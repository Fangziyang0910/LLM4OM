LLMOPT builds a five-part formulation before generating code. Self-correction judges the formulation and code separately and routes repairs to the relevant stage.

## Workflow

```text
Sets, parameters, variables, objective, constraints → code → execute → self-correct
                   ↑ formulation error                   ↓ code error
                   └── redefine the model                 rewrite code
```

A formulation error returns to definition and then code generation. A code-only error returns to code generation. The result comes from actual execution, with re-solves limited by the preset.

## How to use it

Select LLMOPT when you want to inspect problem structure separately from its code mapping. Check all five sections, parameter sources and coverage of the original requirements.

The platform preserves correspondence between executed code and its result. New code that fails before execution does not inherit the previous version's solution.

## Workflow versus trained model

The research includes a fine-tuned and aligned model. The platform integrates the test-time five-part and self-correction workflow, using your selected preset. It does not automatically download the paper's model. To use released weights, deploy a compatible model service and add its preset.

## Source and adaptation

Prompts follow the [pinned LLMOPT source](https://github.com/antgroup/LLMOPT/tree/1492dd33e39ea13f1afe32a0adc13d4217334195); the correction loop follows the [paper](https://arxiv.org/abs/2410.13213). Upstream did not publish that loop's code, so routing decisions are documented in the original adaptation notes. Prompts use the chosen library and platform code contract. Research-reproduction license notes appear in the project NOTICE.
