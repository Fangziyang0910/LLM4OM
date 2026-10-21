"""Tools for managing code artifacts in state."""

from langchain.agents.middleware import after_model
from langchain.messages import AIMessage, ToolMessage
from langchain.tools import ToolRuntime, tool
from langgraph.prebuilt import ToolNode
from langgraph.types import Command

from llm4om.methods.trival.schema import ContextSchema, logger


def _code_preview(code: str, max_lines: int = 8) -> str:
    """Generate a code preview, showing only the first few lines."""
    if not code:
        return "(empty)"
    lines = code.strip().split("\n")
    preview_lines = lines[:max_lines]
    if len(lines) > max_lines:
        preview_lines.append(f"... (total {len(lines)} lines)")
    indented = "\n".join("    │ " + line for line in preview_lines)
    border = "    " + "─" * 50
    return f"{border}\n{indented}\n{border}"


@tool("write_code")
def write_code(code: str, runtime: ToolRuntime[ContextSchema]) -> Command:
    """Overwrite the entire code in state with new code.

    Use this for: initial code generation or major rewrites (>50% changes).

    Args:
        code: Complete Python code to write
    """

    line_count = len(code.strip().split("\n")) if code else 0
    logger.info(
        "📝 write_code: Writing code (%d lines)\n%s", line_count, _code_preview(code)
    )

    return Command(
        update={
            "code": code,
            "messages": [
                ToolMessage(
                    content=f"<result>Code written: {line_count} lines</result>",
                    tool_call_id=runtime.tool_call_id,
                    name="write_code",
                )
            ],
        }
    )


@tool("edit_code")
def edit_code(search: str, replace: str, runtime: ToolRuntime[ContextSchema]) -> Command:
    """Replace a code fragment with new content.

    Use this for: bug fixes, small changes, parameter adjustments.

    Critical: The search fragment must be UNIQUE in current code. Include 3-5 surrounding lines for context.

    Args:
        search: Exact code fragment to find (must appear exactly once)
        replace: New code to insert instead
    """

    code = runtime.state.get("code")

    if code is None:
        logger.warning("❌ edit_code: state.code is empty, cannot edit")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="<error>Code is empty. Use write_code() first.</error>",
                        tool_call_id=runtime.tool_call_id,
                        name="edit_code",
                    )
                ]
            }
        )

    occurrences = code.count(search)
    old_lines = len(search.strip().split("\n") if search else [])
    new_lines = len(replace.strip().split("\n") if replace else [])
    logger.info(
        "🔍 edit_code: Searching (%d→%d lines), found %d occurrences",
        old_lines,
        new_lines,
        occurrences,
    )

    if occurrences == 0:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="<error>Search fragment not found.\nFix: Use read_code() to check current code, ensure exact match including indentation.</error>",
                        tool_call_id=runtime.tool_call_id,
                        name="edit_code",
                    )
                ]
            }
        )

    if occurrences > 1:
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="<error>Search fragment appears multiple times.\nFix: Include more surrounding lines to make it unique.</error>",
                        tool_call_id=runtime.tool_call_id,
                        name="edit_code",
                    )
                ]
            }
        )

    new_code = code.replace(search, replace, 1)
    new_total_lines = len(new_code.strip().split("\n"))
    logger.info("✅ edit_code: Success (code now %d lines)", new_total_lines)

    return Command(
        update={
            "code": new_code,
            "messages": [
                ToolMessage(
                    content=f"<result>Replaced {old_lines} lines with {new_lines} lines</result>",
                    tool_call_id=runtime.tool_call_id,
                    name="edit_code",
                )
            ],
        }
    )


@tool("read_code")
def read_code(runtime: ToolRuntime[ContextSchema]) -> Command:
    """Read the current code from state.

    Use this to inspect code before making edits.
    """

    code = runtime.state.get("code")

    if not code:
        logger.warning("📭 read_code: state.code is empty")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        content="<result>No code in state. Use write_code() first.</result>",
                        tool_call_id=runtime.tool_call_id,
                        name="read_code",
                    )
                ]
            }
        )

    line_count = len(code.strip().split("\n"))
    logger.info("📖 read_code: Returning code (%d lines)", line_count)

    return Command(
        update={
            "messages": [
                ToolMessage(
                    content=f"<code lines={line_count}>\n{code}\n</code>",
                    tool_call_id=runtime.tool_call_id,
                    name="read_code",
                )
            ]
        }
    )


@after_model(can_jump_to=["model"])
async def apply_code_tool_calls(state, runtime):
    message = state["messages"][-1]
    if not isinstance(message, AIMessage) or len(message.tool_calls) < 2:
        return None

    # Code edits must see prior edits and reach the state graph as one update.
    working_state = dict(state)
    messages = []
    tools = ToolNode([write_code, edit_code, read_code])
    for call in message.tool_calls:
        current = message.model_copy(update={"tool_calls": [call]})
        output = await tools.ainvoke({**working_state, "messages": [current]})
        for item in output if isinstance(output, list) else [output]:
            update = item.update if isinstance(item, Command) else item
            messages.extend(update.get("messages", []))
            working_state.update(
                {key: value for key, value in update.items() if key != "messages"}
            )

    result = {"messages": messages, "jump_to": "model"}
    if "code" in working_state:
        result["code"] = working_state["code"]
    return result
