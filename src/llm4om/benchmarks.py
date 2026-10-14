"""Bundled public benchmark examples for browsing and single-problem modeling."""

import base64
from copy import deepcopy
import hashlib
from importlib.resources import files
from typing import Any

from llm4om.contracts import RunError, parse_json, validate_data, validate_problem


def list_benchmarks() -> list[dict[str, Any]]:
    catalog = parse_json(files('llm4om').joinpath('benchmark_sources/catalog.json').read_bytes())
    return [{key: value for key, value in item.items() if key not in {'cases_file', 'sha256', 'size_bytes', 'sources'}}
        for item in catalog['benchmarks']]


def modeling_input(case: dict[str, Any], header: dict[str, Any]) -> dict[str, Any]:
    data = deepcopy(case['data'])
    refs = []
    for index, item in enumerate(data):
        raw = base64.b64decode(item['base64'], validate=True)
        ref = {'data_id': item['data_id'], 'path': f"data/{index}.{item['format']}", 'format': item['format'],
            'sha256': hashlib.sha256(raw).hexdigest(), 'schema': item['schema']}
        validate_data(raw, ref)
        refs.append(ref)
    problem = {'schema_version': '0.3.0', 'problem_id': case['case_id'], 'revision': '1',
        'description': case['description'], 'language': 'en', 'problem_type_hint': 'unknown',
        'requirements': [], 'assumptions': [], 'data_refs': refs,
        'source': {'kind': 'builtin_benchmark', 'dataset_id': header['dataset_id'], 'subset': case['subset'],
            'sample_id': case['sample_id'], 'source_version': header['source_version'], 'source_url': header['source_url']}}
    validate_problem(problem)
    return {'title': header['title'] + ' · ' + case['sample_id'], 'problem': problem, 'data': data}


def benchmark_detail(task_id: str, offset: int, limit: int) -> dict[str, Any]:
    root = files('llm4om').joinpath('benchmark_sources')
    catalog = parse_json(root.joinpath('catalog.json').read_bytes())
    header = next((item for item in catalog['benchmarks'] if item['task_id'] == task_id), None)
    if header is None:
        raise RunError('not_found', 'web', 'This built-in benchmark is not available.')
    public_header = next(item for item in list_benchmarks() if item['task_id'] == task_id)
    if header['cases_file'] != header['dataset_id'] + '.json':
        raise RunError('invalid_benchmark', 'web', 'A built-in benchmark has an invalid resource name.')
    raw = root.joinpath(header['cases_file']).read_bytes()
    if len(raw) != header['size_bytes'] or hashlib.sha256(raw).hexdigest() != header['sha256']:
        raise RunError('snapshot_hash_mismatch', 'web', 'The bundled benchmark bytes changed.')
    cases = parse_json(raw)['cases']
    if len(cases) != header['N_cases']:
        raise RunError('invalid_benchmark', 'web', 'The bundled benchmark count changed.')
    selected = []
    for case in cases[offset:offset + limit]:
        draft = modeling_input(case, header)
        copy_text = draft['problem']['description']
        for data in draft['data']:
            copy_text += '\n\n问题数据（' + data['data_id'] + '）：\n' + base64.b64decode(data['base64']).decode('utf-8')
        selected.append({'case_id': case['case_id'], 'sample_id': case['sample_id'], 'subset': case['subset'],
            'problem': draft['problem'], 'input': draft, 'copy_text': copy_text})
    return {'dataset': public_header, 'total': len(cases), 'cases': selected}
