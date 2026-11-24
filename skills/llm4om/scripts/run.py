# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["llm4om @ https://github.com/Fangziyang0910/LLM4OM/archive/79b9206210acdd95d2db3b5ca6bdcbf81fa977e8.tar.gz"]
# ///
"""Drive the pinned host runtime from an installed skill. Paths belong to the caller's workspace."""

import asyncio
import json
import subprocess
import sys
from pathlib import Path

from llm4om import cli
from llm4om.sandbox import WORKER_IMAGE


def prepare_worker() -> None:
    # A successful empty listing means the image is missing. A daemon/permission error must not start a build.
    try:
        images = subprocess.run(["docker", "image", "ls", "--quiet", WORKER_IMAGE],
                                capture_output=True, text=True, check=False)
    except FileNotFoundError as error:
        raise RuntimeError("Docker is required for solving. Install and start Docker, then retry.") from error
    if images.returncode:
        raise RuntimeError(f"Cannot access Docker: {images.stderr.strip()}")
    if not images.stdout.strip():
        print(f"Preparing {WORKER_IMAGE} for the first solve…", file=sys.stderr, flush=True)
        # Keep Docker's build progress off the JSON output stream.
        subprocess.run([sys.executable, "-I", "-m", "llm4om.cli", "build-worker"], stdout=sys.stderr, check=True)


def turn_output(result: dict) -> dict:
    reply = {"session": result["session"], "status": result["status"],
             "result_file": str(Path(result["session"]) / "result.json")}
    if result["pending"]:
        reply["pending"] = result["pending"]
        return reply
    if result["failure"]:
        reply["failure"] = result["failure"]
    if solve := result["solve"]:
        summary = {key: solve[key] for key in ("status", "solver", "objective", "error") if solve.get(key) is not None}
        variables = solve["variables"]
        if len(variables) > 25:
            summary["variable_count"] = len(variables)
        elif variables:
            summary["variables"] = variables
        if solve.get("pareto"):
            summary["pareto_count"] = solve["pareto"]["total"]
        reply["solve"] = summary
    return reply


def main(argv: list[str]) -> int:
    args = cli.command_parser(for_skill=True).parse_args(argv)
    if args.command in {"backends", "solve"}:
        prepare_worker()
    if args.command not in cli.HOST_COMMANDS:
        return cli.run_tool(args)
    result = asyncio.run(cli.host_result(args, prepare_worker=prepare_worker))
    print(json.dumps(turn_output(result), ensure_ascii=False))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("Interrupted. Use status to inspect a saved session.", file=sys.stderr)
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(2)
