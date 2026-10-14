"""OptiMUS uses ordinary public input and the configured isolated Solver."""

import json
from llm4om import resume_run
from test_research_method_runs import CODE, RunHarness, method_replies


class OptimusRunTests(RunHarness):
    def test_existing_inline_alias_runs_on_ortools_and_completed_resume_adds_no_work(self):
        path, _, requests = self.run_case("optimus_inline", solver="ortools")
        self.assertEqual(resume_run(path).status,"completed")
        self.assertEqual(len(requests),7)

    def test_code_error_repairs_using_highs_without_repeating_mathematical_stages(self):
        replies = method_replies("optimus", "raise ValueError('invalid factory')") + [CODE]
        path, _, requests = self.run_case("optimus", replies, solver="highs")
        ledger = json.loads((path/"budget-ledger.json").read_text())
        self.assertEqual((ledger["solver_calls"],ledger["repairs"]),(2,1))
        self.assertEqual(len(requests),8)

    def test_requested_rag_fails_before_http(self):
        _, bundle, _ = self.run_case("optimus", method_config={"rag_mode":"problem_labels"},
            expected="failed",expected_calls=0)
        self.assertEqual(bundle["error"]["code"],"rag_resources_unavailable")

    def test_repair_budget_stops_before_an_unexecutable_extra_model_call(self):
        replies = method_replies("optimus", "raise ValueError('public failure')")
        _, bundle, _ = self.run_case("optimus", replies, budget={"max_solver_calls":1},expected="failed")
        self.assertEqual(bundle["error"]["code"],"budget_exhausted")

    def test_optional_old_public_declarations_remain_input_data(self):
        data={"params":b'{"capacity":{"value":8,"shape":[],"definition":"resource capacity"}}', "labels":b'{}'}
        path, _, requests = self.run_case("optimus",data=data,
            method_config={"params_data_id":"params","labels_data_id":"labels"})
        self.assertIn("declared_parameters",json.dumps(requests[0]))
        state=json.loads((path/"method/state_1_params.json").read_text())
        self.assertEqual(state["parameters"]["capacity"]["value"],8)
