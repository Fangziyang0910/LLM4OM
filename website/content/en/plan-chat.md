Choose Discuss plan on a result page to ask about that run's problem, formulation and actual values. The assistant reads a fixed result; ordinary explanation does not solve again.

## Questions to ask

```text
Explain the shipment quantities from each warehouse.
Which resource limits further production? Point to the model evidence.
Calculate total shipping cost and remaining inventory for this plan.
```

Totals, resource balances and ratios can use actual decision values directly. A Calculation check card shows the computed value; expand it to inspect the expression and number of variables read. This tool can access complete variables beyond the text explanation's display range.

## When you need a new plan

State the change explicitly: “Increase the budget to 1200, keep all other conditions and recalculate.” The assistant inherits the baseline's method, LLM preset, library, backend and attachments, prepares a new problem and executes the full workflow.

The conversational reply can use a separately selected preset. This does not rewrite the baseline's saved modeling configuration. Each new plan is saved independently and can be opened for complete inspection and export.

## Current and historical plans

The assistant identifies the Current discussion plan. Viewing history changes what you see, rather than the baseline for later computation. Explicitly say “Return to the original plan” or identify another saved plan to switch it.

A single new plan becomes current. Multiple scenarios are calculated from the same baseline, leaving the current plan unchanged.

## Stop, refresh and retry

Enter sends and Shift+Enter inserts a line break. Stop or retry as needed; conversations remain available after refresh. If the final reply fails, saved results can still be opened and retries read the completed plans. Deleting the conversation does not delete those independent runs.
