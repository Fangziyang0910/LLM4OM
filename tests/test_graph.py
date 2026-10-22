"""The platform graph: steps in the order they happen, limits and the run deadline."""

import asyncio
from typing import Any

from llm4om.graph import run
from llm4om.runtime import Limits
from tests.conftest import PRODUCTION_CODE, TWO_PART_REPLY

BROKEN_CODE = PRODUCTION_CODE.replace("return m", "return m.missing")


def test_a_node_update_is_recorded_before_the_next_node_starts(run_method: Any) -> None:
    broken = TWO_PART_REPLY.replace(PRODUCTION_CODE, BROKEN_CODE)
    replies = iter([broken, TWO_PART_REPLY])
    record = run_method("feedback_repair", lambda *_: next(replies))
    order = [(step["type"], step["title"]) for step in record["steps"]]
    assert order == [("llm", "generate"), ("artifact", "生成数学模型和代码"), ("solve", "求解"),
                     ("llm", "repair"), ("artifact", "按求解反馈修正"), ("solve", "求解（修正 1）"),
                     ("artifact", "选择最好的一次")]


def test_llm_call_limit_stops_the_run(run_method: Any) -> None:
    broken = TWO_PART_REPLY.replace(PRODUCTION_CODE, BROKEN_CODE)
    record = run_method("feedback_repair", lambda *_: broken, limits=Limits(max_llm_calls=2))
    assert "limit of 2 LLM calls" in record["failure"]
    assert record.get("code") is None and record["steps"][-1]["type"] == "error"


def test_deadline_includes_final_solving(make_resources: Any) -> None:
    class SlowSandbox:
        cancelled = False

        async def solve(self, *args: Any) -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                self.cancelled = True
                raise

    async def check() -> None:
        resources = make_resources(lambda *_: TWO_PART_REPLY, Limits(run_timeout=0.3))
        sandbox = resources.sandbox = SlowSandbox()
        result = await asyncio.wait_for(run("test", resources=resources), timeout=1)
        assert sandbox.cancelled and "time limit" in result["failure"]
        assert result["steps"][-1]["type"] == "error"
        assert not any(step.get("running") for step in result["steps"])

    asyncio.run(check())


def test_final_solve_limit_is_recorded(make_resources: Any) -> None:
    result = asyncio.run(run("test", resources=make_resources(lambda *_: TWO_PART_REPLY, Limits(max_solves=0))))
    assert "limit of 0 solves" in result["failure"]
    assert result["steps"][-1]["type"] == "error" and result["usage"]["solves"] == 0
