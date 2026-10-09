"""Installed methods assess and select candidates through the public CLI."""

import json
import os
import subprocess
import sys
import unittest
import yaml

import test_plugins


class CandidateFeedbackTests(unittest.TestCase):
    setUp = test_plugins.PluginTests.setUp
    configured_run = test_plugins.PluginTests.configured_run
    cli = test_plugins.PluginTests.cli

    def install_method(self, *, run_body: str) -> None:
        test_plugins.PluginTests.install_method(self, run_body=run_body, describe_body='''manifest = json.loads(files(__package__).joinpath("manifest.json").read_text())
manifest["capabilities"].update(method_profile="grounded_candidates/0.1.0", supports_checkpoint=True, execution_modes=["trusted_local", "container"])
return manifest''')

    def test_invalid_parent_and_repaired_child_keep_real_evidence(self) -> None:
        self.install_method(run_body='''from copy import deepcopy
response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
bad = deepcopy(payload["structured_ir"])
bad["objective"]["expression"]["terms"][0]["variable_id"] = "missing"
first = await context.resources.assess("001", ModelProposal(payload["artifact"], payload["formulation"], bad))
assert first["status"] == "invalid" and first["diagnostics"][0]["code"] == "invalid_ir"
second = await context.resources.assess("002", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]),
    parent_id="001", change_reason="Restore the declared decision ID; keep both business constraints.")
assert second["has_primal_solution"] and second["termination"] == "optimal"
return context.resources.select("002", rule="legal-primal-latest/0.1.0", reason="The child compiles and has a trusted primal; the parent has an invalid decision reference.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["budget"].update(max_candidates=2, max_repairs=1)
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        result, path, bundle = self.configured_run()
        error = bundle.get("error") or {}
        details = error.get("details_ref")
        self.assertEqual(result.returncode, 0, (error, (path / details["relative_path"]).read_text() if details else result.stderr))
        self.assertEqual(bundle["final_candidate_id"], "002")
        parent = json.loads((path / "candidates/001/assessment.json").read_text())
        self.assertEqual(parent["status"], "invalid")
        child = json.loads((path / "candidates/002/candidate.json").read_text())
        self.assertEqual(child["parent_ids"], ["001"])
        self.assertIn("keep both business constraints", child["change_reason"])
        self.assertEqual(child["status"], "selected")
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        solution = json.loads((path / solve["solution_ref"]["relative_path"]).read_text())
        self.assertEqual(solution["variables"], {"qty_A": 3, "qty_B": 2})
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["repairs"], ledger["solver_calls"]), (2, 1, 1))
        selection = json.loads((path / "candidate-selection.json").read_text())
        self.assertEqual(selection["rule"], "legal-primal-latest/0.1.0")
        self.assertEqual(selection["candidate_id"], "002")

    def test_zero_repairs_and_completed_replay_do_not_consume_more_solver_calls(self) -> None:
        self.install_method(run_body='''from llm4om.contracts import RunError
response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
proposal = ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"])
first = await context.resources.assess("001", proposal)
assert await context.resources.assess("001", proposal) == first
try:
    await context.resources.assess("002", proposal, parent_id="001", change_reason="Try another candidate.")
except RunError as error:
    assert error.code == "budget_exhausted"
else:
    raise AssertionError("max_repairs=0 must stop the repair")
return context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="The initial candidate has a primal; repairs are disabled.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["budget"]["max_candidates"] = 2
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 0, bundle.get("error"))
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["repairs"], ledger["solver_calls"]), (1, 0, 1))
        self.assertFalse((path / "candidates/002").exists())
        resumed = self.cli("resume", "--run-id", bundle["run_id"], "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertEqual(json.loads((path / "budget-ledger.json").read_text()), ledger)

    def test_identity_and_selection_cannot_be_rebound(self) -> None:
        self.install_method(run_body='''from copy import deepcopy
from llm4om.contracts import RunError
response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
proposal = ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"])
await context.resources.assess("001", proposal)
changed = deepcopy(payload["structured_ir"])
changed["objective"]["expression"]["constant"] = 7
for candidate_id, candidate, parent, expected in [
    ("001", ModelProposal(payload["artifact"], payload["formulation"], changed), None, "checkpoint_incompatible"),
    ("002", proposal, "absent", "invalid_candidate"),
    ("002", proposal, None, "budget_exhausted")]:
    try:
        await context.resources.assess(candidate_id, candidate, parent_id=parent, change_reason="Test input identity.")
    except RunError as error:
        assert error.code == expected
    else:
        raise AssertionError("Invalid identity must fail before execution")
selected = context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="The original candidate has a trusted primal.")
try:
    context.resources.select("001", rule="different-rule", reason="Overwrite the saved selection.")
except RunError as error:
    assert error.code == "invalid_selection"
else:
    raise AssertionError("Selection must be immutable")
return selected''')
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 0, bundle.get("error"))
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["solver_calls"]), (1, 1))

    def test_candidate_assessment_uses_the_real_isolated_highs_worker(self) -> None:
        self.install_method(run_body='''response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
feedback = await context.resources.assess("001", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]))
assert feedback["has_primal_solution"] and not feedback["diagnostics"]
return context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="The isolated Worker returned a trusted primal.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["executor"] = {"plugin_id": "llm4om.executors.container", "config": {
            "cpu_limit": 1, "memory_limit_mb": 512, "wall_time_s": 15, "pids_limit": 64,
            "output_limit_bytes": 1048576, "network": False}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        result, path, bundle = self.configured_run()
        self.assertEqual(result.returncode, 0, bundle.get("error"))
        solve = json.loads((path / bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        self.assertEqual(solve["evidence_origin"], "trusted_container_worker")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"], 1)

    def test_doctor_refuses_offline_candidate_assessment_before_generation(self) -> None:
        self.install_method(run_body='raise AssertionError("Offline candidate assessment must fail admission")')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        result = self.cli("doctor", "--offline", "--config", str(self.inputs / "solve.yaml"))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "capability_mismatch")

    def test_resume_after_method_process_exit_reuses_the_assessed_candidate(self) -> None:
        self.install_method(run_body='''import os
if checkpoint is None:
    response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
    payload = json.loads(response.text)
    checkpoint = {"schema_version": "0.1.0", "payload": payload, "assessed": False}
    context.save_checkpoint(checkpoint)
payload = checkpoint["payload"]
await context.resources.assess("001", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]))
if not checkpoint["assessed"]:
    checkpoint["assessed"] = True
    context.save_checkpoint(checkpoint)
    os._exit(73)
return context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="Reuse the completed public assessment after process recovery.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        result = self.cli("run", "--problem", str(self.inputs / "problem.json"), "--config", str(self.inputs / "solve.yaml"),
                          "--output", str(self.root / "runs"))
        # The run uses the installed method, with the same fixed configuration on resume.
        if result.returncode != 73:
            self.fail("The fixture must exit after its assessment: " + result.stdout + result.stderr)
        path = next(p for p in (self.root / "runs").iterdir() if (p / "checkpoint.json").exists())
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["solver_calls"], ledger["llm_attempts"]), (1, 1, 1))

    def test_unknown_execution_after_hard_exit_is_not_repeated(self) -> None:
        self.install_method(run_body='''response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
context.save_checkpoint({"schema_version": "0.1.0"})
await context.resources.assess("001", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]))
return context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="Choose the completed candidate.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        script = '''import json, os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "checkpoint.json":
        state = json.loads(Path(target).read_text())["payload"]["state"]
        if state.get("phase") == "execute_pending":
            os._exit(92)
    return result
os.replace = crash
sys.exit(main())'''
        result = subprocess.run([sys.executable, "-c", script, "run", "--problem", str(self.inputs / "problem.json"),
            "--config", str(self.inputs / "solve.yaml"), "--output", str(self.root / "runs")],
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(test_plugins.ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, cwd=self.root, timeout=30)
        self.assertEqual(result.returncode, 92, result.stdout + result.stderr)
        path = next(p for p in (self.root / "runs").iterdir() if (p / "checkpoint.json").exists())
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 1, resumed.stdout + resumed.stderr)
        bundle = json.loads((path / "bundle.json").read_text())
        self.assertEqual(bundle["error"]["code"], "execution_outcome_unknown")
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["solver_calls"], ledger["llm_attempts"]), (1, 1, 1))

    def test_crash_after_assessment_publication_recovers_the_completed_receipt(self) -> None:
        self.install_method(run_body='''response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
context.save_checkpoint({"schema_version": "0.1.0"})
await context.resources.assess("001", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]))
return context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="Choose the completed candidate.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        script = '''import os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "assessment.json" and "history" not in Path(target).parts:
        os._exit(91)
    return result
os.replace = crash
sys.exit(main())'''
        result = subprocess.run([sys.executable, "-c", script, "run", "--problem", str(self.inputs / "problem.json"),
            "--config", str(self.inputs / "solve.yaml"), "--output", str(self.root / "runs")],
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(test_plugins.ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, cwd=self.root, timeout=30)
        self.assertEqual(result.returncode, 91, result.stdout + result.stderr)
        path = next(p for p in (self.root / "runs").iterdir() if (p / "checkpoint.json").exists())
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["solver_calls"], ledger["llm_attempts"]), (1, 1, 1))

    def test_published_final_selection_resumes_without_reentering_the_method(self) -> None:
        self.install_method(run_body='''response = await context.llm.complete({"request_id": "initial", "messages": [{"role": "user", "content": "fixture"}]})
payload = json.loads(response.text)
context.save_checkpoint({"schema_version": "0.1.0"})
await context.resources.assess("001", ModelProposal(payload["artifact"], payload["formulation"], payload["structured_ir"]))
context.resources.emit({"phase": "selecting"})
return context.resources.select("001", rule="legal-primal-latest/0.1.0", reason="Choose the completed candidate.")''')
        settings = yaml.safe_load((self.inputs / "solve.yaml").read_text())
        settings["method"] = {"plugin_id": "llm4om.examples.objective_offset", "config": {"objective_offset": 7}}
        (self.inputs / "solve.yaml").write_text(yaml.safe_dump(settings))
        script = '''import os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "candidate-selection.json" and "history" not in Path(target).parts:
        os._exit(93)
    return result
os.replace = crash
sys.exit(main())'''
        result = subprocess.run([sys.executable, "-c", script, "run", "--problem", str(self.inputs / "problem.json"),
            "--config", str(self.inputs / "solve.yaml"), "--output", str(self.root / "runs")],
            env={**os.environ, "PYTHONPATH": os.pathsep.join((str(test_plugins.ROOT / "src"), str(self.packages)))},
            capture_output=True, text=True, cwd=self.root, timeout=30)
        self.assertEqual(result.returncode, 93, result.stdout + result.stderr)
        path = next(p for p in (self.root / "runs").iterdir() if (p / "checkpoint.json").exists())
        resumed = self.cli("resume", "--run-id", path.name, "--output", str(path.parent))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        events = [json.loads(line) for line in (path / "events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(e.get("method_event") == {"phase": "selecting"} for e in events), 1)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["candidates"], ledger["solver_calls"], ledger["llm_attempts"]), (1, 1, 1))


if __name__ == "__main__":
    unittest.main()
