"""Host-owned modeling across separate CLI invocations, without a platform model or server."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage, convert_to_messages

from llm4om.host import resume, start, status
from llm4om.languages import LANGUAGES
from llm4om.methods import methods
from tests.conftest import ACCEPT_REVIEW, PRODUCTION_CODE, PRODUCTION_PROBLEM, TWO_PART_REPLY
from tests.test_method_libraries import method_script
from tests.test_methods import PASS_FORMULATION, autoformulation_script, by_role, trival_script


def drive_host(directory: Path, script: Any, *, method: str = "direct", language: str = "pyomo",
               sandbox: str = "local", **kwargs: Any) -> dict[str, Any]:
    result = asyncio.run(start(directory, PRODUCTION_PROBLEM, method=method, language=language, sandbox=sandbox, **kwargs))
    for _ in range(150):
        if result["status"] != "waiting":
            return result
        responses = {}
        for request in result["pending"]:
            answer = script(request["role"], convert_to_messages(request["messages"]),
                            [tool["function"]["name"] for tool in request["tools"]])
            responses[request["id"]] = {"content": answer.content, "tool_calls": answer.tool_calls} if isinstance(
                answer, AIMessage) else {"content": answer}
        result = asyncio.run(resume(directory, responses))
    pytest.fail("The method did not finish within its bounded test trajectory")


def test_host_repairs_with_real_solver_feedback_across_restarts(tmp_path: Path, monkeypatch: Any) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Host modeling must never resolve a platform LLM")

    monkeypatch.setattr("llm4om.llm.LLMSettings.validate", forbidden)
    monkeypatch.setattr("llm4om.llm_presets.LLMPresetStore.find", forbidden)
    directory = tmp_path / "session"
    result = asyncio.run(start(directory, PRODUCTION_PROBLEM, method="feedback_repair", sandbox="local"))
    assert result["status"] == "waiting"
    assert result["pending"][0]["role"] == "generate"
    assert asyncio.run(status(directory))["pending"] == result["pending"]

    def answer(text: str) -> dict[str, Any]:
        return asyncio.run(resume(directory, {result["pending"][0]["id"]: {"content": text}}))

    result = answer(TWO_PART_REPLY.replace("return m", "return m.missing"))
    assert result["pending"][0]["role"] == "repair"
    assert "missing" in str(result["pending"][0]["messages"])
    result = answer(TWO_PART_REPLY)
    assert result["pending"][0]["role"] == "review"
    result = answer(ACCEPT_REVIEW)
    assert result["status"] == "completed"
    assert result["solve"]["objective"] == 13
    assert result["code"].strip() == PRODUCTION_CODE.strip()
    assert result["usage"]["llm_calls"] == 3
    assert result["usage"]["solves"] == 2
    assert result["usage"]["input_tokens"] is None
    assert asyncio.run(status(directory))["solve"] == result["solve"]
    assert (directory / "model.py").read_text().strip() == PRODUCTION_CODE.strip()


@pytest.mark.parametrize("method", list(methods()))
@pytest.mark.parametrize("language", list(LANGUAGES))
def test_host_runs_every_method_with_every_library(tmp_path: Path, preset: Any, method: str, language: str) -> None:
    preset("AUTOFORMULATION", n_used_gpt=1, n_top=1, n_reward=1, total_rollouts=1)
    result = drive_host(tmp_path / "session", method_script(method, language), method=method, language=language)
    assert result["status"] == "completed", result.get("failure")
    assert result["solve"]["objective"] == pytest.approx(13), result["solve"]
    assert result["formulation"] and result["code"]
    assert {"llm", "artifact", "solve"} <= {step["type"] for step in result["steps"]}
    assert all(not step.get("running") for step in result["steps"])
    assert result["usage"]["solves"] == 1


def test_host_preserves_parallel_search_voting_and_does_not_repeat_solves(tmp_path: Path, preset: Any) -> None:
    preset("AUTOFORMULATION", n_used_gpt=2, n_top=2, n_reward=1, total_rollouts=2)
    calls: list[tuple[str, str]] = []
    result = drive_host(tmp_path / "session", autoformulation_script("pyo.NonNegativeIntegers", calls),
                        method="autoformulation")
    assert result["status"] == "completed", result["failure"]
    assert result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 2
    assert [role for role, _ in calls].count("compare") == 10
    assert result["usage"]["llm_calls"] == len(calls) == 29
    assert sorted(step["objective"] for step in result["steps"] if step["type"] == "solve") == [13, 16]


def test_host_rejects_invalid_answers_without_consuming_the_pending_request(tmp_path: Path) -> None:
    directory = tmp_path / "session"
    before = asyncio.run(start(directory, PRODUCTION_PROBLEM, sandbox="local"))
    for response in ({"wrong-id": {"content": TWO_PART_REPLY}}, {}, {before["pending"][0]["id"]: {"content": 3}}):
        with pytest.raises(ValueError):
            asyncio.run(resume(directory, response))
        assert asyncio.run(status(directory))["pending"] == before["pending"]
    final = asyncio.run(resume(directory, {before["pending"][0]["id"]: {"content": TWO_PART_REPLY}}))
    assert final["solve"]["objective"] == 13
    with pytest.raises(ValueError, match="ended"):
        asyncio.run(resume(directory, {}))


def test_host_caps_parallel_requests_before_returning_work_to_the_agent(tmp_path: Path) -> None:
    result = asyncio.run(start(tmp_path / "session", PRODUCTION_PROBLEM, method="autoformulation", sandbox="local", max_calls=2))
    assert result["status"] == "failed" and "limit" in result["failure"]
    assert result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 0


def test_host_keeps_attachments_in_the_session_and_preserves_bind_data_offloading(tmp_path: Path) -> None:
    numbers = [0] * 21000 + [876543]
    code = PRODUCTION_CODE.replace('3 * m.x["A"]', 'max(__import__("json").loads(data["profit.json"])) * m.x["A"]')

    def script(role: str, messages: list, tools: list) -> str:
        prompt = "\n".join(message.text for message in messages)
        assert "876543" not in prompt and "truncated" not in prompt
        return TWO_PART_REPLY.replace(PRODUCTION_CODE, code)

    result = drive_host(tmp_path / "session", script, method="bind", data={"profit.json": json.dumps(numbers)})
    assert result["solve"]["objective"] == 4 * 876543
    assert "876543" not in json.dumps(result["spec"])


def test_host_trival_backtracks_from_code_validation_to_formulation(tmp_path: Path) -> None:
    script = trival_script([
        {"code_validation_passed": False, "code_validation_feedback": "Recheck the formulation.",
         "error_attribution": "formulation"},
        {"code_validation_passed": True, "code_validation_feedback": "Matches."},
    ], [dict(PASS_FORMULATION), dict(PASS_FORMULATION)])
    result = drive_host(tmp_path / "session", script, method="trival")
    assert result["status"] == "completed", result["failure"]
    assert "revised" in result["formulation"]
    assert result["solve"]["objective"] == 13 and result["usage"]["solves"] == 2
    titles = [step["title"] for step in result["steps"] if step["type"] == "llm"]
    assert titles.count("trival.formulation_validator") == 2
    assert titles.count("trival.code_validator") == 2


def test_host_resumes_a_legacy_nested_trival_checkpoint_to_completion(tmp_path: Path, monkeypatch: Any) -> None:
    import sqlite3
    from dataclasses import replace

    from langchain_core.messages import HumanMessage
    from langgraph.graph import END, START, StateGraph
    from langgraph.runtime import Runtime

    from llm4om.methods.trival import TRIVAL
    from llm4om.methods.trival.graph import State
    from llm4om.runtime import Context

    def build_legacy_nested_graph() -> Any:
        async def extractor(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
            reply = await runtime.context.llm("trival.semantic_fact_extractor").ainvoke([HumanMessage(state["problem"])])
            return {"semantic_facts": reply.text}

        stage = StateGraph(State, context_schema=Context)
        stage.add_node("semantic_fact_extractor", extractor)
        stage.add_edge(START, "semantic_fact_extractor")
        stage.add_edge("semantic_fact_extractor", END)

        outer = StateGraph(State, context_schema=Context)
        outer.add_node("semantic_validation", stage.compile(name="semantic_validation"))
        outer.add_edge(START, "semantic_validation")
        outer.add_edge("semantic_validation", END)
        return outer.compile(name="trival")

    directory = tmp_path / "legacy-trival"
    legacy_trival = replace(TRIVAL, graph=build_legacy_nested_graph)
    real_methods = methods()
    monkeypatch.setattr("llm4om.host.session.methods", lambda: {**real_methods, "trival": legacy_trival})
    initial = asyncio.run(start(directory, PRODUCTION_PROBLEM, method="trival", sandbox="local"))
    assert initial["status"] == "waiting" and initial["pending"][0]["role"] == "trival.semantic_fact_extractor"
    with sqlite3.connect(directory / "checkpoints.sqlite") as conn:
        assert conn.execute("SELECT 1 FROM checkpoints WHERE checkpoint_ns LIKE 'method:%|%'").fetchone() is not None

    # Restore the real flattened TriVAL graph and verify an invalid answer leaves the legacy checkpoint intact.
    monkeypatch.setattr("llm4om.host.session.methods", methods)
    with pytest.raises(ValueError):
        asyncio.run(resume(directory, {"wrong": {"content": "bad"}}))
    assert asyncio.run(status(directory))["pending"][0]["id"] == initial["pending"][0]["id"]

    script = trival_script(
        [{"code_validation_passed": False, "code_validation_feedback": "re-verify", "error_attribution": "code"},
         {"code_validation_passed": True, "code_validation_feedback": "Matches."}],
        [dict(PASS_FORMULATION)],
    )
    first_req = initial["pending"][0]
    first_ans = script(first_req["role"], convert_to_messages(first_req["messages"]),
                       [t["function"]["name"] for t in first_req["tools"]])
    first_payload = {first_req["id"]: {"content": first_ans.content, "tool_calls": first_ans.tool_calls}}

    # 1) Fault before COMMIT leaves the original checkpoint intact and retryable.
    real_write = __import__("llm4om.host.session", fromlist=["_write_outputs"])._write_outputs
    monkeypatch.setattr("llm4om.host.session._write_outputs", lambda *_: (_ for _ in ()).throw(RuntimeError("crash before commit")))
    with pytest.raises(RuntimeError, match="crash before commit"):
        asyncio.run(resume(directory, first_payload))
    monkeypatch.setattr("llm4om.host.session._write_outputs", real_write)
    assert asyncio.run(status(directory))["pending"][0]["id"] == first_req["id"]

    # 2) Fault mid-cutover (after checkpoints.sqlite replaced, before records.sqlite replaced) rolls forward on status().
    real_replace = os.replace

    def fail_on_records_replace(src: Any, dst: Any) -> None:
        if Path(dst) == directory / "records.sqlite":
            raise OSError("disk glitch between checkpoints and records")
        real_replace(src, dst)

    monkeypatch.setattr("llm4om.host.records.os.replace", fail_on_records_replace)
    with pytest.raises(OSError, match="disk glitch"):
        asyncio.run(resume(directory, first_payload))
    assert not (directory / ".migrating" / "checkpoints.sqlite").exists()
    assert (directory / ".migrating" / "records.sqlite").is_file()
    assert (directory / ".migrating" / "COMMIT").is_file()
    monkeypatch.setattr("llm4om.host.records.os.replace", real_replace)
    rolled_forward = asyncio.run(status(directory))
    assert not (directory / ".migrating").exists()
    assert rolled_forward["status"] == "waiting" and rolled_forward["pending"][0]["id"] != first_req["id"]
    assert json.loads((directory / "result.json").read_text())["pending"] == rolled_forward["pending"]
    assert rolled_forward["usage"]["llm_calls"] == 2

    result = rolled_forward
    for _ in range(45):
        if result["status"] != "waiting":
            break
        responses = {}
        for req in result["pending"]:
            ans = script(req["role"], convert_to_messages(req["messages"]), [t["function"]["name"] for t in req["tools"]])
            responses[req["id"]] = {"content": ans.content, "tool_calls": ans.tool_calls} if isinstance(ans, AIMessage) else {"content": ans}
        result = asyncio.run(resume(directory, responses))
    assert result["status"] == "completed", result.get("failure")
    assert result["solve"]["objective"] == 13

    # 3) Legacy session with partial/extra validator calls + two identical-code solves preserves FIFO order & durations.
    prior_llm = [
        ("trival.semantic_fact_extractor", {"content": "", "tool_calls": [{"name": "write_semantic_facts", "id": "c1", "args": {"semantic_facts": "- facts"}}]}),
        ("trival.semantic_fact_extractor", {"content": "Done.", "tool_calls": []}),
        ("trival.semantic_validator", {"content": "", "tool_calls": [
            {"name": "SemanticValidationOutput", "id": "c2", "args": {"facts_faithful": True, "ambiguities_relevant": True, "resolutions_consistent": True}},
            {"name": "SemanticValidationOutput", "id": "c2_partial", "args": {"feedback": "missing required booleans"}},
            {"name": "unknown_helper", "id": "c2b", "args": {}},
        ]}),
        ("trival.parameter_index_expert", {"content": "M1", "tool_calls": []}),
        ("trival.decision_variable_expert", {"content": "M2", "tool_calls": []}),
        ("trival.constraint_expert", {"content": "M3", "tool_calls": []}),
        ("trival.objective_expert", {"content": "M4", "tool_calls": []}),
        ("trival.formulation_selector", {"content": "", "tool_calls": [{"name": "select_formulation", "id": "c3", "args": {"expert_name": "constraint_expert"}}]}),
        ("trival.formulation_selector", {"content": "Done.", "tool_calls": []}),
        ("trival.formulation_validator", {"content": "", "tool_calls": [{"name": "FormulationValidationOutput", "id": "c4", "args": dict(PASS_FORMULATION)}]}),
        ("trival.code_agent", {"content": "", "tool_calls": [{"name": "write_code", "id": "c5", "args": {"code": PRODUCTION_CODE}}]}),
        ("trival.code_agent", {"content": "Done.", "tool_calls": []}),
        ("trival.code_validator", {"content": "", "tool_calls": [{"name": "CodeValidationOutput", "id": "c6", "args": {"code_validation_passed": False, "code_validation_feedback": "retry", "error_attribution": "code"}}]}),
        ("trival.code_agent", {"content": "", "tool_calls": [{"name": "write_code", "id": "c7", "args": {"code": PRODUCTION_CODE}}]}),
    ]
    final_ans = {"content": "", "tool_calls": [{"name": "CodeValidationOutput", "id": "c8", "args": {"code_validation_passed": True, "code_validation_feedback": "ok", "error_attribution": "code"}}]}

    def build_legacy_code_agent_pause() -> Any:
        async def agent_node(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
            reply = await runtime.context.llm("trival.code_agent").ainvoke([HumanMessage(state["problem"])])
            return {"code": reply.text}
        stage = StateGraph(State, context_schema=Context)
        stage.add_node("code_agent", agent_node)
        stage.add_edge(START, "code_agent")
        stage.add_edge("code_agent", END)
        outer = StateGraph(State, context_schema=Context)
        outer.add_node("code_validation", stage.compile(name="code_validation"))
        outer.add_edge(START, "code_validation")
        outer.add_edge("code_validation", END)
        return outer.compile(name="trival")

    dir_fifo = tmp_path / "legacy-fifo-solves"
    monkeypatch.setattr("llm4om.host.session.methods", lambda: {**real_methods, "trival": replace(TRIVAL, graph=build_legacy_code_agent_pause)})
    paused_fifo = asyncio.run(start(dir_fifo, PRODUCTION_PROBLEM, method="trival", sandbox="local"))
    monkeypatch.setattr("llm4om.host.session.methods", methods)
    with sqlite3.connect(dir_fifo / "records.sqlite", isolation_level=None) as conn:
        conn.execute("DELETE FROM host_operations")
        for idx, (role, reply) in enumerate(prior_llm):
            conn.execute("INSERT INTO host_operations VALUES (?, 'llm', ?, ?)",
                         (f"op-llm-{idx}", json.dumps({"role": role}), json.dumps(reply)))
        for idx, (obj, secs) in enumerate(((101.0, 0.2), (202.0, 0.7))):
            conn.execute(
                "INSERT INTO host_operations VALUES (?, 'solve', ?, ?)",
                (f"op-solve-{idx}", json.dumps({"code": PRODUCTION_CODE, "title": f"Solve {idx}"}),
                 json.dumps({"status": "optimal", "objective": obj, "variables": {"x[A]": 3.0, "x[B]": 2.0}})),
            )
            conn.execute(
                "INSERT INTO host_steps VALUES (?, ?)",
                (f"op-solve-{idx}", json.dumps({"id": f"op-solve-{idx}", "type": "solve", "title": f"Solve {idx}", "seconds": secs})),
            )
    waiting_validator = asyncio.run(resume(dir_fifo, {paused_fifo["pending"][0]["id"]: {"content": "Done."}}))
    assert waiting_validator["status"] == "waiting" and waiting_validator["pending"][0]["role"] == "trival.code_validator"
    assert "202" in str(waiting_validator["pending"][0]["messages"])
    done = asyncio.run(resume(dir_fifo, {waiting_validator["pending"][0]["id"]: final_ans}))
    assert done["status"] == "completed", done.get("failure")
    solve_steps = [step for step in done["steps"] if step["type"] == "solve"]
    assert [step["objective"] for step in solve_steps] == [101.0, 202.0]
    assert [step["seconds"] for step in solve_steps] == [0.2, 0.7]
    assert done["solve"]["objective"] == 202.0

    # 4) If an answer was saved in host_operations before the checkpoint committed, retry deduplicates by interrupt ID
    #    and prefers the already-saved answer without double-counting max_calls.
    dir_dedup = tmp_path / "legacy-dedup"
    monkeypatch.setattr("llm4om.host.session.methods", lambda: {**real_methods, "trival": legacy_trival})
    paused_dedup = asyncio.run(start(dir_dedup, PRODUCTION_PROBLEM, method="trival", sandbox="local", max_calls=2))
    monkeypatch.setattr("llm4om.host.session.methods", methods)
    pending_id = paused_dedup["pending"][0]["id"]
    saved_reply = {
        "content": "",
        "tool_calls": [{"name": "write_semantic_facts", "id": "saved_c1", "args": {"semantic_facts": "- saved facts"}}],
        "id": f"host_{pending_id}",
    }
    with sqlite3.connect(dir_dedup / "records.sqlite", isolation_level=None) as conn:
        conn.execute("UPDATE host_operations SET result = ?", (json.dumps(saved_reply),))
    resubmitted = {
        pending_id: {
            "content": "",
            "tool_calls": [{"name": "write_semantic_facts", "id": "other_c1", "args": {"semantic_facts": "- overwritten"}}],
        }
    }
    after_dedup = asyncio.run(resume(dir_dedup, resubmitted))
    assert after_dedup["status"] == "waiting" and after_dedup["usage"]["llm_calls"] == 2
    assert "saved_c1" in str(after_dedup["pending"][0]["messages"])
    assert "overwritten" not in str(after_dedup["pending"][0]["messages"])


def test_host_solve_budget_keeps_results_bound_to_the_code_actually_executed(tmp_path: Path) -> None:
    script = by_role({"generate": TWO_PART_REPLY.replace("return m", "return m.missing"),
                      "repair": TWO_PART_REPLY, "review": ACCEPT_REVIEW})
    result = drive_host(tmp_path / "session", script, method="feedback_repair", max_solves=1)
    assert result["status"] == "failed" and "limit" in result["failure"]
    assert result["code"].strip() == PRODUCTION_CODE.strip()
    assert result["solve"] is None and result["usage"]["solves"] == 1


@pytest.mark.parametrize("limit", [0, -1, float("nan"), float("inf")])
def test_host_rejects_invalid_limits_before_creating_a_session(tmp_path: Path, limit: float) -> None:
    directory = tmp_path / "session"
    with pytest.raises(ValueError, match="finite and positive"):
        asyncio.run(start(directory, PRODUCTION_PROBLEM, time_limit=limit))
    assert not directory.exists()


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get("LLM4OM_TEST_DOCKER"), reason="set LLM4OM_TEST_DOCKER=1")
@pytest.mark.parametrize("method", ["direct", "feedback_repair", "trival"])
def test_host_executes_the_existing_docker_worker(tmp_path: Path, method: str) -> None:
    result = drive_host(tmp_path / "session", method_script(method, "pyomo"), method=method, sandbox="docker")
    assert result["status"] == "completed", result["failure"]
    assert result["solve"]["objective"] == 13 and result["usage"]["solves"] == 1
