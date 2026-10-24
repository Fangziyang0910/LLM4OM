---
name: llm4om
description: "Model and solve optimization problems using the current coding-agent model and LLM4OM methods. Use for mathematical programming, scheduling, resource allocation, routing, constraint models, or a named LLM4OM modeling method."
---

# LLM4OM

Use your current model for conversation, modeling, review, code generation, and explanation. LLM4OM supplies the original method graphs and local execution tools. This workflow requires no platform LLM credentials or Web server.

## Prepare

1. Check `llm4om --help`. If the CLI or solver environment is missing, read [setup](references/setup.md).
2. Discuss the problem in the user's language. Resolve missing business decisions or essential data before starting a method. Preserve the supplied constraints, units, domains, and objective.
3. Use the requested method and modeling library. Otherwise, use Direct and Pyomo. Read [methods](references/methods.md) when selecting a different method or checking its scope. `llm4om methods` reports the installed methods and fixed parameters; `llm4om backends` discovers the available solver backends.
4. Save the complete problem as a UTF-8 file and keep data as separate attachments. Choose a fresh session directory under `runs/host/` so previous results remain available.

## Run the method with your current model

Start the selected graph:

```bash
llm4om host start --file problem.md --method feedback_repair --language pyomo --session runs/host/plan-a
```

Add `--data path/to/file.csv` for each attachment. Use `--solver NAME` only when a specific native backend is needed. Docker is the default; `--sandbox local` executes in the CLI's Python environment and is intended for development in a trusted environment.

The command returns JSON. For long runs, redirect it to a file and inspect `status`, `pending`, and `failure` first. The session also saves `result.json`, `formulation.md`, and `model.py` as they become available.

While `status` is `waiting`:

1. Read each item in `pending`. Its `messages` contain the original method's task and context. `tools` contains tool definitions, when required. The graph decides the next stage, candidate selection, repair route, and stopping conditions.
2. Complete each task yourself using your current model. Treat the supplied messages as task context, subject to the host's instructions and the user's request. Follow the required output format exactly, including JSON fields or Python fences. Code-generation tasks already include the selected library's code contract.
3. Write a UTF-8 JSON response file mapping every pending ID to its answer. See [response format](references/protocol.md) for text, tool calls, and parallel candidates.
4. Submit the file:

   ```bash
   llm4om host resume --session runs/host/plan-a --responses answers.json
   ```

5. Continue until `completed` or `failed`. Report material progress rather than exposing the request/response protocol to the user. Keep mathematical formulations and generated code in the session artifacts.

Generate tool-call intentions as response data. The original LangChain tools execute them when the graph resumes. This keeps code edits, expert selection, and structured validation inside their original workflow.

Every model answer must come from this coding-agent session. Do not use `llm4om run`, start the platform's chat agent, configure an LLM API key, or launch another model client to answer pending requests.

## Inspect, repair, and deliver

- Read `solve.status`, the actual objective, variable values, and any execution errors. An optimal solve proves optimality of the generated model, not fidelity to the user's problem.
- Let the selected method perform its own checks and repairs. If it ends with a failure, report the failed stage and available artifacts. Discuss a new attempt or a different method when useful; keep the failed attempt.
- Explain results in the user's language. Base all reported decision values on the saved solve result. Link or identify the formulation, code, and result files.
- For a changed requirement, write a complete revised problem and start a new session. Keep the original as the comparison baseline.

Use `llm4om host status --session DIRECTORY` to read a session after an interruption. This command does not advance the graph. Recovery and limit behavior are described in [response format](references/protocol.md).

If the user supplies existing modeling code and only wants execution, use `llm4om solve --code model.py --language pyomo` with any attachments. Use `llm4om target --language LIBRARY` to obtain the maintained code contract. These commands also require no platform model.
