"""Arithmetic over supplied numbers or complete saved decision values."""

import ast
import json
import math
from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ToolCallRequest, wrap_tool_call
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.types import Command
from simpleeval import simple_eval

from .session import TOOL_INPUT_ERRORS, AgentContext, Conversation


def calculation(session: Conversation) -> AgentMiddleware:
    @tool(response_format="content_and_artifact")
    async def calculate(expression: str, runtime: ToolRuntime[AgentContext], query: str = "",
                             plan_id: str | None = None) -> tuple[str, dict[str, Any]]:
        """Evaluate arithmetic, totals, costs or ratios. A saved optimization plan is optional.

        With a saved plan, v maps exact variable names to actual values; values contains ALL values matching query
        (empty means all); objective is its actual objective. Without a plan, use ordinary numeric expressions.
        Each expression returns one number. Use arithmetic and sum, min, max, abs, round, len, sqrt.
        Examples: sum(values); v['x[A]'] * 2 + v['x[B]']; 8 - (2 * v['x[A]'] + v['x[B]']).
        Constants must come from the supplied problem or data. This evaluates expressions, not Python scripts.
        """
        parsed = ast.parse(expression, mode="eval")
        uses_plan = any(isinstance(node, ast.Name) and node.id in {"v", "values", "objective"}
                        for node in ast.walk(parsed))
        source = (session.selected_source(plan_id, runtime.state["current"])
                  if plan_id or ((uses_plan or query) and runtime.state["current"]) else None)
        values = await session.load(source) if source else {}
        solved = values.get("solve") or {}
        variables = solved.get("variables") or {}
        matched = {name: value for name, value in variables.items() if query.casefold() in name.casefold()}
        if query and not matched:
            raise ValueError("No matching decision values. Use lookup_variables to find their exact names.")
        names = {"v": dict(variables), "values": list(matched.values())} if variables else {}
        if solved.get("objective") is not None:
            names["objective"] = solved["objective"]
        result = simple_eval(expression, names=names, functions={"sum": sum, "min": min, "max": max,
            "abs": abs, "round": round, "len": len, "sqrt": math.sqrt}, allowed_attrs={})
        if type(result) not in (int, float) or not math.isfinite(result):
            raise ValueError("The expression must return a finite number.")
        facts = {"source": source, "expression": expression, "query": query,
                 "matched_variables": len(matched), "result": result}
        return json.dumps(facts, ensure_ascii=False), {"type": "calculation", "calculation": facts}

    @wrap_tool_call(tools=[calculate])
    async def calculation_errors(request: ToolCallRequest,
                                 handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]) -> ToolMessage | Command:
        try:
            return await handler(request)
        except TOOL_INPUT_ERRORS as error:
            if request.tool_call["name"] != "calculate":
                raise
            return ToolMessage(str(error), name="calculate", tool_call_id=request.tool_call["id"], status="error")

    return calculation_errors
