"""Execute state.code through the platform: the sandbox builds the model and the solver of the selected language solves it.

Adaptation: TriVAL ran the generated script in a local subprocess and used its printed output as
execution feedback. The platform runs `build_model(data)` in the sandbox and reports the solver's
status, objective and variable values; that report is the execution feedback here.
"""

from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import ContextSchema, logger
from llm4om.methods.trival.state import State


async def code_executor(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
):
    """Execute Python code in state.code and backfill the execution results."""
    code = state.get("code") or ""
    execution_count = state.get("code_execution_count", 0)

    if not code:
        logger.warning("⚠️ code_executor: state.code is empty")
        return {
            "code_executable": False,
            "execution_feedback": "[Code Executor] state.code is empty, no code executed.",
            "code_execution_count": execution_count + 1,
        }

    logger.info("🚀 code_executor: Executing code (attempt %d)", execution_count + 1)
    result = await runtime.context.solve(code, title=f"执行代码（第 {execution_count + 1} 次）")

    return {
        "code_executable": result.executed,
        "execution_feedback": result.feedback(),
        "code_execution_count": execution_count + 1,
    }
