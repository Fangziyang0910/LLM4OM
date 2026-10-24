The Chat Agent appears as Optimization chat in the sidebar. It combines requirements, actual modeling, result discussion and revisions in one ongoing conversation.

## Start with a message

Send a complete problem or discuss an initial idea. General questions, writing, code explanation and arithmetic do not automatically start optimization. When you need a plan, describe the decisions, objective and requirements, then attach any data.

```text
Use the attached data to schedule next week's staff.
At least 3 people must work each day; each person works at most 5 days.
A supervisor must work on weekends. Minimize total staffing cost.
```

The assistant asks for information that matters to the next step. Once the problem is clear, it runs the full modeling workflow, generates a formulation and code, and solves the model.

## Follow computation and inspect the plan

The conversation shows actual stages and links to saved plans. On desktop, the adjacent modeling workspace shows the process, formulation, code and results. Open the full run page to export Excel. Drag the divider, or focus it with Tab and use the arrow keys, to resize the panels.

Defaults are Direct, Pyomo and AUTO. Specify a method, library or backend in your message, or fix a method and library through Modeling preferences beside the input. For example: “Use BIND to read this JSON and model it with Pyomo.”

## Ask questions or change requirements

| Your message | What happens |
|---|---|
| “Why are these two people assigned to Tuesday?” | The assistant reads and explains the existing model and result |
| “Calculate weekend costs for this plan.” | It calculates from actual decisions without solving again |
| “Tuesday needs at least 4 people. Keep everything else and recalculate.” | It creates a revised problem and solves a new model |
| “Compare budgets of 1000 and 1200.” | It computes scenarios from the same baseline |

A single new plan becomes the current plan for later discussion. Say “Return to the original plan without recalculating” or “Use the second plan from now on” to select a baseline. Merely viewing a historical plan does not change it.

## Data, search and recovery

Click attachments to inspect or edit them. Changes affect later models. Explicitly request a new model to use updated data; saved plans retain their own inputs.

Enable web search when public information is useful and expand the sources. Confirm suggested business rules before using them in computation. The DeepSeek thinking toggle controls the conversation turn; modeling tools retain their run preset.

Enter sends; Shift+Enter inserts a line break. Stop or retry a turn as needed. Refresh reconnects to active runs. Saved plans remain available if the final text reply fails, and deleting a conversation does not delete its separately saved plans.
