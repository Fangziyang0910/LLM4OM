"""Optimization tools and host-model skills; optional API-model runs and Web workbench."""

import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from importlib.metadata import version
from importlib.resources import files
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm4om.languages import LANGUAGES, CodeTarget
from llm4om.sandbox import WORKER_IMAGE

HOST_COMMANDS = {"start", "resume", "status"}


def _print_step(step: dict[str, Any]) -> None:
    if step.get("running"):
        return
    extra = f" · {step['status']}" if step.get("status") else ""
    print(f"  [{step['type']}] {step['title']}{extra}", file=sys.stderr)


def _read(path: str) -> str:
    try:
        with Path(path).open("rb") as stream:
            prefix = stream.read(2)
            stream.seek(0)
            encoding = "utf-16" if prefix in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
            with TextIOWrapper(stream, encoding=encoding) as text:
                return text.read()
    except UnicodeDecodeError as error:
        raise ValueError(f"Cannot decode {path}. Save it as UTF-8 or UTF-16 with a byte order mark.") from error
    except OSError as error:
        raise ValueError(f"Cannot read {error.filename}: {error.strerror}.") from error


def _problem(args: argparse.Namespace) -> str:
    return args.problem if args.problem is not None else _read(args.file)


def _data(paths: list[str]) -> dict[str, str]:
    data = {}
    for path in paths:
        name = Path(path).name
        if name in data:
            raise ValueError(f"Duplicate attachment name {name!r}; give the files distinct names.")
        data[name] = _read(path)
    return data


def _json(value: Any, output: str | None = None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if output:
        Path(output).write_text(text, encoding="utf-8")
    print(text, end="")


async def _solve(args: argparse.Namespace) -> int:
    from dataclasses import asdict

    from llm4om.sandbox import Sandbox

    if not math.isfinite(args.time_limit) or args.time_limit <= 0:
        raise ValueError("The solve time limit must be finite and positive.")
    result = await Sandbox(args.sandbox).solve(_read(args.code), _data(args.data), args.language,
                                              args.time_limit, solver=args.solver)
    _json(asdict(result), args.output)
    return 0 if result.executed else 1


async def host_result(args: argparse.Namespace, prepare_worker: Callable[[], None] | None = None) -> dict[str, Any]:
    """Run a host command and return the full result for the caller to present."""
    from llm4om.host import resume, start, status

    if args.command == "status":
        return await status(args.session)
    if args.command == "resume":
        answers = json.loads(_read(args.responses))
        if prepare_worker:
            prepare_worker()
        return await resume(args.session, answers)
    problem, data = _problem(args), _data(args.data)
    if prepare_worker:
        prepare_worker()
    directory = args.session or str(Path("runs/host") / uuid4().hex[:12])
    return await start(directory, problem, method=args.method, language=args.language,
                       solver=args.solver, data=data, sandbox=args.sandbox, max_calls=args.max_calls,
                       max_solves=args.max_solves, time_limit=args.time_limit)


async def _run(args: argparse.Namespace) -> int:
    from llm4om.graph import run
    from llm4om.sandbox import SolveResult

    problem, data = _problem(args), _data(args.data)
    state = await run(problem, method=args.method, language=args.language, data=data,
                      solver=args.solver, preset=args.preset, workspace=args.workspace,
                      sandbox=args.sandbox, on_step=_print_step, time_limit=args.time_limit)
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

    load_dotenv(Path.cwd() / ".env")
    jobs = args.jobs if args.jobs is not None else int(os.environ.get("LLM4OM_RUN_JOBS") or 4)
    if jobs < 0:
        raise ValueError("The run concurrency cannot be negative.")
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    os.environ["LLM4OM_WORKSPACE"] = str(workspace)
    os.environ["LLM4OM_SANDBOX"] = args.sandbox
    # The LangGraph server keeps threads, runs and checkpoints in .langgraph_api under the working directory.
    os.chdir(workspace)
    graphs = {method.id: {"path": f"llm4om.server.graphs:{method.id}", "description": method.description}
              for method in methods().values()}
    graphs["requirements"] = {"path": "llm4om.server.graphs:requirements", "description": "Discuss and prepare business requirements"}
    graphs["solution_chat"] = {"path": "llm4om.server.graphs:solution_chat", "description": "Discuss and revise computed plans"}
    graphs["optimization"] = {"path": "llm4om.server.graphs:optimization", "description": "Converse, model, solve and revise optimization problems"}
    local = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    reach = "; other machines use this machine's address" if args.host == "0.0.0.0" else ""
    print(f"LLM4OM: http://{local}:{args.port}{reach}  (runs are kept in {workspace})", file=sys.stderr)
    run_server(host=args.host, port=args.port, graphs=graphs, n_jobs_per_worker=jobs, open_browser=False,
               http={"app": "llm4om.server.app:app", "cors": {"allow_origins": []},
                     "disable_mcp": True, "disable_a2a": True},
               server_level="WARNING")
    return 0


def _build_worker(args: argparse.Namespace) -> int:
    sandbox = files("llm4om.sandbox")
    with tempfile.TemporaryDirectory() as directory:
        for name in ("worker.Dockerfile", "worker.py"):
            (Path(directory) / name).write_text(sandbox.joinpath(name).read_text("utf-8"), encoding="utf-8")
        autoco_dir = Path(directory) / "autoco"
        autoco_dir.mkdir()
        for item in sandbox.joinpath("autoco").iterdir():
            if item.is_file() and item.name.endswith(".py"):
                (autoco_dir / item.name).write_text(item.read_text("utf-8"), encoding="utf-8")
        return subprocess.run(["docker", "build", "-f", str(Path(directory) / "worker.Dockerfile"), "-t", args.tag, directory]).returncode


def command_parser(*, for_skill: bool = False) -> argparse.ArgumentParser:
    """Build the standalone CLI or the Docker-only skill command surface."""
    description = "Model and solve using the current agent and Docker." if for_skill else __doc__
    parser = argparse.ArgumentParser(prog=None if for_skill else "llm4om", description=description)
    if not for_skill:
        parser.add_argument("--version", action="version", version=f"LLM4OM {version('llm4om')}")
    commands = parser.add_subparsers(dest="command", required=True)

    target_options = argparse.ArgumentParser(add_help=False)
    target_options.add_argument("--language", default="pyomo", help="Modeling library: " + ", ".join(LANGUAGES) + ".")
    target_options.add_argument("--solver", help="Native backend identifier; default: AUTO (the code's native backend).")
    environment = argparse.ArgumentParser(add_help=False)
    if for_skill:
        environment.set_defaults(sandbox="docker")
    else:
        environment.add_argument("--sandbox", choices=("docker", "local"), default="docker")
    inputs = argparse.ArgumentParser(add_help=False, parents=[target_options, environment])
    inputs.add_argument("--data", action="append", default=[], help="Attach a CSV or JSON data file; repeatable.")

    commands.add_parser("methods", help="List modeling methods and their fixed parameters as JSON.")
    commands.add_parser("target", parents=[target_options], help="Print the selected library's code contract and reference.")
    commands.add_parser("backends", parents=[environment], help="Discover solver backends in the execution environment.")
    solve = commands.add_parser("solve", parents=[inputs], help="Execute existing build_model(data) code.")
    solve.add_argument("--code", required=True, help="Python file defining build_model(data).")
    solve.add_argument("--time-limit", type=float, default=60, help="Time limit in seconds (default: 60).")
    solve.add_argument("--output", help="Also write the JSON solve result to this file.")

    modeling = argparse.ArgumentParser(add_help=False, parents=[inputs])
    if for_skill:
        modeling.set_defaults(problem=None)
        modeling.add_argument("--file", required=True, help="Problem description file.")
        host_commands = commands
    else:
        source = modeling.add_mutually_exclusive_group(required=True)
        source.add_argument("--problem", help="Problem description text.")
        source.add_argument("--file", help="Problem description file.")
        host = commands.add_parser("host", help="Run methods using answers from the current coding agent; no LLM API.")
        host_commands = host.add_subparsers(dest="command", required=True)
    modeling.add_argument("--method", default="direct")
    start = host_commands.add_parser("start", parents=[modeling], help="Start a method and return pending requests as JSON.")
    session_help = "New session directory." if for_skill else "New session directory; default: runs/host/<random-id>."
    start.add_argument("--session", required=for_skill, help=session_help)
    start.add_argument("--max-calls", type=int, help="Cap host-model requests, including parallel requests.")
    start.add_argument("--max-solves", type=int)
    start.add_argument("--time-limit", type=float, help="Time limit of each solve or check script, in seconds.")
    resume = host_commands.add_parser("resume", help="Submit a JSON mapping of pending request IDs to model answers.")
    resume.add_argument("--session", required=True)
    resume.add_argument("--responses", required=True, help="UTF-8 JSON file: {request_id: {content, tool_calls}}.")
    status = host_commands.add_parser("status", help="Read pending tasks and results without executing anything.")
    status.add_argument("--session", required=True)
    if for_skill:
        return parser

    serve = commands.add_parser("serve", help="Start the Web workbench on the LangGraph server.")
    serve.add_argument("--workspace", default="runs/web", help="Directory for LLM presets and run history.")
    serve.add_argument("--host", default="0.0.0.0", help="Address to listen on; 127.0.0.1 keeps the workbench on this machine.")
    serve.add_argument("--port", type=int, default=8767)
    serve.add_argument("--jobs", type=int, help="Simultaneous runs. Defaults to LLM4OM_RUN_JOBS or 4.")
    serve.add_argument("--sandbox", choices=("docker", "local"), default="docker",
                       help="Where generated code runs; 'local' skips isolation and is for development only.")

    run = commands.add_parser("run", parents=[modeling], help="Model and solve one problem.")
    run.add_argument("--time-limit", type=float, help="Time limit per solve in seconds (5–300); defaults to the method setting.")
    run.add_argument("--preset", help="LLM preset id; default: the first preset.")
    run.add_argument("--workspace", default="runs/web", help="Directory with the saved LLM presets.")
    run.add_argument("--output", help="Write the final state (steps included) to this JSON file.")

    build = commands.add_parser("build-worker", help="Build the Docker image that runs generated code and solvers.")
    build.add_argument("--tag", default=WORKER_IMAGE)

    return parser


def run_tool(args: argparse.Namespace) -> int:
    """Execute a parsed solver tool and write its command-line output."""
    if args.command == "methods":
        from llm4om.methods import methods

        _json([{"id": method.id, "name": method.name, "source": method.source,
                "linear_only": method.linear_only, "builtin_solver": method.builtin_solver,
                "parameters": method.parameters(),
                "languages": sorted(LANGUAGES if method.languages is None else method.languages)} for method in methods().values()])
        return 0
    if args.command == "target":
        print(CodeTarget(args.language, args.solver).prompt)
        return 0
    if args.command == "backends":
        from llm4om.sandbox import Sandbox

        _json(asyncio.run(Sandbox(args.sandbox).catalog()))
        return 0
    if args.command == "solve":
        return asyncio.run(_solve(args))
    raise ValueError(f"Unknown solver tool {args.command!r}.")


def main(argv: list[str] | None = None) -> int:
    args = command_parser().parse_args(argv)
    try:
        if args.command in HOST_COMMANDS:
            result = asyncio.run(host_result(args))
            _json(result)
            return int(result["status"] == "failed")
        if args.command == "serve":
            return _serve(args)
        if args.command == "run":
            return asyncio.run(_run(args))
        if args.command == "build-worker":
            return _build_worker(args)
        return run_tool(args)
    except ModuleNotFoundError as error:
        if args.command not in {"run", "serve"}:
            raise
        extra = "web" if args.command == "serve" else "llm"
        print(f"Error: Missing {error.name}. Install llm4om[{extra}] to use '{args.command}'.", file=sys.stderr)
        return 2
    except (ValueError, OSError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        message = "Interrupted."
        if args.command in HOST_COMMANDS:
            message += " Inspect with 'llm4om host status' and resume the saved session."
        print(message, file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
