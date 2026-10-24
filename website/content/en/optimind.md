OptiMind combines problem-type hints with multi-turn solver feedback. It matches available public hints, generates and executes a model, then asks the LLM to revise or finish.

## Workflow

```text
Classify type → public hints → generate → solve → feedback
                                  ↑               ↓ revise or finish without code
                                  └───────────────┘
```

Feedback is provided even after successful solving. The LLM can return revised code or finish with a code-free answer, retaining the last actually executed model and result.

## How to use it

Select OptiMind with a library and backend suitable for the problem. Traveling-salesman problems may match the public specialized hints. Unmatched problems use general checking guidance. Selecting the method does not automatically load a dedicated trained model.

## Current public scope

The distributed specialized library contains only `TravelingSalesman`, with six error/hint pairs. The platform does not invent unpublished types or add majority voting by default. It uses one trajectory, with generation limited by the current preset below.

If no valid execution exists and a reply lacks code, the method requests code again. Exhausting the limit reports failure rather than treating an unexecuted answer as completion. Inspect explanatory text and actual numerical results separately.

## Source and adaptation

See the [pinned OptiGuide/OptiMind source](https://github.com/microsoft/OptiGuide/tree/419cf7b9eee20b6af036abf15152fa775b20c951/optimind) and [paper](https://arxiv.org/abs/2509.22979). The platform adds classification restricted to public hints and supplies solver statuses and variables as feedback. OptiMind-SFT weights are not downloaded; presets can connect an independently deployed model service.
