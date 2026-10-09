"""Independent original-problem checks through the public SolutionChecker seam."""

import json
from pathlib import Path
import unittest


class SolutionCheckerTests(unittest.TestCase):
    def test_original_production_rules_and_objective_ignore_candidate_reported_objective(self):
        from llm4om.checkers import ProductionChecker
        root = Path(__file__).parents[1] / 'examples/specs'
        public = json.loads((root / 'problem.json').read_text())
        data = {ref['data_id']: (root / ref['path']).read_bytes() for ref in public['data_refs']}
        checker = ProductionChecker()
        correct = checker.check(public, data, {'A': 3.0, 'B': 2.0})
        self.assertEqual(correct['independent_feasibility']['status'], 'pass')
        self.assertEqual(correct['original_objective'], 13)
        swapped = checker.check(public, data, {'A': 2.0, 'B': 3.0})
        self.assertEqual(swapped['independent_feasibility']['status'], 'pass')
        self.assertEqual(swapped['original_objective'], 12)
        relaxed = checker.check(public, data, {'A': 8/3, 'B': 8/3})
        self.assertEqual(relaxed['independent_feasibility']['status'], 'fail')
        self.assertIn('integer_domain', relaxed['independent_feasibility']['violations'])
        omitted = checker.check(public, data, {'A': 0, 'B': 8})
        self.assertEqual(omitted['independent_feasibility']['status'], 'fail')
        self.assertIn('capacity:finishing', omitted['independent_feasibility']['violations'])
        self.assertEqual(omitted['original_objective'], 16)

    def test_distinct_optimal_vectors_are_accepted_in_constant_objective_profile(self):
        from llm4om import UnitCapChecker
        public = {'source': {'profile': 'integer_unit_interval_constant_zero'}}
        for quantity in (0, 1):
            result = UnitCapChecker().check(public, {}, {'Q': quantity})
            self.assertEqual(result['independent_feasibility']['status'], 'pass')
            self.assertEqual(result['original_objective'], 0)
        self.assertEqual(UnitCapChecker().check(public, {}, {'Q': 2})['independent_feasibility']['status'], 'fail')
