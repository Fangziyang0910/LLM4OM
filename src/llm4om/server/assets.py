"""Serve Vite's content-hashed files and their build-time gzip representations."""

from pathlib import Path
from typing import Literal

from starlette.datastructures import Headers
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send


def preferred_encoding(headers: Headers, has_gzip: bool) -> Literal["gzip", "identity"] | None:
    weights = {}
    for item in ",".join(headers.getlist("accept-encoding")).lower().split(","):
        encoding, _, parameter = item.strip().partition(";")
        try:
            weight = float(parameter.strip().removeprefix("q=").strip()) if parameter else 1.0
        except ValueError:
            continue
        if 0 <= weight <= 1:
            weights[encoding.strip()] = weight
    wildcard = weights.get("*")
    gzip = weights.get("gzip", wildcard or 0) if has_gzip else 0
    if gzip > 0 and gzip >= weights.get("identity", 0):
        return "gzip"
    if weights.get("identity", 0 if wildcard == 0 else 1) > 0:
        return "identity"
    return None


class WorkbenchAssets(StaticFiles):
    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory)
        self.compressed = {path.stem for path in directory.glob("*.gz")}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = Headers(scope=scope)
            if "range" in headers and preferred_encoding(headers, self.get_path(scope) in self.compressed) == "gzip":
                # A range can split a gzip stream. Send the complete selected representation.
                scope = {**scope, "headers": [(key, value) for key, value in scope["headers"] if key != b"range"]}
        await super().__call__(scope, receive, send)

    async def get_response(self, path: str, scope: Scope) -> Response:
        has_gzip = path in self.compressed
        encoding = preferred_encoding(Headers(scope=scope), has_gzip)
        if encoding is None:
            return Response(status_code=406, headers={"Vary": "Accept-Encoding"})
        response = await super().get_response(path + ".gz" if encoding == "gzip" else path, scope)
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
        if has_gzip:
            response.headers.add_vary_header("Accept-Encoding")
        if encoding == "gzip" and response.status_code != 304:
            response.headers["accept-ranges"] = "none"
            response.headers["content-encoding"] = "gzip"
            response.headers["content-type"] = "text/css; charset=utf-8" if path.endswith(".css") else "text/javascript; charset=utf-8"
        return response
