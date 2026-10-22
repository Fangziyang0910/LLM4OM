"""Adapted from OptiGuide/optimind (MIT); source and license are retained in source/."""

import ast
import csv
from functools import cache
from pathlib import Path

SYSTEM = """You are an expert in optimization and mixed integer programming. You are given an optimization problem \
and you need to solve it using {library}. Reasoning step by step before generating the code. The user will execute \
the code and return the standard output and error to you, and you should use the user response to refine your \
previously generated code. When you are satisfied with the code, you can put your final answer in the format of \
`#### <answer>` without another code block.

{target}

Whenever you provide code, also provide its mathematical formulation in Markdown with LaTeX, followed by one \
complete ```python code block."""

HINT_INSTRUCTIONS = """Instructions for applying error-analysis hints:
- Review the provided hints and identify which ones are applicable to this problem.
- Please apply ALL applicable hints.
- Before applying any hint or writing constraints, check the sign and direction of every variable and coefficient \
for consistency (e.g., profit = revenue - cost; capacities as ≤; flow conservation as =).

General modeling checklist (follow rigorously):
- Units: Use correct units everywhere and ensure the objective's units match the goal (e.g., dollars for \
cost/profit, distance for TSP, time for scheduling). Do not mix units (e.g., minutes with hours, dollars with \
1000 dollars) without converting."""

FEEDBACK = """The standard output, result and error message (if any) for your generated code are as follows:
{result}

Based on the output and error message (if any), please think step by step to determine if the code is correct.
Based on your thoughts, please provide an improved code block if you have identified mistakes in the previous \
code. If the previous code is correct, you do not need to provide a new code block again.
Your performance will be evaluated based on the correctness of the final code block."""


@cache
def hint_bank() -> dict[str, list]:
    with Path(__file__).with_name("source").joinpath("hints_subset.csv").open(encoding="utf-8", newline="") as file:
        return {row["problem_class"]: ast.literal_eval(row["error analysis"]) for row in csv.DictReader(file)}


def hints(classes: list[str]) -> str:
    items = [", ".join(pair) for name in classes for pair in hint_bank()[name]]
    return HINT_INSTRUCTIONS + "\n\n" + "\n".join(f"Error analysis #{i}: {text}" for i, text in enumerate(items))
