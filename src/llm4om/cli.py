"""A thin CLI over the single-problem application use case."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from llm4om.application import run_problem
from llm4om.tasks import import_dataset
from llm4om.evaluation import evaluate_case
from llm4om.plugins import discover_methods
from llm4om.contracts import RunError, read_config
from llm4om.preflight import prepare_run


def main() -> int:
    parser = argparse.ArgumentParser(prog="llm4om")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Generate or replay Formulation; compile and solve grounded LPIR")
    run.add_argument("--problem", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, help="Override the configured filesystem store root")
    run.add_argument("--offline", action="store_true", help="Only replay Mock artifacts; skip Code and Solve")
    importer = commands.add_parser("import", help="Freeze a local NL4Opt split")
    importer.add_argument("--config", type=Path, required=True)
    importer.add_argument("--output", type=Path, required=True)
    evaluator = commands.add_parser("evaluate", help="Evaluate one frozen case after modeling")
    evaluator.add_argument("--manifest", type=Path, required=True)
    evaluator.add_argument("--case-id", required=True)
    evaluator.add_argument("--run", type=Path, required=True)
    evaluator.add_argument("--output", type=Path, required=True)
    plugins = commands.add_parser("plugins", help="Inspect installed modeling methods")
    plugins.add_subparsers(dest="plugin_command", required=True).add_parser("list")
    doctor = commands.add_parser("doctor", help="Check compatibility, installed dependencies and admission without a model request")
    doctor.add_argument("--config", type=Path, required=True)
    doctor.add_argument("--offline", action="store_true")
    args = parser.parse_args()
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
            inventory = discover_methods()
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
            plan = prepare_run(read_config(args.config), offline=args.offline, config_dir=args.config.parent)
            report.update(preflight_ok=True, execution_plan=plan.snapshot, error=None)
        except (RunError, OSError) as error:
            report.update(preflight_ok=False, execution_plan=None, error={
                "code": error.code if isinstance(error, RunError) else "config_unavailable",
                "stage": "admission", "message": str(error) if isinstance(error, RunError) else "Cannot read RunConfig.",
                "details": error.details if isinstance(error, RunError) else None})
        print(json.dumps(report))
        return 0 if report["preflight_ok"] else 1
    try:
        result = run_problem(args.problem, args.config, offline=args.offline, output_root=args.output)
    except OSError:
        print(json.dumps({"error": {"code": "store_unavailable", "stage": "storage",
                                   "message": "Cannot persist run evidence to the selected store."}}), file=sys.stderr)
        return 2
    print(json.dumps({"run_id": result.run_id, "bundle_path": str(result.bundle_path), "status": result.status}))
    return 0 if result.status in {"artifact_ready", "completed"} else 1
