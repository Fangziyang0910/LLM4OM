LLM4OM turns a business problem and its data into an optimization model, then uses a solver to compute a concrete plan. Describe requirements in natural language, inspect the model and actual values, and recalculate when conditions change.

## Where to begin

Follow [Your first plan](../quickstart/) for a complete example. If you do not have access to a running platform, use [Install and launch](../installation/) to start one on your computer or server. The product website uses fixed interactive examples; the full platform accepts your own problems and attachments.

There are two parallel entry points:

| Entry point | How it works |
|---|---|
| [Optimization chat](../chat-agent/) | Send a problem and data, then compute and revise plans through conversation |
| [Manual modeling workbench](../run-settings/) | Edit the problem, select a configuration and click Start modeling |

If the problem is still unclear, use [requirements chat](../requirements/) to prepare an editable draft first.

The workbench's lower-left controls switch Chinese/English and light, dark or system appearance. Smaller screens use tabs for the main content and assistant; desktop dividers resize the workspace.

## What a run produces

A run saves the problem, attachments, mathematical model, solver code, actual solver result and intermediate steps. Discuss the result, revise requirements, or export Excel, CSV and Markdown reports.

An optimal status applies to the mathematical model the solver actually computed. Before using a plan, check that its objective, constraints, data and variable meanings match the business problem. See [Review and export results](../results/).

## Continue by task

- For everyday use, follow the user guides from [data preparation](../attachments/) to [scenario comparison](../scenarios/).
- For modeling strategies, read [Modeling methods](../methods/). Each method has its own workflow and current parameters.
- For computation tools, read [Libraries and solvers](../solvers/) for capabilities, backends and license requirements.
- For shared use, read [Team deployment](../team-deployment/) and [Configuration and backups](../configuration/).
