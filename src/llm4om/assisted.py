"""Explicit human revisions, using the same proposal, execution and lineage contracts."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:
    from llm4om.application import RunResult

from llm4om.contracts import RunError, parse_json, read_public_bytes, validate_problem, validate_config
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome, ModelProposal, FactoryCodeProposal, ScriptCodeProposal
from llm4om.storage import RunStore
from llm4om.store_registry import open_run_store, saved_store_selection
from llm4om.control import CancellationToken

KINDS = ('lp_ir', 'python_factory', 'native_code', 'native_script')


def _atomic_write(path: Path, content: bytes) -> None:
    # Derived-run inputs are read back by hash; an interrupted write must not leave truncated bytes.
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(content)
    os.replace(temporary, path)


class AssistedMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = deepcopy(config)

    async def run(self, problem: dict[str, Any], context: MethodContext, *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        context.cancellation.check()
        edits = self.config['edits']
        original = deepcopy(edits['problem'])
        if len(original['data_refs']) != len(problem['data_refs']):
            raise RunError('artifact_problem_mismatch', 'formulation', 'Human edits are bound to one original public problem.')
        for before, after in zip(original['data_refs'], problem['data_refs']):
            before['path'] = after['path']
        if original != problem:
            raise RunError('artifact_problem_mismatch', 'formulation', 'Human edits are bound to one original public problem.')
        bindings = [{'data_id': ref['data_id'], 'sha256': ref['sha256']} for ref in problem['data_refs']]
        provenance = {'origin': 'user_edited', 'assisted': True, 'operation': edits['operation'], 'reason': edits['reason']}
        formulation = deepcopy(edits['formulation'])
        if formulation is not None:
            formulation.update(problem_id=problem['problem_id'], problem_revision=problem['revision'],
                               data_bindings=bindings, structured_ir_ref=None, provenance=provenance)
        ir = deepcopy(edits['structured_ir']) if self.config['code_kind'] == 'lp_ir' else None
        code: FactoryCodeProposal | ScriptCodeProposal | None = None
        execution_id = None
        if ir is not None:
            ir.update(problem_id=problem['problem_id'], problem_revision=problem['revision'], data_bindings=bindings)
        else:
            material = edits['code']
            source = material['source']
            digest = hashlib.sha256(source.encode()).hexdigest()
            if self.config['code_kind'] == 'native_script':
                data = json.dumps(material['data_json'], ensure_ascii=False, allow_nan=False).encode()
                code = ScriptCodeProposal(source, digest, bindings, data)
                execution_id = 'assisted-script-001'
                if context.save_checkpoint is not None:
                    context.save_checkpoint({'schema_version': '0.1.0', 'execution_id': execution_id})
                if context.resources is None:
                    raise RunError('capability_mismatch', 'execution', 'Script editing requires the admitted execution resource.')
                await context.resources.execute(execution_id, code)
            else:
                code = FactoryCodeProposal(source, digest, bindings, representation_kind=self.config['code_kind'])
        artifact = {'schema_version': '0.2.0', 'artifact_id': 'assisted-model-001',
            'problem_ref': {'sha256': context.problem_sha256}, 'formulation_ref': {} if formulation is not None else None,
            'code_ref': None, 'data_bindings': bindings, 'assumptions': deepcopy(edits['model_metadata']['assumptions']),
            'requirement_traces': deepcopy(edits['model_metadata']['requirement_traces']), 'diagnostics': [],
            'warnings': [*edits['model_metadata']['warnings'], 'Human-assisted result; do not rank as an autonomous method run.'], 'optional_views': [],
            'provenance': provenance, 'stage_status': {'formulation': {'status': 'available' if formulation is not None else 'not_available',
            'reason': None if formulation is not None else 'The source method supplied no Formulation.'},
            'code': {'status': 'pending', 'reason': 'Validate or compile the supplied public revision.'}}}
        return MethodOutcome('selected', '001', ModelProposal(artifact, formulation, ir, code, execution_id))


class AssistedFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id='llm4om.methods.assisted', plugin_version='0.1.0', display_name='Human-assisted revision',
                        description='Explicit public Formulation/Code edits; no model request; reuse common validation and execution.')
        manifest['config_schema'] = {'type': 'object', 'additionalProperties': False, 'required': ['code_kind', 'formulation_kind', 'edits'],
            'properties': {'code_kind': {'enum': list(KINDS)}, 'formulation_kind': {'enum': ['five_element', 'native_formulation', 'not_available']},
                           'edits': {'type': 'object'}}}
        manifest['capabilities']['human_assisted'] = True
        return manifest

    def resolve_capabilities(self, config: dict[str, Any]) -> dict[str, Any]:
        capabilities: dict[str, Any] = self.describe()['capabilities']
        kind = config['code_kind']
        if kind != 'lp_ir':
            capabilities.update(execution_modes=['container'], method_profile='factory_single/0.2.0')
        if kind in ('native_code', 'native_script'):
            capabilities.update(model_backends=['llm4om.model_backends.gurobipy'], solvers=['llm4om.solvers.gurobi'],
                                code_representations=[kind], method_profile='native_single/0.2.0')
        if kind == 'native_script':
            native_formulation = config['formulation_kind'] == 'native_formulation'
            capabilities.update(method_profile='native_script/0.1.0' if native_formulation else 'native_script/0.2.0',
                                formulation_representations=['native_formulation'] if native_formulation else [])
        return capabilities

    def create(self, config: dict[str, Any]) -> AssistedMethod:
        return AssistedMethod(config)


def _config(store: RunStore) -> dict[str, Any]:
    # Config values can contain source-reference literals; RunStore already validates the file bytes.
    ref = store.projections['requested-config.json']
    return parse_json(read_public_bytes(store.path / ref['relative_path']))


def _template(store: RunStore, operation: str) -> dict[str, Any]:
    from llm4om.run_records import load_run_record
    if operation not in ('problem', 'formulation', 'code'):
        raise RunError('invalid_edit', 'admission', 'Choose problem, formulation or code editing.')
    problem_ref = store.projections.get('public-problem.json')
    if problem_ref is None:
        raise RunError('edit_unavailable', 'admission', 'The parent has no saved public problem.')
    problem = load_run_record(store, problem_ref)
    config = _config(store)
    artifact = load_run_record(store, store.state['artifact_ref']) if store.state.get('artifact_ref') else None
    formulation = ir = code = None
    if operation != 'problem':
        if artifact is None:
            raise RunError('edit_unavailable', 'admission', 'The parent has no saved modeling output.')
        if artifact.get('formulation_ref'):
            formulation = load_run_record(store, artifact['formulation_ref'])
            if formulation.get('structured_ir_ref'):
                ir = load_run_record(store, formulation['structured_ir_ref'])
        if artifact.get('code_ref'):
            saved = load_run_record(store, artifact['code_ref'])
            source_ref = saved['representation_ref']
            source = read_public_bytes(store.path / source_ref['relative_path'], max_bytes=8 * 1024 * 1024).decode()
            if operation == 'code' and saved['provenance']['origin'] == 'deterministic_compilation':
                symbols = load_run_record(store, saved['provenance']['symbol_map_ref'])['variables']
                # Compiled factories return ConcreteModel; explicit edit source exposes the transport adapter.
                source += ('\n# Assisted template: preserve the saved symbol map and return the common ModelHandle.\n'
                    'from llm4om.backends import ModelHandle\n_assisted_build = build_model\n'
                    'def build_model(data):\n    model = _assisted_build(data)\n'
                    f'    symbols = {symbols!r}\n'
                    '    return ModelHandle(model, {name: model.variables[index] for name, index in symbols.items()})\n')
            code = {'representation_kind': saved['representation_kind'], 'source': source,
                    'data_json': load_run_record(store, saved['data_json_ref']) if saved.get('data_json_ref') else None}
        if operation == 'code' and code is None:
            raise RunError('edit_unavailable', 'admission', 'The parent has no saved executable code.')
    return {'schema_version': '0.1.0', 'operation': operation, 'reason': '', 'budget': config['budget'],
            'model_metadata': {field: deepcopy((artifact or {}).get(field, [])) for field in ('assumptions', 'requirement_traces', 'warnings')},
            'problem': problem, 'formulation': formulation, 'structured_ir': ir, 'code': code}


def export_edit(run: Path, *, operation: str = 'code') -> dict[str, Any]:
    """Produce a public editing document, without changing the parent artifacts."""
    store = open_run_store(saved_store_selection(run), run.parent, resume=run)
    try:
        if store.state.get('status') not in {'completed', 'artifact_ready', 'failed', 'cancelled', 'unresolved', 'needs_input'}:
            raise RunError('run_active', 'admission', 'Edit a saved inactive run.')
        return _template(store, operation)
    finally:
        store.close()


def edit_run(run: Path, edits: Path, *, cancellation: CancellationToken | None = None) -> 'RunResult':
    """Create a new assisted revision, preserving parent bytes and paid/unknown usage."""
    from llm4om.run_records import load_run_record
    from llm4om.application import _initialize_derived_run
    from llm4om.gateway import Gateway
    value = parse_json(read_public_bytes(edits, max_bytes=24 * 1024 * 1024))
    store = open_run_store(saved_store_selection(run), run.parent, resume=run)
    child = None
    try:
        if not isinstance(value.get('operation'), str):
            raise RunError('invalid_edit', 'admission', 'Declare the editing operation.')
        expected = _template(store, value['operation'])
        if set(value) != set(expected) or value['schema_version'] != '0.1.0' or not isinstance(value['reason'], str) or not 1 <= len(value['reason'].strip()) <= 4096:
            raise RunError('invalid_edit', 'admission', 'Use a versioned public edit document with an explicit change reason.')
        if store.state.get('status') not in {'completed', 'artifact_ready', 'failed', 'cancelled', 'unresolved', 'needs_input'}:
            raise RunError('run_active', 'admission', 'Edit a saved inactive run.')
        public = value['problem']
        validate_problem(public)
        if public['problem_id'] != expected['problem']['problem_id']:
            raise RunError('invalid_edit', 'admission', 'A revision must retain its public problem identity.')
        # Ref order is presentation only; normalize by data_id so reorderings compare as the same data.
        expected_refs = expected['problem']['data_refs']
        ref_order = {ref['data_id']: index for index, ref in enumerate(expected_refs)}
        if len(ref_order) != len(public['data_refs']) or {ref['data_id'] for ref in public['data_refs']} != set(ref_order):
            raise RunError('invalid_edit', 'admission', 'This edit retains exact original data; import changed data as a new problem.')
        public['data_refs'].sort(key=lambda ref: ref_order[ref['data_id']])
        if public['data_refs'] != expected_refs:
            raise RunError('invalid_edit', 'admission', 'This edit retains exact original data; import changed data as a new problem.')
        operation = value['operation']
        if operation == 'problem':
            if public['revision'] == expected['problem']['revision'] or any(value[field] is not None for field in ('formulation', 'structured_ir', 'code')):
                raise RunError('invalid_edit', 'admission', 'Change the problem revision and regenerate its modeling output.')
        elif public != expected['problem']:
            raise RunError('invalid_edit', 'admission', 'Formulation/Code edits retain the original public problem; choose a problem revision to change it.')
        if operation == 'code' and (value['formulation'] != expected['formulation'] or value['structured_ir'] != expected['structured_ir'] or value['model_metadata'] != expected['model_metadata']):
            raise RunError('invalid_edit', 'admission', 'Code-only editing retains the source Formulation and IR.')
        settings = _config(store)
        settings['budget'] = value['budget']
        resource_records = []
        if 'gateway_sha256' in store.state:
            resource = Gateway.recover(store.path.parent / '.private' / store.run_id, expected_sha256=store.state['gateway_sha256'],
                budget=_config(store)['budget'], deadline=store.state['deadline'],
                inherited_ledger=store.state.get('inherited_ledger', {}))
            store.state['ledger'].update(resource.ledger)
            resource_records = resource.trace
        if operation != 'problem':
            kind = 'lp_ir' if operation == 'formulation' and value['structured_ir'] is not None else value['code']['representation_kind']
            if kind not in KINDS:
                raise RunError('invalid_edit', 'admission', 'Unsupported edited Code representation.')
            if kind != 'lp_ir':
                material = value['code']
                if set(material) != {'representation_kind', 'source', 'data_json'} or not isinstance(material['source'], str):
                    raise RunError('invalid_edit', 'admission', 'Edited Code needs explicit source and its original representation.')
                if kind == 'native_script' and material['data_json'] != expected['code']['data_json']:
                    raise RunError('invalid_edit', 'admission', 'Code-only script editing retains exact public data.json.')
            if store.state.get('admission', {}).get('mode') != 'container':
                declared = value['budget'].get('wall_time_s') if isinstance(value['budget'], dict) else None
                if type(declared) is not int or declared < 1:
                    declared = 60
                settings['executor'] = {'plugin_id': 'llm4om.executors.container', 'config':
                    {'network': False, 'cpu_limit': 1, 'memory_limit_mb': 1024, 'wall_time_s': declared}}
            settings['method'] = {'plugin_id': 'llm4om.methods.assisted', 'config': {'code_kind': kind,
                'formulation_kind': value['formulation']['representation_kind'] if value['formulation'] else 'not_available', 'edits': value}}
            settings['llm'] = {'provider_plugin_id': 'llm4om.providers.mock', 'model': 'no-llm-human-edit', 'config': {'response_artifact': 'edits.json'}}
        validate_config(settings)
        if 'candidates' in store.state['ledger']:
            raise RunError('checkpoint_incompatible', 'admission', 'Runs saved before the modeling-process layout (ADR-0006) are read-only.')
        if settings['budget']['max_checks'] <= store.state['ledger']['checks']:
            raise RunError('budget_exhausted', 'admission', 'The revised budget must cover the inherited public checks and this new check.')
        child = open_run_store(saved_store_selection(store.path), store.path.parent, cancellation=cancellation)
        inputs = child.path / 'input'
        inputs.mkdir()
        revised = deepcopy(public)
        for index, ref in enumerate(revised['data_refs']):
            name = f'data/{index}.{ref["format"]}'
            target = inputs / name
            target.parent.mkdir(exist_ok=True)
            _atomic_write(target, read_public_bytes(store.path / ref['path'], max_bytes=8 * 1024 * 1024))
            ref['path'] = name
        for name, content in (('problem.json', revised), ('config.json', settings), ('edits.json', value)):
            _atomic_write(inputs / name, (json.dumps(content, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
        if operation == 'problem' and 'response_artifact' in settings['llm']['config']:
            raise RunError('invalid_edit', 'admission', 'Problem changes need a real Provider or a newly input-bound Mock packet.')
        return _initialize_derived_run(child, store, resource_records, problem=inputs / 'problem.json',
            config=inputs / 'config.json', edit={'operation': operation, 'reason': value['reason'], 'assisted': True,
                'parent_sdk': store.state.get('sdk'), 'budget_changed': value['budget'] != expected['budget']})
    finally:
        if child is not None:
            child.close()
        store.close()
