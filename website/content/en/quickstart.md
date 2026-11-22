Complete a production task from description through modeling, solving, export and revision. The example includes a statement, downloadable data and localized workbench recordings.

## 1. Prepare a service and preset

Before you start, confirm that:

- You can open your team service in a browser, or have [installed and started one](../installation/).
- At least one [model preset](../model-presets/) can make requests. Check the provider, endpoint, model ID and key in AI model settings, save it, then select it.
- For a self-hosted service, Docker is running and `uv run llm4om build-worker` has built the Worker for your CLI version. A successful model request does not verify the solving environment.

Enter credentials in local settings or the server environment, never in the problem or attachments. Select your preferred interface language before starting the run.

Send the problem in Optimization chat or use manual modeling. This example uses Direct, Pyomo and AUTO to match the recording.

## 2. Enter the problem

```text
Produce nonnegative integer quantities of products A and B.
A earns CNY 3 and uses 2 cutting hours and 1 finishing hour per unit.
B earns CNY 2 and uses 1 cutting hour and 2 finishing hours per unit.
There are 8 hours of each resource.
Calculate the production plan with maximum total profit.
```

Use the solve button to start, then follow formulation, code and solving. Begin with the complete statement above; it needs no attachment. For a data-file version, download [JSON](../../../assets/examples/production.json) or [CSV](../../../assets/examples/production.csv), describe fields and capacities, then run.

## 3. Review and export

The expected result is **A=3, B=2, total profit CNY 13**. Read quantities in Optimal Plan and expressions in Formulation/Code. Export Excel downloads solution and problem/conditions sheets.

Check these items before moving on:

| Check | Expected value |
|---|---|
| Variable domains | A and B are nonnegative integers |
| Cutting | $2\times3+2=8$ hours |
| Finishing | $3+2\times2=7\le8$ hours |
| Profit | $3\times3+2\times2=13$ CNY |

If the model or values differ, inspect the statement, attachments, domains and resource directions, then use [troubleshooting](../troubleshooting/). Rounding fractional values does not replace an integer constraint.

![Actual production result](../../../assets/screens/en/plan.png)

View run settings retains method, model and backend choices; the page also shows duration and usage. Open Solving Steps for individual stages. Raw model output is collapsed by default and can be expanded. It can contain English protocol fields; the localized reading view does not alter saved records.

## 4. Revise and compare

Request “B at least 3, with other conditions unchanged.” The new result is **A=2, B=3, profit 12**. Comparison shows changes from the original.

Use Business scenarios to calculate B≥3 and B≥4 together; profits are 12 and 8. See [scenario comparison](../scenarios/).

## 5. Follow the recording

```video
workbench
```

Sequence: enter production requirements → inspect profit 13 → enter two scenarios → compare 13, 12 and 8 → open the data editor → edit and save unit profit. Pause, enable captions or use fullscreen.

## 6. Try it in the docs

Change capacity, minimum demand or quantity domain, inspect the plan and download CSV. For your own task, use the [requirements assistant](../requirements/) or [Optimization chat](../chat-agent/).

```demo
production
```
