"""An independently installed run store that records opens and delegates to the filesystem contract."""

import json
from pathlib import Path
from typing import Any, Callable

from llm4om.storage import RunStore


class FixtureFactory:
    def describe(self) -> dict[str, Any]:
        return {'schema_version': '0.2.0', 'plugin_id': 'llm4om.examples.receipt_store', 'kind': 'artifact_store',
            'plugin_version': '0.1.0', 'contract_range': '>=0.2.0,<0.3.0', 'display_name': 'Receipt store',
            'description': 'Record every opened run, then persist it through the standard filesystem contract.',
            'capabilities': {'problem_types': ['lp', 'milp'], 'input_artifact_kinds': ['store_bytes'],
                'output_artifact_kinds': ['artifact_ref'], 'store_profile': 'run_store/0.1.0'},
            'config_schema': {'type': 'object', 'additionalProperties': False, 'properties': {
                'receipt_path': {'type': 'string', 'minLength': 1}}, 'required': ['receipt_path']},
            'dependencies': {'python': []}, 'source': None}

    def create(self, config: dict[str, Any]) -> Callable[..., Any]:
        def opener(root: Path, *, resume: Path | None = None, cancellation: Any = None,
                   versioned: bool = True) -> RunStore:
            record = {'root': str(root), 'resume': str(resume) if resume is not None else None,
                      'versioned': versioned}
            with Path(config['receipt_path']).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
            return RunStore(root, resume=resume, cancellation=cancellation, versioned=versioned)
        return opener


plugin = FixtureFactory()
