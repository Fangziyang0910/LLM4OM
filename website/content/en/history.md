History preserves each run's problem, data, configuration and result so you can recover originals, compare revisions and record conclusions.

## Find related records

The sidebar groups requirements chats, runs, revisions and comparisons by their recorded problem origin. Expand Related records to inspect them. Identical titles do not automatically mean the same problem. Older records without origin information remain separate.

History loads 100 records at a time. Use Load earlier runs to continue. Text and tag filters apply to the loaded records, with that range shown in the interface.

## Notes, tags and reports

On a run page, choose More actions → Notes and tags to record conclusions and categories. Search for `#tag` in the sidebar. Export report (Markdown) saves the problem, settings, result, model, code and notes.

Runs and comparisons have stable links for people with access to the same platform. See [Results](../results/) for complete Excel and CSV exports.

## Rerun and delete

Run again uses the same problem and settings. Edit and run returns inputs to the editor. If the original preset was deleted, select another preset. Deleting an independent record does not cascade to other related runs; deleting an original removes its associated comparison baseline.

## Storage and shared access

Use the same workspace to retain presets and history across normal server restarts. Stopped runs retain saved steps, without guaranteeing that a method can resume from the interrupted point.

The workbench has no built-in login or user-level permissions. People who can access the service can view and manage shared records. Control access through networking or a reverse proxy and follow the [backup guide](../configuration/).
