Business scenario comparison asks how one original plan changes under several independent conditions. Each scenario is generated and solved from the same baseline, so one scenario's change does not carry into the next.

## Create scenarios

Choose Business scenario comparison below the original run and enter 2–6 names and changes. For the production example:

| Scenario | Change |
|---|---|
| At least 3 of B | Produce at least 3 units of B; keep everything else unchanged |
| At least 4 of B | Produce at least 4 units of B; keep everything else unchanged |

Click Calculate and compare. Each scenario inherits the same original problem, attachments and settings. You can also request several explicit scenarios in Optimization chat or plan chat.

## Read the actual differences

The original example earns CNY 13. These two scenarios have optima of CNY 12 and CNY 8. The comparison shows actual statuses, objectives, units and key decisions. Open an individual plan to inspect its complete model and variables.

![Business scenario comparison in the dark English workbench](../../../assets/screens/en/scenarios.png)

The comparison prioritizes the first 20 changed variables with matching names; each run retains all values. Missing variables appear as `—`. Objectives with different meanings or units are not directly ranked.

## Save and continue

Each scenario is an independent run and the original remains a fixed baseline. Creating several scenarios in chat does not switch the current discussion plan. Explicitly select a scenario to continue from it.

If some scenarios fail to start or save, completed runs remain available. Check which scenarios actually finished before retrying the remainder. A missing result does not mean infeasibility.
