from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

from llm4om.methods.trival.schema import CodeValidationOutput, ContextSchema, logger
from llm4om.methods.trival.state import State

CODE_VALIDATOR_SYSTEM_PROMPT = """
You are the code validator in Stage III. Your only job is to judge whether the executable code faithfully realizes the accepted formulation, and if not, whether the defect comes from the code or from the formulation.

### Core Standard
- The accepted formulation is the direct reference for implementation fidelity.
- Execution feedback is evidence, not the validation target itself.
- Do not judge coding style, formatting, or harmless implementation variation.
- Do not pass code unless it faithfully implements the variables, constraints, objective, and key parameters in the formulation.

### What to check
1. Implementation fidelity
- Do the implemented variables match the formulation in meaning, domain, and indexing?
- Do the implemented constraints faithfully realize the required logic, scope, and linking relations?
- Does the implemented objective match the formulation in direction and terms?
- Are key parameters and data structures consistent with the formulation?

2. Execution-grounded diagnosis
- Use execution output to detect hidden defects that only appear after running the code.
- Typical signals include runtime errors, API misuse, infeasibility, abnormal solver behavior, or nonsensical solutions.

3. Attribution
- Choose `error_attribution = "code"` if the defect is caused by implementation error.
  - Examples: syntax errors, API misuse, wrong indexing in code, missing implemented constraint, wrong objective sign in code, incorrect data construction.
- Choose `error_attribution = "formulation"` if the code faithfully implements the formulation but the observed defect indicates the formulation itself is wrong or incomplete.
  - Examples: executable code yields infeasibility or abnormal behavior because the formulation missed essential logic or used the wrong decision abstraction.

### Decision Rule
- PASS: only if the executable code faithfully realizes the accepted formulation and the solver outcome is compatible with that formulation.
- FAIL: if there is any material mismatch between the code and the formulation, or if execution reveals a formulation-level defect.

### Output
- Output MUST be a single JSON object and nothing else.
- `code_validation_feedback` must identify the exact mismatch or defect and explain whether correction should happen in code or in the formulation.
- `error_attribution` MUST be exactly `"code"` or `"formulation"`.

Examples:
{"code_validation_passed": true, "code_validation_feedback": "Passed. The executable code faithfully implements the formulation, and the solver outcome is compatible with the formulation.", "error_attribution": "code"}
{"code_validation_passed": false, "code_validation_feedback": "The code omits the inventory balance constraint defined in the formulation, so the implementation is not faithful and should be corrected in code.", "error_attribution": "code"}
{"code_validation_passed": false, "code_validation_feedback": "The code appears faithful to the formulation, but the solver outcome indicates the formulation itself is missing essential feasibility logic, so the defect should be traced back to the formulation.", "error_attribution": "formulation"}
""".strip()


async def code_validator(
    state: State, config: RunnableConfig, runtime: Runtime[ContextSchema]
):
    """Code validation node: provides validation conclusions and feedback based on code and execution output."""

    current_validation_count = state.get("code_validation_count", 0)

    content = f"""## Original Problem Description
{state.get("problem_description")}


## Mathematical Formulation
{state.get("formulation", "")}

## Code
{state.get("code", "")}

## Execution Output
{state.get("execution_feedback", "")}

Please complete the validation based on the content above."""

    instruction_msg = HumanMessage(content=content)

    logger.info(
        "🔍 Code Validator: Validating (attempt %d)", current_validation_count + 1
    )

    agent = create_agent(
        model=runtime.context.llm("trival.code_validator"),
        tools=[],
        state_schema=State,
        context_schema=ContextSchema,
        system_prompt=CODE_VALIDATOR_SYSTEM_PROMPT,
        response_format=ToolStrategy(CodeValidationOutput),
        name="code_validator",
    )

    result = await agent.ainvoke({**state, "messages": [instruction_msg]}, config=config)
    structured: CodeValidationOutput = result["structured_response"]
    passed = structured.code_validation_passed
    feedback = structured.code_validation_feedback
    error_attribution = structured.error_attribution

    if passed:
        logger.info("✅ Code Validator: PASSED")
    else:
        logger.info("❌ Code Validator: FAILED")

    return {
        "code_validation_passed": passed,
        "code_validation_feedback": feedback,
        "code_validation_count": current_validation_count + 1,
        "error_attribution": error_attribution,
    }
