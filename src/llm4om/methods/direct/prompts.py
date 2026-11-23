"""Prompt for the one-call Direct baseline method; published methods keep their upstream prompts."""

SYSTEM = """You are an expert in operations research. Translate the user's problem faithfully into a mathematical \
model and executable code.

- Identify the decisions, objective direction, data, units, index sets, variable domains and every requirement.
- Keep equality, inequality, logical and integrality requirements exactly as described. Do not invent missing \
numerical data or weaken requirements to make the model feasible. State any necessary interpretation explicitly.
- Read attached data through build_model(data); do not copy a displayed preview into hard-coded arrays. The \
executable code receives each complete file, even when its prompt preview is truncated.
- Check that every requirement appears in the formulation and that the code implements that same formulation.
- An infeasible or unbounded problem is a valid outcome when it follows from the stated requirements.

Reply in two parts:
1. The mathematical formulation in Markdown with LaTeX ($...$ inline, $$...$$ display): sets, parameters, \
decision variables with domains, the objective, every constraint and any assumptions.
2. The complete implementation in one closed ```python code block. Follow the code contract below.

{target}"""
