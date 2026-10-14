"""CoE reduction and backward reflection keep trusted configured Solver evidence."""

import json
import subprocess
from llm4om import resume_run
from test_research_method_runs import CODE, MATH, RunHarness, method_replies


class CoERunTests(RunHarness):
    def test_final_formulation_code_and_real_solve_are_saved_together(self):
        path,bundle,requests=self.run_case("coe",solver="ortools")
        self.assertEqual(bundle["stages"]["formulation"]["status"],"available")
        self.assertEqual(resume_run(path).status,"completed")
        self.assertEqual(len(requests),3)
        ledger=json.loads((path/"budget-ledger.json").read_text())
        self.assertEqual(ledger["solver_calls"],1)

    def test_backward_reflection_reaches_corrected_trial_on_highs(self):
        replies=method_replies("coe","raise ValueError('first reducer failure')")+[
            {"is_caused_by_you":True,"reason":"invalid construction","refined_result":"return a ModelHandle with both integer decisions"},
            *method_replies("coe")]
        path,_,requests=self.run_case("coe",replies,solver="highs",method_config={"enable_reflection":True})
        self.assertIn("return a ModelHandle",json.dumps(requests[5]))
        ledger=json.loads((path/"budget-ledger.json").read_text())
        self.assertEqual((ledger["solver_calls"],ledger["repairs"]),(2,1))
        self.assertEqual(json.loads((path/"method/selection.json").read_text())["candidate_id"],"002")

    def test_generated_return_value_cannot_manufacture_a_trusted_solution(self):
        _,bundle,_=self.run_case("coe",method_replies("coe","def build_model(data): return 13"),
            expected="failed")
        self.assertEqual(bundle["error"]["code"],"method_debug_exhausted")
        self.assertIsNone(bundle["solve_result_ref"])

    def test_original_public_contract_is_input_while_code_uses_selected_backend(self):
        data={"contract":b'{"code_example":"def prob_case(capacity): pass","entry_point":"prob_case","input":{"capacity":8}}'}
        _,_,requests=self.run_case("coe",data=data,method_config={"public_contract_data_id":"contract"})
        self.assertIn("public_contract",json.dumps(requests[-1]))
        self.assertIn("build_model(data)",json.dumps(requests[-1]))

    def test_shared_budget_stops_before_further_expert_reflection(self):
        _,bundle,_=self.run_case("coe",method_replies("coe","raise ValueError('public failure')"),expected="failed",
            method_config={"enable_reflection":True},budget={"max_solver_calls":1})
        self.assertEqual(bundle["error"]["code"],"budget_exhausted")

    def test_cancellation_removes_the_owned_factory_container(self):
        source="import time\ndef build_model(data):\n    time.sleep(100)\n"
        path,bundle,_=self.run_case("coe",method_replies("coe",source),expected="cancelled",cancel=True)
        self.assertEqual(bundle["error"]["code"],"run_cancelled")
        execution=json.loads((path/"candidates/001/execution.json").read_text())
        self.assertEqual(execution["status"],"cancelled")
        self.assertTrue(execution["container_id"])
        self.assertNotEqual(subprocess.run(["docker","inspect",execution["container_id"]],capture_output=True).returncode,0)
