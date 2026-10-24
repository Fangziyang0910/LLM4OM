Homepage examples introduce the workflow; public problem collections expose different statements and structures. Load a problem into the editor, then run it with your configuration.

## Three introductory tasks

| Example | Decision | Changes to try |
|---|---|---|
| Production | Quantities per product | Hours and minimum orders |
| Staffing | Employee-by-day assignments | Availability and coverage |
| Delivery assignment | Vehicle-to-store matching | Disable a route or change costs |

The homepage provides three interactive fixed cases. [Quickstart](../quickstart/) includes the production statement, recording and data. [OR-Tools](../ortools/) supplies staffing code; [CPMpy](../cpmpy/) supplies assignment code.

## Download production data

Use [production.json](../../../assets/examples/production.json) or [production.csv](../../../assets/examples/production.csv). Explain products, time units and resource capacities before running.

```text
Choose nonnegative integer quantities of A and B to maximize profit.
Each resource has 8 hours. Processing data uses hours per unit.
JSON usage rows identify resources and columns identify products.
```

## Public problem collections

The library contains 2,033 statements across nine groups:

| Collection | Count | Collection | Count |
|---|---:|---|---:|
| NL4Opt | 205 | IndustryOR | 99 |
| NL4LP | 178 | ComplexOR | 18 |
| MAMO Easy | 642 | OptiBench | 403 |
| MAMO Complex | 210 | OptMATH | 128 |
| NL4COP | 150 | | |

Statements use the [OPT-Agent](https://github.com/Fangziyang0910/OPT-Agent) collection. Provenance and licenses are recorded in [benchmark sources](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/references/benchmark-sources.md).

## Use a problem

Choose a group and statement, read it, and load it into the editor. Select method and solver according to domains, constraints and objective. After solving, tag the source and export the model, code and result.

For comparison, fix the data and preset and use [method comparison](../method-comparison/). For tasks requiring additional data, develop fields and units in the [requirements assistant](../requirements/).

## Build your own case library

Prepare business attachments, record meanings and adopted rules in notes, and tag runs. Revisions and scenarios connect later changes, gradually forming reusable team cases.
