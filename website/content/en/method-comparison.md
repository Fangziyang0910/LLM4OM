Method and LLM comparison runs one problem with several configurations and aligns results and usage. Use it to inspect how workflows handle your task and how changing the LLM preset affects the process.

## Start from run settings

Enable “Compare,” select methods or presets, and choose a shared library/backend. Up to 12 runs can start together. After confirming inputs, open the comparison page to follow progress.

Try Direct, Feedback Repair and TriVAL with one preset, or hold the method fixed and select two presets. Each row opens its complete run.

## Reading the table

| Field | Use |
|---|---|
| Method and preset | Identify the configuration |
| Status and objective | Read computed results |
| Elapsed time | Inspect total run duration |
| LLM calls and tokens | Understand generation, validation and repair usage |
| Run link | Read formulation, code, steps and inputs |

The page indicates objective agreement. Open a row to inspect a constraint, code version or validation finding.

## Follow one requirement across runs

For production with B≥3:

1. Find `B≥3` in the formulation.
2. Find its code constraint and integer domain.
3. Read A, B and profit in results.
4. Inspect whether repair occurred and what changed.

This connects call count and elapsed time to actual stages. A workflow may complete directly or find and revise a particular expression.

## Inputs and records

Each run retains the shared input snapshot plus its configuration, process and result. Add tags and notes to record observations across related runs.

Concurrency and hourly quotas control startup and queuing. If some runs fail to start, the comparison retains launched items and shows startup information for the rest. See [configuration and usage](../configuration/).

## Continue from the comparison

Open a run for inspection, export its report or revise business conditions from it. See [methods](../methods/) for mechanisms, parameters and worked examples, and [LLM presets](../model-presets/) for service configuration.
