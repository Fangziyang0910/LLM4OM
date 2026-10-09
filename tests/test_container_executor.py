"""Real Docker behavior at the approved Executor seam."""

import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from time import monotonic
from pathlib import Path
from unittest.mock import patch


class ContainerExecutorTests(unittest.TestCase):
    image = "python@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f"

    def test_invalid_requests_are_rejected_before_contacting_docker(self) -> None:
        from llm4om.contracts import RunError
        from llm4om.executors import run_container

        limits = {"network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10}
        cases = [(command, {}, limits, self.image) for command in
                 ("python", ("python",), None, [], [1], [""], ["python", "\0"], ["\ud800"])]
        cases += [(["python"], {name: b"public"}, limits, self.image) for name in
                  (None, 1, Path("public.csv"), "", ".", "..", "../escape", "/absolute",
                   "a/../b", "a//b", "a/./b", "a/", "a\\b", "a,b", "a\0b", "a\nb", "\ud800")]
        cases += [(["python"], files, limits, self.image) for files in
                  ({"a": b"file", "a/b": b"child"}, {"a/b/c": b"child", "a": b"file"},
                   {"public.csv": "host path"}, {"public.csv": Path("private")}, None, [])]
        for key in ("cpu_limit", "memory_limit_mb", "wall_time_s", "output_limit_bytes", "pids_limit"):
            cases += [(["python"], {}, {**limits, key: value}, self.image) for value in
                      (True, False, None, "1", 0, -1, float("nan"), float("inf"), -float("inf"), 10**1000)]
            if key not in ("cpu_limit", "wall_time_s"):
                cases.append((["python"], {}, {**limits, key: 1.5}, self.image))
        cases += [(["python"], {}, value, self.image) for value in
                  (None, [], {**limits, "network": True}, {**limits, "network": 0}, {**limits, "unknown": 1})]
        for image in (None, 1, True, [], Path("image"), "", "--help", "image\0", "image\n", " image", "\ud800"):
            cases.append((["python"], {}, limits, image))
            cases.append((["python"], {}, {**limits, "image": image}, self.image))
        for index, (command, files, restrictions, image) in enumerate(cases):
            with self.subTest(case=index):
                with self.assertRaises(RunError) as caught:
                    run_container(command, files, restrictions, image=image)
                self.assertEqual(caught.exception.code, "invalid_execution_request")
                self.assertEqual(caught.exception.stage, "admission")

    def run_hanging_docker(self, scenario: str) -> dict:
        # Only daemon/control faults use this external CLI fixture; resource tests use real Docker.
        with tempfile.TemporaryDirectory(prefix="llm4om-control-test-") as directory:
            docker = Path(directory) / "docker"
            docker.write_text(f"#!{sys.executable}\n" + '''import json, os, sys, time
from pathlib import Path
scenario = os.environ["LLM4OM_CONTROL_SCENARIO"]
operation = sys.argv[1]
trace = Path(__file__).with_name("pids")
with trace.open("a") as stream:
    print(os.getpid(), os.getpgrp(), file=stream)
if operation == "create":
    mount = sys.argv[sys.argv.index("--mount") + 1]
    Path(__file__).with_name("public-root").write_text(mount.split("src=", 1)[1].split(",", 1)[0])
if operation == "image":
    operation = "image_inspect"
if operation in scenario.split("+"):
    if "flood" in scenario:
        while True:
            os.write(2, b"control-output" * 4096)
    if operation == "start":
        print("before-hang", flush=True)
        if "closed" in scenario:
            os.close(1)
            os.close(2)
    if "descendant" in scenario:
        if os.fork() != 0:
            sys.exit(0)
        with trace.open("a") as stream:
            print(os.getpid(), os.getpgrp(), file=stream)
    time.sleep(120)
elif operation == "version":
    print("27.0.0")
elif operation == "image_inspect":
    print(json.dumps([{"Id": "sha256:fixture", "Config": {"Labels": {}}}]))
elif operation == "create":
    print("fixture-container")
elif operation == "start":
    if "output" in scenario:
        while True:
            os.write(1, b"x" * 4096)
            os.write(2, b"e" * 4096)
    print("public-output", flush=True)
elif operation == "kill" and "kill_error" in scenario:
    sys.exit(1)
elif operation == "inspect":
    state = {"ExitCode": 137 if "oom" in scenario else 0, "OOMKilled": "oom" in scenario, "Running": False}
    if "inspect_missing_exit" in scenario:
        del state["ExitCode"]
    if "inspect_missing_config" in scenario:
        print(json.dumps([{"State": state}]))
        sys.exit(0)
    print(json.dumps([{"State": state, "Config": {"User": "65532:65532"},
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "Memory": 134217728,
        "MemorySwap": 134217728, "NanoCpus": 1000000000, "PidsLimit": 64,
        "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges"]}, "Mounts": []}]))
elif operation == "rm" and "rm_error" in scenario:
    sys.exit(1)
''')
            docker.chmod(0o755)
            source = '''import json
from dataclasses import asdict
from llm4om.contracts import RunError
from llm4om.executors import run_container
try:
    result = run_container(["python", "-c", "pass"], {}, {
        "network": False, "cpu_limit": 1, "memory_limit_mb": 128,
        "wall_time_s": 0.3, "output_limit_bytes": 8192})
    data = asdict(result)
    data["stdout"] = result.stdout.decode(errors="replace")
    data["stderr"] = result.stderr.decode(errors="replace")
    print(json.dumps(data))
except RunError as error:
    print(json.dumps({"code": error.code, "stage": error.stage, "details": error.details}))
'''
            started = monotonic()
            process = subprocess.Popen([sys.executable, "-c", source], start_new_session=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, "PATH": directory + os.pathsep + os.defpath,
                     "LLM4OM_CONTROL_SCENARIO": scenario})
            try:
                try:
                    out, err = process.communicate(timeout=12)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate(timeout=2)
                    self.fail(f"Executor did not return within 12 seconds: {scenario}")
                live_groups = []
                for record in (Path(directory) / "pids").read_text().splitlines():
                    pid, group = map(int, record.split())
                    stat = Path(f"/proc/{pid}/stat")
                    try:
                        if stat.read_text().rsplit(") ", 1)[1].split()[0] != "Z":
                            live_groups.append(group)
                    except FileNotFoundError:
                        pass
                self.assertEqual(live_groups, [], f"Docker CLI processes leaked: {scenario}")
                public_root = Path(directory) / "public-root"
                if public_root.exists():
                    self.assertFalse(Path(public_root.read_text()).exists(), "Public staging directory leaked")
            finally:
                trace = Path(directory) / "pids"
                if trace.exists():
                    for record in trace.read_text().splitlines():
                        pid, group = map(int, record.split())
                        try:
                            os.killpg(group, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
            self.assertEqual(process.returncode, 0, err.decode(errors="replace"))
            self.assertLess(monotonic() - started, 12)
            return json.loads(out)

    def test_attach_and_kill_hangs_preserve_timeout_and_cleanup_evidence(self) -> None:
        result = self.run_hanging_docker("start+kill+rm")
        self.assertEqual(result["status"], "timeout")
        self.assertIn("before-hang", result["stdout"])
        self.assertTrue(any("kill" in item for item in result["diagnostics"]))
        self.assertTrue(any("remove" in item for item in result["diagnostics"]))

    def test_create_and_cleanup_hangs_preserve_the_primary_error(self) -> None:
        result = self.run_hanging_docker("create+rm")
        self.assertEqual(result["code"], "executor_error")
        self.assertEqual(result["stage"], "execution")
        self.assertEqual(result["details"]["status"], "failed")
        self.assertTrue(result["details"]["container_name"].startswith("llm4om-"))
        self.assertTrue(any("create" in item for item in result["details"]["diagnostics"]))
        self.assertTrue(any("remove" in item for item in result["details"]["diagnostics"]))

    def test_daemon_preflight_hangs_are_bounded_admission_errors(self) -> None:
        for scenario in ("version", "image_inspect", "version+descendant", "version+flood"):
            with self.subTest(scenario=scenario):
                result = self.run_hanging_docker(scenario)
                self.assertEqual(result["code"], "executor_unavailable")
                self.assertEqual(result["stage"], "admission")
                self.assertTrue(result["details"]["diagnostics"])

    def test_failed_kill_and_remove_do_not_mask_a_hanging_workers_timeout(self) -> None:
        result = self.run_hanging_docker("start+kill_error+rm_error")
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(any("kill:" in item and "code 1" in item for item in result["diagnostics"]))
        self.assertTrue(any("remove:" in item and "code 1" in item for item in result["diagnostics"]))

    def test_attach_hangs_after_pipe_closure_or_a_descendant_holds_the_pipes(self) -> None:
        for scenario in ("start+closed+kill", "start+descendant+kill"):
            with self.subTest(scenario=scenario):
                result = self.run_hanging_docker(scenario)
                self.assertEqual(result["status"], "timeout")
                self.assertIn("before-hang", result["stdout"])

    def test_inspect_hang_does_not_erase_a_timeout_or_captured_output(self) -> None:
        result = self.run_hanging_docker("start+kill+inspect+rm")
        self.assertEqual(result["status"], "timeout")
        self.assertIsNone(result["exit_code"])
        self.assertIn("before-hang", result["stdout"])
        self.assertTrue(any("inspect" in item for item in result["diagnostics"]))
        self.assertTrue(any("remove" in item for item in result["diagnostics"]))
        self.assertNotIn("network", result["restrictions"])

    def test_output_keeps_draining_with_bounded_capture_while_kill_hangs(self) -> None:
        result = self.run_hanging_docker("output+kill+rm")
        self.assertEqual(result["status"], "output_limit")
        self.assertTrue(result["output_truncated"])
        self.assertEqual(len(result["stdout"]) + len(result["stderr"]), 8192)
        self.assertTrue(any("kill" in item for item in result["diagnostics"]))
        self.assertTrue(any("remove" in item for item in result["diagnostics"]))

    def test_first_resource_limit_is_preserved_with_later_oom_evidence(self) -> None:
        result = self.run_hanging_docker("output+oom+kill+rm")
        self.assertEqual(result["status"], "output_limit")
        self.assertTrue(result["oom_killed"])
        self.assertEqual(result["exit_code"], 137)
        self.assertTrue(result["output_truncated"])

    def test_oom_evidence_is_retained_when_cleanup_hangs(self) -> None:
        result = self.run_hanging_docker("oom+rm")
        self.assertEqual(result["status"], "oom")
        self.assertTrue(result["oom_killed"])
        self.assertEqual(result["exit_code"], 137)
        self.assertTrue(any("remove" in item for item in result["diagnostics"]))

    def test_oom_exit_evidence_survives_incomplete_inspect_and_cleanup_hang(self) -> None:
        result = self.run_hanging_docker("oom+inspect_missing_config+rm")
        self.assertEqual(result["status"], "oom")
        self.assertTrue(result["oom_killed"])
        self.assertEqual(result["exit_code"], 137)
        self.assertTrue(any("inspect" in item for item in result["diagnostics"]))
        self.assertTrue(any("remove" in item for item in result["diagnostics"]))

    def test_known_oom_is_preserved_without_an_exit_code_during_cleanup_hang(self) -> None:
        result = self.run_hanging_docker("oom+inspect_missing_exit+rm")
        self.assertEqual(result["status"], "oom")
        self.assertTrue(result["oom_killed"])
        self.assertIsNone(result["exit_code"])
        self.assertTrue(any("inspect" in item for item in result["diagnostics"]))

    def test_successful_worker_cannot_hide_a_cleanup_hang(self) -> None:
        result = self.run_hanging_docker("rm")
        self.assertEqual(result["code"], "executor_error")
        self.assertEqual(result["details"]["stdout"], "public-output\n")
        self.assertEqual(result["details"]["exit_code"], 0)
        self.assertTrue(any("remove" in item for item in result["details"]["diagnostics"]))

    def test_inspect_and_remove_hangs_preserve_collection_error_and_output(self) -> None:
        result = self.run_hanging_docker("inspect+rm")
        self.assertEqual(result["code"], "executor_error")
        self.assertEqual(result["details"]["status"], "failed")
        self.assertEqual(result["details"]["stdout"], "public-output\n")
        self.assertEqual(result["details"]["container_id"], "fixture-container")
        self.assertTrue(any("inspect" in item for item in result["details"]["diagnostics"]))
        self.assertTrue(any("remove" in item for item in result["details"]["diagnostics"]))

    def test_script_executes_as_a_restricted_container_process(self) -> None:
        from llm4om.executors import run_container
        execution = run_container(["python", "-I", "/input/probe.py"], {
            "probe.py": b"import os\nprint(os.getuid())\n"}, {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10},
            image=self.image)
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.exit_code, 0)
        self.assertEqual(execution.stdout.strip(), b"65532")
        self.assertEqual(execution.restrictions["network"], "none")
        self.assertTrue(execution.restrictions["read_only"])
        self.assertEqual(execution.restrictions["user"], "65532:65532")
        self.assertEqual(execution.restrictions["memory_bytes"], 128 * 1024 * 1024)
        self.assertEqual(execution.restrictions["memory_swap_bytes"], 128 * 1024 * 1024)
        self.assertEqual(execution.restrictions["nano_cpus"], 1000000000)
        self.assertEqual(execution.restrictions["pids_limit"], 64)
        self.assertEqual(execution.restrictions["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges", execution.restrictions["security_options"])
        self.assertTrue(all(not mount["rw"] for mount in execution.restrictions["mounts"]
                            if mount["destination"] == "/input"))
        self.assertEqual(execution.diagnostics, ())

    def test_worker_image_runs_without_mounting_host_code_or_environment(self) -> None:
        from llm4om.executors import run_container
        execution = run_container(["python", "-I", "-m", "llm4om.worker", "--runtime"], {}, {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 256, "wall_time_s": 10},
            image="llm4om-worker:0.3.0")
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.exit_code, 0)
        self.assertEqual(json.loads(execution.stdout)["schema_version"], "0.2.0")
        self.assertTrue(all(mount["destination"] in ("/input", "/tmp")
                            for mount in execution.restrictions["mounts"]))

    def test_nested_public_inputs_are_readable_with_a_private_host_umask(self) -> None:
        from llm4om.executors import run_container
        previous = os.umask(0o077)
        try:
            execution = run_container(["python", "-I", "-c",
                "from pathlib import Path; print(Path('/input/data/nested/public.csv').read_text())"],
                {"data/nested/public.csv": b"public bytes"}, {
                    "network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10}, image=self.image)
        finally:
            os.umask(previous)
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.stdout.strip(), b"public bytes")

    def test_timeout_kills_the_container_and_the_next_task_can_run(self) -> None:
        from llm4om.executors import run_container
        limits = {"network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 0.4}
        execution = run_container(["python", "-I", "/input/probe.py"], {"probe.py": b"while True: pass\n"}, limits, image=self.image)
        self.assertEqual(execution.status, "timeout")
        self.assertLess(execution.wall_time_s, 5)
        result = subprocess.run(["docker", "inspect", execution.container_id], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"no such object", result.stderr.lower())
        limits["wall_time_s"] = 10
        execution = run_container(["python", "-c", "print('next')"], {}, limits, image=self.image)
        self.assertEqual(execution.stdout.strip(), b"next")

    def test_output_limit_is_enforced_while_the_worker_is_running(self) -> None:
        from llm4om.executors import run_container
        execution = run_container(["python", "-u", "-c", "while True: print('x'*4096)"], {}, {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10,
            "output_limit_bytes": 8192}, image=self.image)
        self.assertEqual(execution.status, "output_limit")
        self.assertTrue(execution.output_truncated)
        self.assertLessEqual(len(execution.stdout) + len(execution.stderr), 8192)

    def test_stderr_output_limit_is_enforced_while_the_worker_is_running(self) -> None:
        from llm4om.executors import run_container
        execution = run_container(["python", "-I", "-c",
            "import os\nwhile True: os.write(2, b'e'*4096)"], {}, {
                "network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10,
                "output_limit_bytes": 8192}, image=self.image)
        self.assertEqual(execution.status, "output_limit")
        self.assertTrue(execution.output_truncated)
        self.assertEqual(execution.stdout, b"")
        self.assertEqual(execution.stderr, b"e" * 8192)

    def test_network_host_environment_and_file_writes_are_denied(self) -> None:
        from llm4om.executors import run_container
        source = b'''import os, json, socket
from pathlib import Path
checks = {"secret_absent": "LLM4OM_LLM_API_KEY" not in os.environ,
          "oracle_absent": not Path("/input/oracle.json").exists(),
          "docker_socket_absent": not Path("/var/run/docker.sock").exists()}
try:
    socket.create_connection(("1.1.1.1", 80), timeout=0.1)
    checks["network_blocked"] = False
except OSError:
    checks["network_blocked"] = True
for label, path in (("root_read_only", "/etc/escape"), ("input_read_only", "/input/public.csv")):
    try:
        Path(path).write_text("overwrite")
        checks[label] = False
    except OSError:
        checks[label] = True
print(json.dumps(checks))
'''
        with patch.dict(os.environ, {"LLM4OM_LLM_API_KEY": "PRIVATE-CONTAINER-ENV-SENTINEL"}):
            execution = run_container(["python", "-I", "/input/probe.py"], {"probe.py": source, "public.csv": b"public\n"}, {
                "network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10}, image=self.image)
        self.assertEqual(execution.exit_code, 0)
        self.assertTrue(all(json.loads(execution.stdout).values()))
        self.assertNotIn(b"PRIVATE-CONTAINER-ENV-SENTINEL", execution.stdout + execution.stderr)

    def test_memory_limit_reports_real_oom(self) -> None:
        from llm4om.executors import run_container
        execution = run_container(["python", "-c", "data=[]\nwhile True: data.append(bytearray(1024*1024))"], {}, {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 64, "wall_time_s": 10}, image=self.image)
        self.assertEqual(execution.status, "oom")
        self.assertTrue(execution.oom_killed)
        self.assertEqual(execution.exit_code, 137)

    def test_process_limit_denies_forks_and_reaps_the_child_processes(self) -> None:
        from llm4om.executors import run_container
        source = b'''import json, os, signal, time
children = []
failure_errno = None
try:
    for _ in range(20):
        try:
            child = os.fork()
        except OSError as error:
            failure_errno = error.errno
            break
        if child == 0:
            time.sleep(60)
            os._exit(0)
        children.append(child)
    print(json.dumps({"spawned": len(children), "errno": failure_errno}), flush=True)
finally:
    for child in children:
        os.kill(child, signal.SIGKILL)
        os.waitpid(child, 0)
'''
        execution = run_container(["python", "-I", "/input/probe.py"], {"probe.py": source}, {
            "network": False, "cpu_limit": 1, "memory_limit_mb": 128, "wall_time_s": 10,
            "pids_limit": 12}, image=self.image)
        self.assertEqual(execution.status, "completed")
        self.assertEqual(execution.exit_code, 0)
        report = json.loads(execution.stdout)
        self.assertEqual(report["errno"], 11)
        self.assertGreater(report["spawned"], 0)
        self.assertLess(report["spawned"], 12)
        self.assertEqual(execution.restrictions["pids_limit"], 12)
        result = subprocess.run(["docker", "inspect", execution.container_id], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"no such object", result.stderr.lower())


if __name__ == "__main__":
    unittest.main()
