"""A thin CLI over the single-problem application use case."""

import argparse
import json
import sys
import signal
from pathlib import Path
from typing import Any

from llm4om.application import run_problem, resume_run
from llm4om.storage import cancel_run
from llm4om.control import CancellationToken
from llm4om.tasks import import_dataset
from llm4om.evaluation import evaluate_case
from llm4om.plugins import discover_plugins
from llm4om.contracts import RunError, read_config
from llm4om.preflight import prepare_run
from llm4om.task_plugins import prepare_task
from llm4om.experiments import run_experiment, report_experiment


def main() -> int:
    parser = argparse.ArgumentParser(prog="llm4om")
    commands = parser.add_subparsers(dest="command", required=True)
    web = commands.add_parser("serve", help="Open the local single-user optimization workbench")
    web.add_argument("--workspace", type=Path, default=Path("runs/web"))
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--host", default="127.0.0.1", help="Bind address; use 0.0.0.0 for remote access")
    benchmark = commands.add_parser("benchmark", help="Run an explicit frozen task/configuration matrix")
    benchmark.add_argument("--config", type=Path, required=True)
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark.add_argument("--offline", action="store_true")
    benchmark.add_argument("--resume", action="store_true", help="Keep saved completed cases and continue unfinished work")
    report_command = commands.add_parser("report", help="Export public per-case and grouped experiment reports")
    report_command.add_argument("--experiment", type=Path, required=True)
    run = commands.add_parser("run", help="Generate Formulation and Code; solve supported LP/MILP")
    run.add_argument("--problem", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, help="Override the configured filesystem store root")
    run.add_argument("--offline", action="store_true", help="Only replay Mock artifacts; skip Code and Solve")
    run.add_argument("--interactive", action="store_true", help="Persist needs_input for public clarification instead of unresolved")
    for name in ("cancel", "resume"):
        control = commands.add_parser(name, help=f"{name.capitalize()} a persisted run")
        if name == "resume":
            control.add_argument("--answers", type=Path, help="Versioned response to the saved public clarification")
            control.add_argument("--revised-problem", type=Path, help="Explicit new ProblemSpec revision for newly supplied rules/data")
            control.add_argument("--strategy", choices=("continue", "rerun"), default="continue",
                                 help="Continue saved work, or explicitly rerun with parent usage still counted")
        control.add_argument("--run-id", required=True)
        control.add_argument("--output", type=Path, default=Path("runs"), help="Filesystem store root")
    importer = commands.add_parser("import", help="Freeze a declared local task source")
    importer.add_argument("--config", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    evaluator = commands.add_parser("evaluate", help="Evaluate one frozen case after modeling")
    evaluator.add_argument("--manifest", type=Path, required=True)
    evaluator.add_argument("--case-id", required=True)
    evaluator.add_argument("--run", type=Path, required=True)
    evaluator.add_argument("--output", type=Path, required=True)
    plugins = commands.add_parser("plugins", help="Inspect supported installed plugins")
    plugins.add_subparsers(dest="plugin_command", required=True).add_parser("list")
    doctor = commands.add_parser("doctor", help="Check compatibility, installed dependencies and admission without a model request")
    doctor_config = doctor.add_mutually_exclusive_group(required=True)
    doctor_config.add_argument("--config", type=Path)
    doctor_config.add_argument("--task-config", type=Path, help="Preflight Task/Evaluator selections without importing source")
    doctor.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    if args.command in ("benchmark", "report"):
        cancellation = CancellationToken()
        previous = signal.signal(signal.SIGINT, lambda signum, frame: cancellation.cancel())
        try:
            experiment_result = (report_experiment(args.experiment) if args.command == "report" else
                      run_experiment(args.config, args.output, offline=args.offline, resume=args.resume,
                                     cancellation=cancellation))
            print(json.dumps(experiment_result, ensure_ascii=False))
            return 0
        except (RunError, OSError, KeyError, TypeError, ValueError) as error:
            print(json.dumps({"error": {"code": error.code if isinstance(error, RunError) else "experiment_error",
                "message": str(error) if isinstance(error, RunError) else "Cannot read or persist this experiment.",
                "details": error.details if isinstance(error, RunError) else None}}))
            return 1
        finally:
            signal.signal(signal.SIGINT, previous)
    if args.command == "serve":
        from llm4om.web import serve_web
        serve_web(args.workspace, port=args.port, host=args.host)
        return 0
    if args.command == "import":
        try:
            manifest = import_dataset(args.config, args.output)
            print(json.dumps({"manifest_path": str(manifest)}))
            return 0
        except (RunError, OSError, ValueError) as error:
            print(json.dumps({"error": {"code": error.code if isinstance(error, RunError) else "import_error",
                                       "message": str(error) if isinstance(error, RunError) else "Cannot import local snapshot."}}))
            return 1
    if args.command == "evaluate":
        try:
            evaluation_result = evaluate_case(args.manifest, args.case_id, args.run, args.output)
            print(json.dumps(evaluation_result))
            return 1 if evaluation_result["checker_error"] else 0
        except (RunError, OSError, ValueError, KeyError, TypeError) as error:
            print(json.dumps({"error": {"code": error.code if isinstance(error, RunError) else "evaluation_error",
                                       "message": str(error) if isinstance(error, RunError) else "Cannot evaluate frozen case."}}))
            return 1
    if args.command == "plugins":
        try:
            inventory = discover_plugins()
        except RunError as error:
            print(json.dumps({"schema_version": "0.2.0", "plugins": [], "error": {
                "code": error.code, "stage": error.stage, "message": str(error), "details": error.details}}))
            return 1
        print(json.dumps({"schema_version": "0.2.0", "plugins": [
            {"manifest": plugin.manifest, "origin": plugin.origin} for plugin in inventory.values()]}))
        return 0
    if args.command == "doctor":
        report: dict[str, Any] = {"schema_version": "0.2.0", "connectivity_checks": {"status": "not_requested"}}
        try:
            if args.task_config:
                snapshot = prepare_task(args.task_config)
            else:
                plan = prepare_run(read_config(args.config), offline=args.offline, config_dir=args.config.parent)
                snapshot = plan.snapshot
            report.update(preflight_ok=True, execution_plan=snapshot, error=None)
        except (RunError, OSError) as error:
            report.update(preflight_ok=False, execution_plan=None, error={
                "code": error.code if isinstance(error, RunError) else "config_unavailable",
                "stage": "admission", "message": str(error) if isinstance(error, RunError) else "Cannot read RunConfig.",
                "details": error.details if isinstance(error, RunError) else None})
        print(json.dumps(report))
        return 0 if report["preflight_ok"] else 1
    cancellation = CancellationToken()
    previous = signal.signal(signal.SIGINT, lambda signum, frame: cancellation.cancel())
    try:
        if args.command in ("cancel", "resume"):
            if len(args.run_id) != 32 or any(char not in "0123456789abcdef" for char in args.run_id):
                raise RunError("control_incompatible", "control", "Run ID must be a platform UUID.")
            path = args.output / args.run_id
            if args.command == "cancel":
                print(json.dumps({"run_id": args.run_id, "status": cancel_run(path)}))
                return 0
            result = resume_run(path, cancellation=cancellation, strategy=args.strategy, answers=args.answers,
                                revised_problem=args.revised_problem)
        else:
            result = run_problem(args.problem, args.config, offline=args.offline,
                                 output_root=args.output, cancellation=cancellation, interactive=args.interactive)
    except RunError as error:
        print(json.dumps({"error": {"code": error.code, "stage": error.stage, "message": str(error)}}))
        return 1
    except OSError:
        print(json.dumps({"error": {"code": "store_unavailable", "stage": "storage",
                                   "message": "Cannot persist run evidence to the selected store."}}), file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous)
    print(json.dumps({"run_id": result.run_id, "bundle_path": str(result.bundle_path), "status": result.status}))
    return 0 if result.status in {"artifact_ready", "completed", "needs_input"} else 1
