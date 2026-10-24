Complete a production task from description through modeling, solving, export and revision. The example includes a statement, downloadable data and localized workbench recordings.

## 1. Prepare a service and preset

Open your team service or [install one](../installation/). Choose an available LLM preset; see [preset setup](../model-presets/) to add one.

Send the problem in Optimization chat or use manual modeling. This example uses Direct, Pyomo and AUTO to match the recording.

## 2. Enter the problem

```text
Produce nonnegative integer quantities of products A and B.
A earns CNY 3 and uses 2 cutting hours and 1 finishing hour per unit.
B earns CNY 2 and uses 1 cutting hour and 2 finishing hours per unit.
There are 8 hours of each resource.
Calculate the production plan with maximum total profit.
```

Start modeling and follow formulation, code and solving. For a data-file version, download [JSON](../../../assets/examples/production.json) or [CSV](../../../assets/examples/production.csv), describe fields and capacities, then run.

## 3. Review and export

The result is **A=3, B=2, total profit CNY 13**. Read quantities in Solution and expressions in Formulation/Code. “Export Excel” downloads solution and problem/conditions sheets.

![Actual production result](../../../assets/screens/en/plan.png)

Run information retains method, LLM, actual backend, duration and usage. Open the process for individual stages.

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
