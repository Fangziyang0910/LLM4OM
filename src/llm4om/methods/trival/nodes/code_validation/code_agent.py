from typing import Any

from langchain.agents import create_agent
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State

from .tools import apply_code_tool_calls, edit_code, read_code, write_code

CODE_AGENT_SYSTEM_PROMPT = """
## Role Description
You are an expert in optimization modeling code generation. Your task is to translate "Problem Description + Mathematical Formulation" into **standard mathematical modeling code**. If code errors are reported, you also need to fix the modeling code.

**Core Responsibilities**: Define the four pillars of modeling (parameters, decision variables, constraints, and objectives) in the model-building code required by the code contract below; the platform solves the model and reports the solver result; fix the code based on error feedback.

When execution errors or validation feedback occur: determine if the problem is a code-level error (API, index, dimension, or data structure); make only the minimum necessary changes; and do not change the model semantics or re-select the modeling approach.

## Core Principles
1. Modeling is declarative: define parameters, decision variables, constraints, and objectives. Tell the solver "what to solve," not "how to solve."
2. Semantic Primacy: The Problem Description defines the true problem semantics. The Mathematical Formulation is a highly reliable reference but **may not be perfect**. When the formulation clearly conflicts with the semantics, follow the semantics and choose the **minimum correction** to the modeling expression.
3. Semantic Preservation: Do not arbitrarily add, delete, or restructure modeling semantics. **Equivalent technical expression adjustments** are allowed to adapt to the solver API. It is forbidden to introduce new modeling assumptions, objectives, or preferences.

## Strict Boundaries
You only perform modeling, not solver design: implementing algorithms; you do not design Big-M, linearization, relaxation, decomposition, or other tricks. If a certain linearization or auxiliary variable structure is **already clearly given** in the formulation, you are responsible only for faithfully translating it into code; but you must not invent new ways of handling it on your own.

## Tools
- write_code(code): Large changes or initial generation
- edit_code(search, replace): Precise small fixes (prefer making all changes in one edit rather than multiple small edits)
- read_code(): View existing code when necessary (the current code is already in context, so avoid frequent reads)

""".strip()


async def code_agent(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
) -> dict[str, Any]:
    """Code generation agent - generates or fixes optimization code based on formulation."""

    logger.info("🛠️ code_agent called")

    agent = create_agent(
        model=runtime.context.llm("trival.code_agent"),
        tools=[write_code, edit_code, read_code],
        middleware=[apply_code_tool_calls],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=CODE_AGENT_SYSTEM_PROMPT + "\n\n" + runtime.context.target.prompt,
        name="code_agent",
    )

    code_validation_passed = state.get("code_validation_passed")
    code_validation_feedback = state.get("code_validation_feedback", "")
    code_executable = state.get("code_executable")
    execution_feedback = state.get("execution_feedback", "")

    content = f"""## Original Problem Description
{state.get("problem_description")}

## Mathematical Formulation
{state.get("formulation", "")}

The mathematical formulation above expresses the problem at the mathematical layer, for your reference when writing code.
"""

    if (
        code_validation_passed is False
        and code_validation_feedback
        and code_executable is not False
    ):
        content += f"""## Current Code
{state.get("code", "")}

## Validation Feedback
{code_validation_feedback}

Please fix the code based on the validation feedback above.
"""
    elif code_executable is False and execution_feedback:
        content += f"""## Current Code
{state.get("code", "")}

## Execution Error
{execution_feedback}

Please fix the code based on the error information above.
"""
    else:
        content += "\nPlease generate the complete optimization solver code based on the mathematical formulation above."

    instruction_msg = HumanMessage(content=content)

    result: dict[str, Any] = await agent.ainvoke(
        {**state, "messages": [instruction_msg]}, config=config
    )

    logger.info("✅ code_agent completed")

    code = result.get("code", state.get("code"))
    return {
        "code": code,
        "failure": None if code else state.get("failure"),  # llm4om: clear the pre-code failure after generation.
        "code_validation_passed": None,
        "code_validation_feedback": None,
    }
