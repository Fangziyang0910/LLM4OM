Data and the problem statement together form the modeling input. Explain each field and its units, especially the relationships between costs, times, quantities and identifiers.

## Supported files

Upload CSV, TSV, JSON, text or Excel `.xlsx` workbooks. Each Excel worksheet becomes a separate CSV attachment. Ordinary attachments have a 2 MB per-file limit; converted worksheets are used as separate data files.

A production table could contain:

```csv
Product,Profit (CNY),Cutting units,Processing units
A,3,2,1
B,2,1,2
```

State resource capacities and variable domains in the problem text. The table supplies parameters; the description explains how to use them.

## Inspect and edit

Click an attachment name to open the editor. CSV and TSV support cell and column-name editing. JSON and text use the source editor. Tables show 50 rows per page while pagination and saving retain the entire dataset. Use source editing for more than 50 columns.

Values retain their original text, so identifier `001` does not silently become `1`. Fix incomplete CSV quotes or invalid JSON before saving. Save data applies edits; Cancel keeps the original attachment.

![Dark English data editor](../../../assets/screens/en/data.png)

## How complete data reaches computation

Ordinary methods may see an attachment preview in their prompts. Generated code reads the full content through `build_model(data)`. [BIND](../bind/) passes JSON/CSV structure to the LLM and parses the complete data during execution, which is useful for long datasets.

## After changing data

Editing draft or chat attachments affects later computation. Saved plans retain their original inputs. Explicitly request a new model or start another run to use updated attachments, then check the files recorded with the new problem.
