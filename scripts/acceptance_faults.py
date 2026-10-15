"""Run100 isolated CLI tasks with synthetic HTTP faults and actual HiGHS."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time
from typing import Any

import yaml


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / "rows.json").exists(), "Keep previous acceptance records."
    fixture = root / "fixtures"
    shutil.copytree(args.fixtures, fixture)
    os.environ["LLM4OM_FAULT_TEST_KEY"] = "synthetic-fault-acceptance-key"
    representation = json.loads((fixture / "formulation.json").read_text())["representation"]
    for parameter, value in zip(representation["parameters"], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
        parameter.pop("source")
        parameter["value"] = value
    ir = json.loads((fixture / "model-ir.json").read_text())
    compact = {"representation": representation, "structured_ir": {key: ir[key] for key in ("problem_type", "variables", "objective", "constraints", "assumptions")}}
    requests: dict[str, int] = {}
    starts: dict[str, threading.Event] = {}
    releases: dict[str, threading.Event] = {}
    lock = threading.Lock()

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            model = request["model"]
            with lock:
                requests[model] = requests.get(model, 0) + 1
                starts[model].set()
            if model.startswith("cancel-"):
                releases[model].wait(timeout=15)
            if model.startswith("timeout-"):
                time.sleep(2)
            code = 429 if model.startswith("rate-") else 200
            content = "{bad-json" if model.startswith("malformed-") else json.dumps(compact)
            raw = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}}).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args: Any) -> None:
            pass

    provider = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=provider.serve_forever, daemon=True)
    thread.start()
    scenarios = [f"{kind}-{index}" for index in range(20) for kind in ("normal", "malformed", "rate", "timeout", "cancel")]
    for scenario in scenarios:
        starts[scenario] = threading.Event()
        releases[scenario] = threading.Event()

    def invoke(arguments: list[str]) -> dict[str, Any]:
        completed = subprocess.run([sys.executable, "-m", "llm4om", *arguments], capture_output=True, timeout=30)
        return json.loads(completed.stdout)

    def execute(model: str) -> dict[str, Any]:
        output = root / model
        output.mkdir()
        config = yaml.safe_load((fixture / "solve.yaml").read_text())
        config["llm"] = {"provider_plugin_id": "llm4om.providers.openai_compatible", "model": model,
            "config": {"base_url": f"http://127.0.0.1:{provider.server_port}/v1", "credential_env": "LLM4OM_FAULT_TEST_KEY",
                "max_retries": 1 if model.startswith("rate-") else 0, "timeout_s": 0.5 if model.startswith("timeout-") else 10,
                "max_output_tokens": 8192}}
        config["budget"].update(max_llm_attempts=4, max_total_tokens=100000, max_solver_calls=4, max_checks=4)
        write(output / "config.json", config)
        command = ["run", "--problem", str(fixture / "problem.json"), "--config", str(output / "config.json"),
                   "--output", str(output / "runs")]
        process = subprocess.Popen([sys.executable, "-m", "llm4om", *command], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True)
        try:
            if model.startswith("cancel-"):
                assert starts[model].wait(timeout=15), "Cancellation fixture must reach the actual HTTP request."
                process.send_signal(signal.SIGINT)
            stdout, _ = process.communicate(timeout=30)
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
        record = json.loads(stdout)
        run = Path(record["bundle_path"])
        bundle = json.loads((run / "bundle.json").read_text())
        ledger = json.loads((run / "budget-ledger.json").read_text())
        row = {"scenario": model, "run_id": record["run_id"], "status": record["status"], "error": bundle["error"], "ledger": ledger}
        with lock:
            before = requests[model]
        if model.startswith("normal-"):
            assert record["status"] == "completed"
            solve = json.loads((run / bundle["solve_result_ref"]["relative_path"]).read_text())
            assert solve["objective_value"] == 13 and ledger["solver_calls"] == 1
            continued = invoke(["resume", "--run-id", record["run_id"], "--output", str(output / "runs")])
            assert continued["run_id"] == record["run_id"] and continued["status"] == "completed"
            assert requests[model] == before, "Completed response must not be requested again."
        elif model.startswith("cancel-"):
            assert record["status"] == "cancelled" and ledger["reserved_tokens"] > 0
            releases[model].set()
            continued = invoke(["resume", "--run-id", record["run_id"], "--output", str(output / "runs")])
            assert requests[model] == before, "Unknown outcome cannot be silently requested again."
            row["continue_result"] = continued
            parent_bytes = (run / "bundle.json").read_bytes()
            derived = invoke(["resume", "--run-id", record["run_id"], "--output", str(output / "runs"), "--strategy", "rerun"])
            assert derived["status"] == "completed" and derived["run_id"] != record["run_id"]
            child = Path(derived["bundle_path"])
            child_ledger = json.loads((child / "budget-ledger.json").read_text())
            assert child_ledger["llm_attempts"] == 2 and child_ledger["reserved_tokens"] == ledger["reserved_tokens"]
            assert requests[model] == before + 1
            assert (run / "bundle.json").read_bytes() == parent_bytes
            row.update(derived_run_id=derived["run_id"], derived_ledger=child_ledger,
                parent_bundle_sha256=hashlib.sha256(parent_bytes).hexdigest())
        else:
            assert record["status"] == "failed" and ledger["solver_calls"] == 0
            if model.startswith("rate-"):
                assert ledger["llm_attempts"] == 2 and requests[model] == 2
            else:
                assert ledger["llm_attempts"] == 1 and requests[model] == 1
            if model.startswith("timeout-"):
                assert ledger["total_tokens"] is None and ledger["reserved_tokens"] > 0
        write(output / "outcome.json", row)
        return row

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(execute, scenarios))
        assert len(rows) == 100 and len({row["run_id"] for row in rows}) == 100
        assert len({row.get("derived_run_id") for row in rows if row.get("derived_run_id")}) == 20
        write(root / "rows.json", {"rows": rows})
        result = {"N_selected": 100, "statuses": {status: sum(row["status"] == status for row in rows) for status in ("completed", "failed", "cancelled")},
            "explicit_derived_completed": 20, "completed_reused_without_new_request": 20,
            "requests": requests, "actual_highs_successes": 40, "provider": "synthetic_local_HTTP", "cost": None,
            "concurrency": 4, "policy": "100 original runs retain all terminal outcomes;20 cancelled runs have separately recorded explicit derived reruns and inherited unknown reservations. Synthetic responses are workflow/fault evidence, not modeling accuracy."}
        write(root / "faults.json", result)
        print(json.dumps({key: result[key] for key in ("N_selected", "statuses", "explicit_derived_completed", "actual_highs_successes")}), flush=True)
        return 0
    finally:
        for event in releases.values():
            event.set()
        provider.shutdown()
        provider.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
