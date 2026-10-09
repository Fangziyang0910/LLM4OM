"""Verify real isolated solving from the public application CLI."""

import json
import subprocess
import sys
import tempfile
import unittest
import hashlib
import shutil
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class ContainerRunTests(unittest.TestCase):
    def docker_fixture(self, command: str, *, runtime: dict, solve: dict | None = None) -> tuple[subprocess.CompletedProcess, Path]:
        # Substitute the external Docker protocol only; real resource tests remain separate.
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        docker = root / "docker"
        docker.write_text(f"#!{sys.executable}\n" + '''import json, os, sys
from pathlib import Path
operation = sys.argv[1]
mode = Path(__file__).with_name("worker-mode")
if operation == "version":
    print("29.6.2")
elif operation == "image":
    print(json.dumps([{"Id": "sha256:fixture", "Config": {"Labels": {}}}]))
elif operation == "create":
    mode.write_text("runtime" if "--runtime" in sys.argv else "solve")
    print("fixture-container")
elif operation == "start":
    print(os.environ["WORKER_RUNTIME_FIXTURE" if mode.read_text() == "runtime" else "WORKER_SOLVE_FIXTURE"])
elif operation == "inspect":
    print(json.dumps([{"State": {"ExitCode": 0, "OOMKilled": False, "Running": False},
        "Config": {"User": "65532:65532"}, "HostConfig": {"NetworkMode": "none",
        "ReadonlyRootfs": True, "Memory": 536870912, "MemorySwap": 536870912,
        "NanoCpus": 1000000000, "PidsLimit": 64, "CapDrop": ["ALL"],
        "SecurityOpt": ["no-new-privileges"]}, "Mounts": []}]))
''')
        docker.chmod(0o755)
        arguments = [sys.executable, "-m", "llm4om", command, "--config", str(ROOT / "examples/specs/run.yaml")]
        if command == "run":
            arguments += ["--problem", str(ROOT / "examples/specs/problem.json"), "--output", str(root / "runs")]
        result = subprocess.run(arguments, capture_output=True, text=True, timeout=15,
            env={**os.environ, "PATH": str(root) + os.pathsep + os.defpath,
                 "WORKER_RUNTIME_FIXTURE": json.dumps(runtime), "WORKER_SOLVE_FIXTURE": json.dumps(solve)})
        return result, root

    def test_doctor_rejects_incomplete_worker_runtime_before_the_method_runs(self) -> None:
        result, _ = self.docker_fixture("doctor", runtime={"schema_version": "0.2.0", "runtime": {"packages": []}})
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        report = json.loads(result.stdout)
        self.assertFalse(report["preflight_ok"])
        self.assertEqual(report["error"]["code"], "executor_unavailable")

    def test_incompatible_worker_response_does_not_become_a_solve_result(self) -> None:
        runtime = {"schema_version": "0.2.0", "runtime": {"python": "3.12.15", "llm4om": "0.3.0",
            "packages": {"Pyomo": "6.10.1", "highspy": "1.15.1"}}}
        for schema_version in ("999.0.0", "0.2.0"):
            with self.subTest(schema_version=schema_version):
                payload = {"schema_version": schema_version, "runtime": runtime["runtime"],
                    "result": {"variables": {"qty_A": 3, "qty_B": 2}, "termination": "optimal"}, "resources": {}}
                result, _ = self.docker_fixture("run", runtime=runtime, solve=payload)
                self.assertTrue(result.stdout, result.stderr)
                self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
                path = Path(json.loads(result.stdout)["bundle_path"])
                bundle = json.loads((path / "bundle.json").read_text())
                self.assertEqual(bundle["error"]["code"], "worker_protocol_error")
                self.assertIsNone(bundle["solve_result_ref"])
                self.assertIsNotNone(bundle["execution_result_ref"])

    def test_output_limit_keeps_execution_evidence_without_a_solve_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inputs = Path(directory) / "inputs"
            shutil.copytree(ROOT / "examples/specs", inputs)
            config = yaml.safe_load((inputs / "run.yaml").read_text())
            config["executor"]["config"]["output_limit_bytes"] = 512
            config_path = inputs / "run.yaml"
            config_path.write_text(yaml.safe_dump(config))
            result = subprocess.run([sys.executable, "-m", "llm4om", "run", "--problem", str(inputs / "problem.json"),
                "--config", str(config_path), "--output", directory], capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            path = Path(json.loads(result.stdout)["bundle_path"])
            bundle = json.loads((path / "bundle.json").read_text())
            self.assertEqual(bundle["error"]["code"], "execution_output_limit")
            self.assertIsNone(bundle["solve_result_ref"])
            execution = json.loads((path / bundle["execution_result_ref"]["relative_path"]).read_text())
            self.assertTrue(execution["output_truncated"])
            self.assertEqual(execution["image_id"], json.loads((path / "admission-plan.json").read_text())["worker"]["image_id"])
            self.assertEqual(execution["worker_status"], "output_limit")
            self.assertIsNone(execution["resources"]["cpu_time_s"])
            output = (path / execution["stdout_ref"]["relative_path"]).read_bytes()
            self.assertGreater(len(output), 0)
            self.assertLessEqual(len(output), 512)

    def test_public_problem_is_really_solved_in_the_container(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-m", "llm4om", "run", "--problem", str(ROOT / "examples/specs/problem.json"),
                "--config", str(ROOT / "examples/specs/run.yaml"), "--output", directory], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            path = Path(json.loads(result.stdout)["bundle_path"])
            bundle = json.loads((path / "bundle.json").read_text())
            self.assertEqual(bundle["mode"], "container")
            solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
            self.assertEqual(solve["termination"], "optimal")
            self.assertAlmostEqual(solve["objective_value"], 13)
            self.assertEqual(solve["evidence_origin"], "trusted_container_worker")
            execution = json.loads((path / bundle["execution_result_ref"]["relative_path"]).read_text())
            self.assertEqual(execution["mode"], "container")
            self.assertEqual(execution["restrictions"]["network"], "none")
            self.assertTrue(execution["restrictions"]["read_only"])

    def test_worker_rejects_a_forged_code_artifact_before_solving(self) -> None:
        from llm4om.executors import run_container
        from llm4om.linear import compile_ir
        ir = json.loads((ROOT / "examples/specs/model-ir.json").read_text())
        code = compile_ir(ir)
        request = {"ir": ir, "source_sha256": hashlib.sha256(code.source.encode()).hexdigest(), "solver_options": {}}
        execution = run_container(["python", "-I", "-m", "llm4om.worker", "--solve", "/input/request.json"], {
            "request.json": json.dumps(request).encode(),
            "model.py": b"print('forged objective 123456')\n"}, {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 10})
        self.assertEqual(execution.exit_code, 1)
        payload = json.loads(execution.stdout)
        self.assertEqual(payload["error"]["code"], "code_hash_mismatch")
        self.assertNotIn("result", payload)
        self.assertNotIn(b"forged objective", execution.stdout)


if __name__ == "__main__":
    unittest.main()
