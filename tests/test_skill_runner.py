import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from skills.llm4om.scripts import run as runner
from tests.conftest import PRODUCTION_PROBLEM, TWO_PART_REPLY


def test_worker_builds_only_when_missing(capsys):
    missing = subprocess.CompletedProcess([], 0, stdout="", stderr="")
    ready = subprocess.CompletedProcess([], 0, stdout="image-id\n", stderr="")
    with patch.object(subprocess, "run", side_effect=[missing, None, ready]) as command:
        runner.prepare_worker()
        runner.prepare_worker()
    lookup, build, retry = command.call_args_list
    assert lookup == retry
    assert lookup.args[0] == ["docker", "image", "ls", "--quiet", runner.WORKER_IMAGE]
    assert build.args[0] == [runner.sys.executable, "-I", "-m", "llm4om.cli", "build-worker"]
    assert build.kwargs == {"check": True, "stdout": runner.sys.stderr}
    assert capsys.readouterr().out == ""


def test_unreachable_docker_does_not_build_or_create_a_session(tmp_path):
    problem = tmp_path / "problem.md"
    problem.write_text(PRODUCTION_PROBLEM, encoding="utf-8")
    session = tmp_path / "plan"
    unavailable = subprocess.CompletedProcess([], 1, stdout="", stderr="daemon is unavailable")
    with patch.object(subprocess, "run", return_value=unavailable) as command:
        with pytest.raises(RuntimeError, match="daemon is unavailable"):
            runner.main(["start", "--file", str(problem), "--session", str(session)])
    command.assert_called_once()
    assert not session.exists()


def test_waiting_for_review_only_emits_the_pending_work(tmp_path):
    pending = [{"id": "review", "messages": [{"role": "user", "content": "Review the candidate"}]}]
    result = {"session": str(tmp_path), "pending": pending, "status": "waiting", "failure": None,
              "solve": {"status": "feasible", "objective": 2, "variables": {"x": 2}}}
    assert runner.turn_output(result) == {"session": str(tmp_path), "result_file": str(tmp_path / "result.json"),
                                          "status": "waiting", "pending": pending}


def test_large_results_keep_the_full_artifact_address(tmp_path):
    variables = {f"x[{i}]": i for i in range(40)}
    result = {"session": str(tmp_path), "pending": [], "failure": None, "status": "completed",
              "solve": {"status": "feasible", "objective": 0, "variables": variables,
                        "pareto": {"solutions": [], "total": 3}}}
    reply = runner.turn_output(result)
    assert reply == {"session": str(tmp_path), "result_file": str(tmp_path / "result.json"), "status": "completed",
                     "solve": {"status": "feasible", "objective": 0, "variable_count": 40, "pareto_count": 3}}
    assert result["solve"]["variables"] == variables


def test_skill_keeps_docker_only_tools_and_requires_explicit_session_files(capsys):
    for args in (["backends", "--sandbox", "local"], ["run", "--problem", "test"],
                 ["start", "--problem", "test", "--session", "plan"], ["start", "--file", "problem.md"]):
        with pytest.raises(SystemExit) as error:
            runner.main(args)
        assert error.value.code == 2
    assert runner.main(["methods"]) == 0
    assert any(method["id"] == "direct" for method in json.loads(capsys.readouterr().out))


@pytest.mark.docker
@pytest.mark.skipif(os.environ.get("LLM4OM_TEST_DOCKER") != "1", reason="requires the current Docker worker")
def test_skill_runs_a_model_and_reopens_the_result(tmp_path, capsys):
    problem = tmp_path / "problem.md"
    problem.write_text(PRODUCTION_PROBLEM, encoding="utf-8")
    session_args = ["--session", str(tmp_path / "saved plan")]
    assert runner.main(["start", "--file", str(problem), "--solver", "highs", *session_args]) == 0
    first = json.loads(capsys.readouterr().out)
    with patch.object(runner, "prepare_worker", side_effect=AssertionError("status must only read")):
        assert runner.main(["status", *session_args]) == 0
    assert json.loads(capsys.readouterr().out) == first
    responses = tmp_path / "answers.json"
    answer = {first["pending"][0]["id"]: {"content": TWO_PART_REPLY}}
    responses.write_text(json.dumps(answer), encoding="utf-8")
    assert runner.main(["resume", *session_args, "--responses", str(responses)]) == 0
    final = json.loads(capsys.readouterr().out)
    assert final["status"] == "completed" and final["solve"]["status"] == "optimal"
    assert final["solve"]["objective"] == 13
    full = json.loads(Path(final["result_file"]).read_text(encoding="utf-8"))
    assert full["steps"] and full["solve"]["variables"] == final["solve"]["variables"]
