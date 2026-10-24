"""The command line."""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from llm4om.cli import _print_step, main


def test_cli_reports_failed_solve_without_a_status(capsys: Any) -> None:
    _print_step({"type": "solve", "title": "final solve", "running": False, "failed": True})
    assert "final solve" in capsys.readouterr().err


def test_cli_reports_a_missing_input_file_without_a_traceback(tmp_path: Path, capsys: Any) -> None:
    missing = tmp_path / "missing.txt"
    assert main(["run", "--file", str(missing), "--workspace", str(tmp_path)]) == 2
    assert capsys.readouterr().err.strip() == f"Error: Cannot read {missing}: No such file or directory."


def test_cli_solves_code_without_model_settings(tmp_path: Path, capsys: Any) -> None:
    from tests.conftest import PRODUCTION_CODE

    code = tmp_path / "model.py"
    code.write_text(PRODUCTION_CODE)
    assert main(["solve", "--code", str(code), "--language", "pyomo", "--sandbox", "local"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "optimal" and result["objective"] == 13


def test_host_cli_can_exit_and_resume_in_new_processes(tmp_path: Path) -> None:
    from tests.conftest import ACCEPT_REVIEW, PRODUCTION_PROBLEM, TWO_PART_REPLY

    environment = {key: value for key, value in os.environ.items() if not key.startswith("LLM4OM_LLM_")}
    environment["LANGSMITH_TRACING"] = "false"

    def invoke(*args: str) -> dict:
        completed = subprocess.run([sys.executable, "-m", "llm4om.cli", *args], cwd=tmp_path,
                                   env=environment, capture_output=True, text=True, timeout=30)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    directory = tmp_path / "session"
    result = invoke("host", "start", "--session", str(directory), "--problem", PRODUCTION_PROBLEM,
                    "--method", "feedback_repair", "--sandbox", "local")
    assert invoke("host", "status", "--session", str(directory))["pending"] == result["pending"]
    for reply in (TWO_PART_REPLY, ACCEPT_REVIEW):
        responses = tmp_path / "responses.json"
        responses.write_text(json.dumps({result["pending"][0]["id"]: {"content": reply}}))
        result = invoke("host", "resume", "--session", str(directory), "--responses", str(responses))
    assert result["status"] == "completed" and result["solve"]["objective"] == 13
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 1


def test_cli_discovers_methods_and_prints_native_contracts(capsys: Any) -> None:
    assert main(["methods"]) == 0
    catalog = json.loads(capsys.readouterr().out)
    assert len(catalog) == 13 and all(len(item["languages"]) == 9 for item in catalog)
    assert main(["target", "--language", "ortools", "--solver", "CP_SAT"]) == 0
    prompt = capsys.readouterr().out
    assert "build_model(data)" in prompt and "CpModel" in prompt


def test_cli_rejects_invalid_host_json_without_a_traceback(tmp_path: Path, capsys: Any) -> None:
    path = tmp_path / "response.json"
    path.write_text("null")
    assert main(["host", "resume", "--session", str(tmp_path), "--responses", str(path)]) == 2
    assert "JSON object" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="This regression sends a POSIX SIGINT to the CLI")
def test_host_cli_interrupts_and_resumes_an_unfinished_solve(tmp_path: Path) -> None:
    from tests.conftest import PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY

    def invoke(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-m", "llm4om.cli", *args], cwd=tmp_path,
                              capture_output=True, text=True, timeout=30)

    directory, marker = tmp_path / "session", tmp_path / "solver-started"
    first = invoke("host", "start", "--session", str(directory), "--problem", PRODUCTION_PROBLEM, "--sandbox", "local")
    state = json.loads(first.stdout)
    slow_code = PRODUCTION_CODE.replace("    m = pyo.ConcreteModel()", (
        f"    from pathlib import Path\n    import time\n    marker = Path({str(marker)!r})\n"
        "    if not marker.exists():\n        marker.write_text('started')\n        time.sleep(30)\n"
        "    m = pyo.ConcreteModel()"))
    response = tmp_path / "responses.json"
    response.write_text(json.dumps({state["pending"][0]["id"]: {"content": TWO_PART_REPLY.replace(PRODUCTION_CODE, slow_code)}}))
    with subprocess.Popen([sys.executable, "-m", "llm4om.cli", "host", "resume", "--session", str(directory),
                           "--responses", str(response)], cwd=tmp_path, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        try:
            deadline = time.monotonic() + 15
            while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert marker.exists(), "The real worker did not start"
            process.send_signal(signal.SIGINT)
            _, stderr = process.communicate(timeout=15)
            assert process.returncode == 130 and "Traceback" not in stderr, stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()
    interrupted = invoke("host", "status", "--session", str(directory))
    state = json.loads(interrupted.stdout)
    assert state["status"] == "interrupted" and not state["pending"], state
    response.write_text("{}")
    completed = invoke("host", "resume", "--session", str(directory), "--responses", str(response))
    assert completed.returncode == 0, completed.stderr
    state = json.loads(completed.stdout)
    assert state["status"] == "completed" and state["solve"]["objective"] == 13
    assert state["usage"]["llm_calls"] == state["usage"]["solves"] == 1
