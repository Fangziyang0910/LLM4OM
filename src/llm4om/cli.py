"""Command line: serve the Web workbench, run one problem, or build the solver sandbox image."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from llm4om.languages import LANGUAGES
from llm4om.sandbox import WORKER_IMAGE


def _print_step(step: dict[str, Any]) -> None:
    if step.get("running"):
        return
    extra = f" · {step['status']}" if step.get("status") else ""
    print(f"  [{step['type']}] {step['title']}{extra}", file=sys.stderr)


async def _run(args: argparse.Namespace) -> int:
    from llm4om.graph import Resources, run
    from llm4om.llm_presets import LLMPresetStore
    from llm4om.sandbox import Sandbox, SolveResult

    try:
        problem = args.problem if args.problem is not None else Path(args.file).read_text(encoding="utf-8")
        data = {Path(item).name: Path(item).read_text(encoding="utf-8") for item in args.data}
    except OSError as error:
        raise ValueError(f"Cannot read {error.filename}: {error.strerror}.") from error
    resources = Resources(LLMPresetStore(Path(args.workspace)), Sandbox(args.sandbox))
    state = await run(problem, method=args.method, language=args.language, data=data,
                      preset=args.preset, resources=resources, on_step=_print_step)
    if args.output:
        Path(args.output).write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    if state.get("failure"):
        print(f"Failed: {state['failure']}")
        return 1
    solve = SolveResult(**state["solve"]) if state.get("solve") else None
    print("\n=== Mathematical formulation ===\n" + (state.get("formulation") or "(none)"))
    print("\n=== Code ===\n" + (state.get("code") or "(none)"))
    print("\n=== Solve result ===\n" + (solve.feedback() if solve else "(not solved)"))
    return 0 if solve is not None and solve.executed else 1


def _serve(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv
    from langgraph_api.cli import run_server

    from llm4om.methods import methods

    load_dotenv()  # read .env from where the command starts, before moving into the workspace
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["LLM4OM_WORKSPACE"] = str(workspace)
    os.environ["LLM4OM_SANDBOX"] = args.sandbox
    # The LangGraph server keeps threads, runs and checkpoints in .langgraph_api under the working directory.
    os.chdir(workspace)
    graphs = {method.id: {"path": f"llm4om.server.graphs:{method.id}", "description": method.description}
              for method in methods().values()}
    local = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    reach = "; other machines use this machine's address" if args.host == "0.0.0.0" else ""
    print(f"LLM4OM: http://{local}:{args.port}{reach}  (runs are kept in {workspace})", file=sys.stderr)
    run_server(host=args.host, port=args.port, graphs=graphs, n_jobs_per_worker=args.jobs, open_browser=False,
               http={"app": "llm4om.server.app:app", "cors": {"allow_origins": []}},
               server_level="WARNING")
    return 0


def _build_worker(args: argparse.Namespace) -> int:
    sandbox = files("llm4om.sandbox")
    with tempfile.TemporaryDirectory() as directory:
        for name in ("worker.Dockerfile", "worker.py"):
            (Path(directory) / name).write_text(sandbox.joinpath(name).read_text("utf-8"), encoding="utf-8")
        return subprocess.run(["docker", "build", "-f", str(Path(directory) / "worker.Dockerfile"), "-t", args.tag, directory]).returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="llm4om", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Start the Web workbench on the LangGraph server.")
    serve.add_argument("--workspace", default="runs/web", help="Directory for LLM presets and run history.")
    serve.add_argument("--host", default="0.0.0.0", help="Address to listen on; 127.0.0.1 keeps the workbench on this machine.")
    serve.add_argument("--port", type=int, default=8767)
    serve.add_argument("--jobs", type=int, default=4, help="Runs that may execute at the same time.")
    serve.add_argument("--sandbox", choices=("docker", "local"), default="docker",
                       help="Where generated code runs; 'local' skips isolation and is for development only.")

    run = commands.add_parser("run", help="Model and solve one problem.")
    source = run.add_mutually_exclusive_group(required=True)
    source.add_argument("--problem", help="Problem description text.")
    source.add_argument("--file", help="UTF-8 file with the problem description.")
    run.add_argument("--data", action="append", default=[], help="Attach a CSV or JSON data file; repeatable.")
    run.add_argument("--method", default="direct")
    run.add_argument("--language", default="pyomo", choices=list(LANGUAGES), help="Code language, which decides the solver: "
                     + ", ".join(f"{item.id} ({item.solver})" for item in LANGUAGES.values()) + ".")
    run.add_argument("--preset", help="LLM preset id; default: the first preset.")
    run.add_argument("--workspace", default="runs/web", help="Directory with the saved LLM presets.")
    run.add_argument("--sandbox", choices=("docker", "local"), default="docker")
    run.add_argument("--output", help="Write the final state (steps included) to this JSON file.")

    build = commands.add_parser("build-worker", help="Build the Docker image that runs generated code and solvers.")
    build.add_argument("--tag", default=WORKER_IMAGE)

    args = parser.parse_args(argv)
    if args.command == "serve":
        return _serve(args)
    if args.command == "run":
        try:
            return asyncio.run(_run(args))
        except ValueError as error:
            print(f"Error: {error}", file=sys.stderr)
            return 2
    return _build_worker(args)


if __name__ == "__main__":
    sys.exit(main())
