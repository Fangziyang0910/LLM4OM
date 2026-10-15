"""Interactive clarification and problem revisions through public CLI/SDK."""

import json
import os
import subprocess
import sys
import unittest
from copy import deepcopy
from pathlib import Path

import test_feedback_repair


class ClarificationTests(unittest.TestCase):
    setUp = test_feedback_repair.FeedbackRepairTests.setUp
    run_responses = test_feedback_repair.FeedbackRepairTests.run_responses

    def cli_resume(self, path, *arguments):
        return subprocess.run([sys.executable, "-m", "llm4om", "resume", "--run-id", path.name,
            "--output", str(path.parent), *arguments], capture_output=True, text=True, cwd=self.root,
            env={**os.environ, "REPAIR_TEST_KEY": "synthetic-repair-key", "PYTHONPATH": str(test_feedback_repair.ROOT / "src")}, timeout=100)

    def test_confirm_existing_requirement_then_resume_with_real_highs(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "domain", "kind": "confirm_existing",
            "question": "Confirm the stated nonnegative integer quantities.",
            "statement_ref": {"kind": "requirement", "id": "R-DOMAIN"}}]}}
        path, bundle, requests = self.run_responses([question, self.compact])
        self.assertEqual(bundle["status"], "needs_input", bundle.get("error"))
        self.assertEqual(len(requests), 1)

        request = json.loads((path / bundle["clarification_request_ref"]["relative_path"]).read_text())
        answers = self.root / "answers.json"
        answers.write_text(json.dumps({"schema_version": "0.1.0", "request_id": request["request_id"],
            "action": "confirm", "answers": [{"question_id": "domain", "value": True}]}))
        resumed = self.cli_resume(path, "--answers", str(answers))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        completed = json.loads((path / "bundle.json").read_text())
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(requests), 2)
        prompt = json.loads(requests[1]["messages"][-1]["content"])
        self.assertEqual(prompt["clarifications"][0]["answers"][0]["value"], True)
        solve = json.loads((path / completed["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 13)
        ledger = json.loads((path / "budget-ledger.json").read_text())
        self.assertEqual((ledger["external_llm_requests"], ledger["checks"], ledger["solver_calls"]), (2, 1, 1))

    def test_published_answer_recovers_without_resubmitting_the_response_file(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "domain", "kind": "confirm_existing",
            "question": "Confirm the stated domain.", "statement_ref": {"kind": "requirement", "id": "R-DOMAIN"}}]}}
        path, bundle, requests = self.run_responses([question, self.compact])
        request = json.loads((path / bundle["clarification_request_ref"]["relative_path"]).read_text())
        answers = self.root / "answers.json"
        answers.write_text(json.dumps({"schema_version": "0.1.0", "request_id": request["request_id"], "action": "confirm",
            "answers": [{"question_id": "domain", "value": True}]}))
        script = '''import os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "response.json" and "clarifications" in Path(target).parts and "history" not in Path(target).parts:
        os._exit(91)
    return result
os.replace = crash
sys.exit(main())'''
        process = subprocess.run([sys.executable, "-c", script, "resume", "--run-id", path.name,
            "--output", str(path.parent), "--answers", str(answers)], cwd=self.root, capture_output=True, text=True,
            env={**os.environ, "REPAIR_TEST_KEY": "synthetic-repair-key", "PYTHONPATH": str(test_feedback_repair.ROOT / "src")}, timeout=100)
        self.assertEqual(process.returncode, 91, process.stdout + process.stderr)
        restored = self.cli_resume(path)
        self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
        self.assertEqual(json.loads(restored.stdout)["status"], "completed")
        self.assertEqual(len(requests), 2)

    def test_noninteractive_missing_information_is_unresolved_without_repeat_requests(self) -> None:
        question = {"clarification": {"questions": [{"question_id": "capacity", "kind": "new_information",
            "question": "Provide the missing capacity rule.", "statement_ref": None}]}}
        path, bundle, requests = self.run_responses([question])
        self.assertEqual(bundle["status"], "unresolved")
        self.assertEqual(len(requests), 1)
        before = (path / "budget-ledger.json").read_bytes()
        for _ in range(2):
            resumed = self.cli_resume(path)
            self.assertEqual(resumed.returncode, 1, resumed.stdout + resumed.stderr)
            self.assertEqual(json.loads(resumed.stdout)["status"], "unresolved")
        self.assertEqual(len(requests), 1)
        self.assertEqual((path / "budget-ledger.json").read_bytes(), before)

    def test_new_rule_creates_a_derived_revision_and_preserves_parent_public_history(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "rule", "kind": "new_information",
            "question": "Provide the additional product-A business rule.", "statement_ref": None}]}}
        revised_output = deepcopy(self.compact)
        revised_output["representation"]["constraints"].append({"id": "limit_A", "expression_text": "qty[A] <= 2", "requirement_ids": ["R-A-LIMIT"]})
        revised_output["structured_ir"]["constraints"].append({"id": "limit_A", "expression": {
            "constant": 0, "terms": [{"variable_id": "qty_A", "coefficient": 1}]}, "sense": "le", "rhs": 2, "requirement_ids": ["R-A-LIMIT"]})
        path, bundle, requests = self.run_responses([question, revised_output])
        parent_files = {name: (path / name).read_bytes() for name in ("public-problem.json", "bundle.json", "events.jsonl", "budget-ledger.json")}
        request = json.loads((path / bundle["clarification_request_ref"]["relative_path"]).read_text())
        answers = self.root / "answers.json"
        answers.write_text(json.dumps({"schema_version": "0.1.0", "request_id": request["request_id"], "action": "revise",
            "answers": [{"question_id": "rule", "value": "Product A must be at most 2."}]}))
        problem = json.loads((self.inputs / "problem.json").read_text())
        problem["revision"] = "2"
        problem["description"] += " 产品A的生产数量最多为2。"
        problem["requirements"].append({"id": "R-A-LIMIT", "text": "产品A的生产数量最多为2。", "category": "constraint", "source_span": None})
        revision = self.inputs / "revision-2.json"
        revision.write_text(json.dumps(problem))
        if getattr(self, "crash_derivation", False):
            script = '''import json, os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "checkpoint.json":
        state = json.loads(Path(target).read_text())["payload"]["state"]
        if state.get("clarification_derivations"):
            os._exit(91)
    return result
os.replace = crash
sys.exit(main())'''
            process = subprocess.run([sys.executable, "-c", script, "resume", "--run-id", path.name,
                "--output", str(path.parent), "--answers", str(answers), "--revised-problem", str(revision)],
                env={**os.environ, "REPAIR_TEST_KEY": "synthetic-repair-key", "PYTHONPATH": str(test_feedback_repair.ROOT / "src")},
                cwd=self.root, capture_output=True, text=True, timeout=100)
            self.assertEqual(process.returncode, 91, process.stdout + process.stderr)
        resumed = self.cli_resume(path, "--answers", str(answers), "--revised-problem", str(revision))
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        child = Path(json.loads(resumed.stdout)["bundle_path"])
        self.assertNotEqual(child, path)
        child_bundle = json.loads((child / "bundle.json").read_text())
        solve = json.loads((child / child_bundle["solve_result_ref"]["relative_path"]).read_text())
        self.assertEqual(solve["objective_value"], 12)
        self.assertEqual(json.loads((child / "public-problem.json").read_text())["revision"], "2")
        lineage = json.loads((child / "lineage.json").read_text())
        self.assertEqual(lineage["operation"], "clarification_revision")
        self.assertEqual(lineage["parent_run_id"], path.name)
        self.assertEqual(lineage["parent_budget_ledger"]["external_llm_requests"], 1)
        self.assertEqual(json.loads((child / "budget-ledger.json").read_text())["external_llm_requests"], 2)
        self.assertEqual(len(requests), 2)
        for name, raw in parent_files.items():
            self.assertEqual((path / name).read_bytes(), raw, name)
        repeated = self.cli_resume(path, "--answers", str(answers), "--revised-problem", str(revision))
        self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["run_id"], child.name)
        self.assertEqual(len(requests), 2)

    def test_derivation_intent_crash_finishes_the_same_child_without_extra_generation(self) -> None:
        self.crash_derivation = True
        self.test_new_rule_creates_a_derived_revision_and_preserves_parent_public_history()

    def test_explicit_rerun_of_waiting_run_creates_a_child_with_carried_usage(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "domain", "kind": "confirm_existing",
            "question": "Confirm the original domain.", "statement_ref": {"kind": "requirement", "id": "R-DOMAIN"}}]}}
        path, bundle, requests = self.run_responses([question, self.compact])
        parent_bytes = (path / "bundle.json").read_bytes()
        rerun = self.cli_resume(path, "--strategy", "rerun")
        self.assertEqual(rerun.returncode, 0, rerun.stdout + rerun.stderr)
        child = Path(json.loads(rerun.stdout)["bundle_path"])
        self.assertNotEqual(child, path)
        self.assertEqual(json.loads((child / "lineage.json").read_text())["operation"], "derived_rerun")
        self.assertEqual(json.loads((child / "budget-ledger.json").read_text())["external_llm_requests"], 2)
        self.assertEqual((path / "bundle.json").read_bytes(), parent_bytes)
        self.assertEqual(len(requests), 2)

    def test_invalid_answers_and_disguised_new_information_reject_before_work(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "domain", "kind": "confirm_existing",
            "question": "Confirm the original domain.", "statement_ref": {"kind": "requirement", "id": "R-DOMAIN"}}]}}
        path, bundle, requests = self.run_responses([question])
        request = json.loads((path / bundle["clarification_request_ref"]["relative_path"]).read_text())
        original = (path / "budget-ledger.json").read_bytes()
        valid = {"schema_version": "0.1.0", "request_id": request["request_id"], "action": "confirm",
            "answers": [{"question_id": "domain", "value": True}]}
        cases = []
        wrong = deepcopy(valid); wrong["request_id"] = "other"; cases.append((wrong, "invalid_clarification_response"))
        duplicate = deepcopy(valid); duplicate["answers"] *= 2; cases.append((duplicate, "invalid_clarification_response"))
        missing = deepcopy(valid); missing["answers"] = []; cases.append((missing, "invalid_clarification_response"))
        changed = deepcopy(valid); changed["answers"][0]["value"] = "Actually allow continuous quantities."; cases.append((changed, "problem_revision_required"))
        denied = deepcopy(valid); denied["answers"][0]["value"] = False; cases.append((denied, "problem_revision_required"))
        for response, expected in cases:
            with self.subTest(expected=expected, response=response):
                answers = self.root / "answers.json"; answers.write_text(json.dumps(response))
                rejected = self.cli_resume(path, "--answers", str(answers))
                self.assertEqual(rejected.returncode, 1)
                self.assertEqual(json.loads(rejected.stdout)["error"]["code"], expected)
                self.assertEqual((path / "budget-ledger.json").read_bytes(), original)
                self.assertEqual(len(requests), 1)

    def test_undeclared_confirmation_anchor_cannot_claim_existing_information(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "domain", "kind": "confirm_existing",
            "question": "Confirm an invented rule.", "statement_ref": {"kind": "requirement", "id": "INVENTED"}}]}}
        path, bundle, requests = self.run_responses([question])
        self.assertEqual(bundle["status"], "failed")
        self.assertEqual(bundle["error"]["code"], "invalid_clarification")
        self.assertEqual(len(requests), 1)

    def test_published_request_recovers_the_same_identity_without_another_http_call(self) -> None:
        self.run_arguments = ["--interactive"]
        question = {"clarification": {"questions": [{"question_id": "domain", "kind": "confirm_existing",
            "question": "Confirm the original quantity domain.", "statement_ref": {"kind": "requirement", "id": "R-DOMAIN"}}]}}
        seen = self.root / "seen-request.json"
        script = '''import json, os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    if Path(target).name == "request.json" and "clarifications" in Path(target).parts and "history" not in Path(target).parts:
        Path(SEEN).write_bytes(Path(target).read_bytes())
        os._exit(91)
    return result
os.replace = crash
sys.exit(main())'''.replace("SEEN", repr(str(seen)))
        path, bundle, requests = self.run_responses([question], crash_script=script)
        self.assertEqual(bundle["status"], "needs_input", bundle.get("error"))
        original = json.loads(seen.read_text())
        restored = json.loads((path / bundle["clarification_request_ref"]["relative_path"]).read_text())
        self.assertEqual(restored["request_id"], original["request_id"])
        self.assertEqual(len(requests), 1)
