The manual workbench lets you review a complete problem and configuration before starting computation. Optimization chat can also specify these choices; see [Chat Agent](../chat-agent/).

## Select four settings

Open View run settings or Adjust configuration above the problem.

| Setting | What to consider |
|---|---|
| Modeling method | Generation, validation and repair workflow; see [Methods](../methods/) |
| Modeling library | Its ability to express the variables, objective and constraints; see [Libraries and solvers](../solvers/) |
| Solver backend | An installed engine compatible with the model; AUTO is the default |
| LLM preset | The language model service called during the run |

Method parameters are fixed in deployment presets, rather than editable per-run form fields. The run records the actual parameter snapshot for later inspection.

## Review the problem and start

Check decisions, objective direction, constraints, units, integer or continuous domains and attachment fields. Switch between Markdown editing and preview. Use `\(...\)`, `\[...\]` or `$$...$$` for formulas in a problem statement; a single `$` in a price remains text.

Click Done to close the settings, then Start modeling, or press Ctrl+Enter / Cmd+Enter. Wait for attachments to finish loading before starting.

## Follow progress

The server runs the computation while the page shows actual steps. Closing the browser does not cancel a background run. Reopening retrieves its process and current progress. Stopping preserves saved steps, but does not imply that a method can resume from the interrupted node.

## Handle incompatible settings

A library's interfaces do not imply that every backend can solve every model. Integer variables, for example, require an integer-capable backend. An explicitly selected backend is not silently replaced after failure. Read the full error and adjust configuration or model expression rather than using a continuous relaxation by mistake.
