# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = ["llm4om @ https://github.com/Fangziyang0910/LLM4OM/archive/d8fa79384683e166a8ddb708eb36dc040d895783.tar.gz"]
# ///
"""Drive the pinned host runtime from an installed skill. Paths belong to the caller's workspace."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from llm4om import cli, host
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
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("methods", help="List available modeling methods")
    commands.add_parser("backends", help="List solver backends in the Docker worker")
    target = commands.add_parser("target", help="Read the model code contract for a library and solver")
    solve = commands.add_parser("solve", help="Solve an existing model in the Docker worker")
    solve.add_argument("--code", required=True, help="Python file defining build_model(data)")
    solve.add_argument("--output", help="Also write the full solver result to this file")
    start = commands.add_parser("start", help="Start modeling a UTF-8 business problem")
    start.add_argument("--file", required=True)
    start.add_argument("--method", default="direct")
    start.add_argument("--max-calls", type=int)
    start.add_argument("--max-solves", type=int)
    for command in (start, target, solve):
        command.add_argument("--language", default="pyomo")
        command.add_argument("--solver")
    for command in (start, solve):
        command.add_argument("--data", action="append", default=[], help="Attach a data file; repeat for multiple inputs")
        command.add_argument("--time-limit", type=float)
    resume = commands.add_parser("resume", help="Submit host answers and continue the method")
    resume.add_argument("--responses", required=True, help="JSON file mapping pending request IDs to answers")
    status = commands.add_parser("status", help="Read a saved session without advancing it")
    for command in (start, resume, status):
        command.add_argument("--session", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.action in {"methods", "target", "backends", "solve"}:
        if args.action in {"backends", "solve"}:
            prepare_worker()
        return cli.main(argv)

    if args.action == "start":
        problem, data = cli._read(args.file), cli._data(args.data)
        prepare_worker()
        result = asyncio.run(host.start(args.session, problem, method=args.method, language=args.language,
                                        solver=args.solver, data=data, max_calls=args.max_calls,
                                        max_solves=args.max_solves, time_limit=args.time_limit))
    elif args.action == "resume":
        answers = json.loads(cli._read(args.responses))
        prepare_worker()
        result = asyncio.run(host.resume(args.session, answers))
    else:
        result = asyncio.run(host.status(args.session))
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
