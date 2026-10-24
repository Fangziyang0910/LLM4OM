Requirement revision changes one or more conditions of an existing problem and computes a new plan. The original problem, configuration and result remain available.

## Start a revision

Click Adjust conditions on the result page. State what changes and what stays fixed:

```text
Produce at least 3 units of B. Keep all other conditions unchanged.
```

Generate new plan first prepares a complete revised problem. It then inherits the original method, LLM preset, library, backend and attachments, and solves again. You can make the same request through [plan chat](../plan-chat/).

## Read the comparison

The new run shows both objectives, decision changes and problem-text differences. In the production example, original profit is CNY 13; requiring at least 3 units of B changes the optimum to CNY 12.

The baseline comes from a checkpoint saved when revision starts. Rerunning the original thread later does not rewrite that comparison. Variables match by name; added or missing variables are identified rather than treated as zero.

## Choose a baseline for later changes

In conversation, a single new plan becomes current and later revisions start from it. Say “Start from the original plan” to return to the original requirements. Use [business scenarios](../scenarios/) for multiple independent changes.

## What to check

Review the new problem to ensure it changes only the intended requirements. If objective meaning or units change, interpret each objective in its own business context rather than comparing numbers alone. Check recorded data after changing attachments. Deleting the original run removes its baseline checkpoint, while the new run remains separately saved.
