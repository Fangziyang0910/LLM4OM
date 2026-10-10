"""Measure the real offline batch entry point against equivalent direct CLI tasks."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import sys
import time
from typing import Any

import yaml

from llm4om import import_dataset, run_experiment
from llm4om.application import _sdk_sha256


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def reference(path: Path, original: dict[str, Any]) -> dict[str, Any]:
    raw = path.read_bytes()
    return {**original, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    assert not (root / "batch").exists(), "Preserve prior acceptance evidence; choose a new output."
    cpu = Path("/sys/fs/cgroup/cpu.max").read_text().strip()
    memory = Path("/sys/fs/cgroup/memory.max").read_text().strip()
    quota, period = cpu.split()
    assert quota != "max" and int(quota) / int(period) == 4, "Require4 vCPU cgroup."
    assert memory == str(8 * 1024 ** 3), "Require8 GiB cgroup."
    source = root / "fixtures"
    shutil.copytree(args.fixtures, source)
    manifest = import_dataset(source / "import-checker.json", root / "task")
    entry = json.loads(manifest.read_text())["cases"][0]
    public = manifest.parent / entry["public_ref"]["relative_path"]
    packet = root / "packet"
    packet.mkdir()
    shutil.copyfile(public, packet / "problem.json")
    problem = json.loads(public.read_text())
    for ref in problem["data_refs"]:
        target = packet / ref["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(public.parent / ref["path"], target)
    ir = json.loads((source / "model-ir.json").read_text())
    ir.update(problem_id=problem["problem_id"], problem_revision=problem["revision"])
    write(packet / "model-ir.json", ir)
    formulation = json.loads((source / "formulation.json").read_text())
    formulation.update(problem_id=problem["problem_id"], problem_revision=problem["revision"])
    formulation["structured_ir_ref"] = reference(packet / "model-ir.json", formulation["structured_ir_ref"])
    write(packet / "formulation.json", formulation)
    artifact = json.loads((source / "model-artifact.json").read_text())
    artifact["problem_ref"] = {**reference(packet / "problem.json", artifact["problem_ref"]), "artifact_id": problem["problem_id"]}
    artifact["formulation_ref"] = reference(packet / "formulation.json", artifact["formulation_ref"])
    write(packet / "model-artifact.json", artifact)
    config = yaml.safe_load((source / "solve.yaml").read_text())
    config["llm"]["config"]["response_artifact"] = "packet/model-artifact.json"
    write(root / "run.json", config)
    spec = {"schema_version": "0.1.0", "experiment_id": "offline-reference-1000",
        "tasks": [{"id": "production", "manifest": str(manifest)}],
        "configurations": [{"id": "direct-offline", "run_config": "run.json"}], "repeats": 1000,
        "budget": {"max_llm_attempts": 1000 * config["budget"]["max_llm_attempts"],
            "max_total_tokens": 1000 * config["budget"]["max_total_tokens"],
            "max_solver_calls": 1000 * config["budget"]["max_solver_calls"],
            "wall_time_s": 3600, "max_concurrency": 4}, "exclusions": []}
    write(root / "experiment.json", spec)

    def direct(index: int) -> float:
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-m", "llm4om", "run", "--problem", str(packet / "problem.json"),
            "--config", str(root / "run.json"), "--output", str(root / "baseline" / str(index)), "--offline"],
            capture_output=True, check=True)
        run = json.loads(result.stdout)
        subprocess.run([sys.executable, "-m", "llm4om", "evaluate", "--manifest", str(manifest),
            "--case-id", entry["case_id"], "--run", run["bundle_path"], "--output", str(root / ("baseline-" + str(index) + ".json"))],
            capture_output=True, check=True)
        return time.monotonic() - started

    with ThreadPoolExecutor(max_workers=4) as pool:
        baseline = list(pool.map(direct, range(64)))
    # Four declared warm-up tasks are excluded before observing the batch results.
    baseline = baseline[4:]
    write(root / "baseline-timings.json", {"elapsed_s": baseline, "concurrency": 4, "warmup_excluded": 4})
    print("Direct CLI baseline complete; starting1000 offline tasks.", flush=True)
    started = time.monotonic()
    summary = run_experiment(root / "experiment.json", root / "batch", offline=True)
    elapsed = time.monotonic() - started
    rows = [json.loads(line) for line in (root / "batch/reports/results.jsonl").read_text().splitlines()]
    assert len(rows) == 1000 and len({row["job_id"] for row in rows}) == 1000
    assert all(row["status"] == "artifact_ready" and row["run_id"] for row in rows), "No missing/failed offline task."
    assert len({row["run_id"] for row in rows}) == 1000
    median = statistics.median(baseline)
    overhead = sorted(row["elapsed_s"] - median for row in rows)
    p95 = overhead[math.ceil(0.95 * len(overhead)) - 1]
    record = {"runtime": {"python": platform.python_version(), "platform": platform.platform(), "sdk_sha256": _sdk_sha256(),
        "cpu_max": cpu, "memory_max": memory}, "N_selected": len(rows), "N_saved": len(rows),
        "baseline_N": len(baseline), "baseline_median_s": median, "batch_wall_time_s": elapsed,
        "scheduled_task_elapsed_s": [row["elapsed_s"] for row in rows], "extra_time_p95_s": p95,
        "pass_500ms": p95 <= 0.5, "usage": {"external_llm_requests": 0, "solver_calls": 0},
        "measurement": "Per-dispatched task run+evaluation wall time minus median equivalent direct CLI run+evaluation with concurrency4. Queue wait and full batch preflight/report are separately included only in batch_wall_time_s; no LLM/Solver/container-start time occurs in these offline tasks.",
        "summary_sha256": hashlib.sha256((root / "batch/reports/summary.json").read_bytes()).hexdigest()}
    write(root / "performance.json", record)
    print(json.dumps({key: record[key] for key in ("N_saved", "batch_wall_time_s", "extra_time_p95_s", "pass_500ms")}), flush=True)
    assert p95 <= 0.5, "Measured scheduling extra time exceeds500ms; preserve failed acceptance."
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
