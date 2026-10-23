"""Every method graph, with scripted LLM replies, must assemble and execute all nine native libraries."""

import json
from typing import Any

import pytest

from llm4om.languages import LANGUAGES, CodeTarget
from llm4om.methods import methods
from llm4om.model_code import ModelCode
from tests.conftest import ACCEPT_REVIEW, FORMULATION
from tests.test_methods import (
    FIVE_ELEMENT,
    JUDGED,
    ORTHOUGHT_REPLY,
    PASS_FORMULATION,
    autoformulation_script,
    by_role,
    optimus_script,
    trival_script,
)
from tests.test_new_methods import sac_reply


def method_script(method: str, library: str) -> Any:
    native = ModelCode(CodeTarget(library))
    variables = native.variables('x', ['range(2)'], 'INTEGER', '0', '8')
    objective = native.objective('3*x[0]+2*x[1]', 'max')
    constraints = [native.constraint('2*x[0]+x[1]<=8'), native.constraint('x[0]+2*x[1]<=8')]
    source = native.assemble([variables, *constraints, objective])
    block = f'```python\n{source}```'
    reply = f'{FORMULATION}\n{block}'
    if method == 'optimus':
        return optimus_script(library)
    if method == 'autoformulation':
        base = autoformulation_script('INTEGER', [])
        return lambda role, messages, tools: (
            "formalization_dict['inequality_constraints'] = {'cutting': '2*x[0]+x[1]<=cap', 'machining': 'x[0]+2*x[1]<=cap'}"
            if role == 'generate.inequality_constraints' else base(role, messages, tools))
    if method == 'trival':
        return trival_script([{'code_validation_passed': True, 'code_validation_feedback': 'faithful'}],
                             [PASS_FORMULATION], source)
    if method == 'sac_opt':
        pieces = {'setup': variables, 'objective': {'formulation': FORMULATION, 'code': objective},
                  'constraints': [{'formulation': FORMULATION, 'code': item} for item in constraints]}
        return lambda role, *_: json.dumps(
            pieces if role == 'sac_generate' else {'items': ['cutting <= 8', 'machining <= 8']}
            if role == 'sac_backtranslate' else {'items': [{'equivalent': True, 'reason': 'matches'}] * 2}
            if role == 'sac_compare' else sac_reply(role))
    replies = {
        'direct': {'generate': reply},
        'feedback_repair': {'generate': reply, 'review': ACCEPT_REVIEW},
        'coe': {'conductor': ['Modeling Expert', 'Programming Expert', 'Code Reviewer'],
                'Modeling Expert': FORMULATION, 'Programming Expert': block, 'Code Reviewer': 'Looks fine.', 'reducer': block},
        'optitree': {'interpreter': '{"matching_problem_type":"", "belongs_to_problem_types":false}', 'reasoner': reply},
        'or_llm_agent': {'math_model': FORMULATION, 'code': block},
        'orthought': {'model': ORTHOUGHT_REPLY.split('```python')[0] + block},
        'llmopt': {'five_element': FIVE_ELEMENT, 'code': block, 'self_correction': JUDGED.format(five='True', code='True')},
        'bind': {'bind_generate': reply},
        'optimind': {'optimind_classify': '[]', 'optimind_generate': [reply, '#### The final model correctly solves the problem.']},
    }
    return by_role(replies[method])


@pytest.mark.parametrize('method', list(methods()))
@pytest.mark.parametrize('library', list(LANGUAGES))
def test_every_method_can_use_every_modeling_library(run_method: Any, preset: Any, method: str, library: str) -> None:
    preset('AUTOFORMULATION', n_used_gpt=1, n_top=1, n_reward=1, total_rollouts=1)
    record = run_method(method, method_script(method, library), language=library)
    assert not record.get('failure'), record.get('failure')
    assert record['solve']['objective'] == pytest.approx(13), record['solve']
    assert record['spec']['language'] == library
    assert record['formulation'] and record['code']
    assert {'llm', 'artifact', 'solve'} <= {step['type'] for step in record['steps']}
    assert all(abs(value - round(value)) < 1e-5 for value in record['solve']['variables'].values())
