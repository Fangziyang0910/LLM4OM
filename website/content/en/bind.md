BIND shows JSON/CSV structure to the LLM and reads complete data during code execution. It addresses data copying and truncated attachment previews on longer inputs.

## Workflow

```text
Attachment structure → formulation and code → read full attachments and solve
                                              ↓ execution or format error
                                      regenerate with conversation feedback
```

The LLM receives fields, types, array lengths or CSV row counts. Nested, heterogeneous and nonrectangular JSON structures are described as they are. Full values remain available to execution.

## Prepare the input

Explain fields, units and rules in the problem. For example: “quantity in each order is demand; warehouse_costs is the unit shipping-cost matrix from warehouses to stores.” Upload JSON or CSV, then select BIND and a compatible library.

Excel worksheets are converted to CSV by the UI. Without attachments, BIND models directly from the statement. It does not add PDF or image parsing.

## Interpret the result

Check that code binds the intended fields, rows, columns and units. Full-data binding does not replace business-model review. Successful execution with a solver status can finish the workflow. Genuine infeasibility is valid and does not trigger constraint relaxation to match a reference answer.

## Source and adaptation

The integration follows schema offloading and the default agentic path in the [pinned Text2Opt-Bench source](https://github.com/SprocketLab/Text2Opt-Bench/tree/1dac06be656c41d827ef20987cf8af0b48d382a2); see the [paper](https://arxiv.org/abs/2605.21751). User attachments replace benchmark instances. Reference-optimum and model-size scoring dependencies are removed. Outputs include a formulation and `build_model(data)`, with bounded execution repair.
