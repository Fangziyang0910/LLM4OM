"""A thin CLI over the single-problem application use case."""

import argparse
import json
import sys
from pathlib import Path

from llm4om.application import run_problem


def main() -> int:
    parser = argparse.ArgumentParser(prog="llm4om")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Replay a Mock Formulation; optionally compile and solve grounded LPIR")
    run.add_argument("--problem", type=Path, required=True)
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--output", type=Path, help="Override the configured filesystem store root")
    run.add_argument("--offline", action="store_true", help="Only replay Mock artifacts; skip Code and Solve")
    args = parser.parse_args()
    try:
        result = run_problem(args.problem, args.config, offline=args.offline, output_root=args.output)
    except OSError:
        print(json.dumps({"error": {"code": "store_unavailable", "stage": "storage",
                                   "message": "Cannot persist run evidence to the selected store."}}), file=sys.stderr)
        return 2
    print(json.dumps({"run_id": result.run_id, "bundle_path": str(result.bundle_path), "status": result.status}))
    return 0 if result.status in {"artifact_ready", "completed"} else 1
