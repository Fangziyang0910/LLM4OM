"""Bind installed run stores to the existing run persistence seam."""

from dataclasses import dataclass
from typing import Any, Callable

from llm4om.contracts import RunError, parse_json, read_public_bytes
from llm4om.plugins import Plugin, discover_plugins, resolve_configured_plugin
from pathlib import Path

FILESYSTEM_CONFIG = {'type': 'object', 'properties': {
    'root': {'type': 'string', 'minLength': 1}},
    'required': ['root'], 'additionalProperties': False}

DEFAULT_SELECTION = {'plugin_id': 'llm4om.stores.filesystem', 'config': {'root': 'runs'}}


class FilesystemStoreFactory:
    profile = 'run_store/0.1.0'

    def describe(self) -> dict[str, Any]:
        return {'schema_version': '0.2.0', 'plugin_id': 'llm4om.stores.filesystem', 'kind': 'artifact_store',
            'plugin_version': '0.1.0', 'contract_range': '>=0.2.0,<0.3.0', 'display_name': 'filesystem',
            'description': 'Local run directories with immutable content-addressed history and verified checkpoints.',
            'capabilities': {'problem_types': ['lp', 'milp'], 'input_artifact_kinds': ['store_bytes'],
                'output_artifact_kinds': ['artifact_ref'], 'store_profile': self.profile},
            'config_schema': dict(FILESYSTEM_CONFIG), 'dependencies': {'python': []}, 'source': None}

    def create(self, config: dict[str, Any]) -> Callable[..., Any]:
        from llm4om.storage import RunStore
        return RunStore


@dataclass(frozen=True)
class ResolvedStore:
    opener: Callable[..., Any]
    binding: dict[str, Any]

    def open(self, root: Path, *, resume: Path | None = None, cancellation: Any = None,
             versioned: bool = True) -> Any:
        try:
            store = self.opener(root, resume=resume, cancellation=cancellation, versioned=versioned)
        except (RunError, OSError):
            raise
        except (Exception, SystemExit) as error:
            from llm4om.plugins import _exception_details
            raise RunError('store_plugin_error', 'storage', 'The declared ArtifactStore failed to open a run.',
                           details=_exception_details(error)) from error
        for name in ('run_id', 'path', 'refs', 'events', 'state', 'projections', 'identity', 'cancellation',
                     'write', 'json', 'emit', 'checkpoint', 'close', 'accept_publications'):
            if not hasattr(store, name):
                raise RunError('store_protocol_error', 'storage',
                               'ArtifactStore result does not match the run_store/0.1.0 profile.',
                               details={'missing': name})
        return store


def resolve_store(selection: dict[str, Any], *, inventory: dict[tuple[str, str], Plugin] | None = None,
                  expected: dict[str, Any] | None = None) -> ResolvedStore:
    opener, binding = resolve_configured_plugin('artifact_store', selection,
        inventory=discover_plugins() if inventory is None else inventory, expected=expected)
    if not callable(opener):
        raise RunError('invalid_plugin_manifest', 'admission', 'Store factory must provide its declared opener.')
    if binding['manifest']['capabilities'].get('store_profile') != 'run_store/0.1.0':
        raise RunError('invalid_plugin_manifest', 'admission', 'Unsupported ArtifactStore profile.')
    return ResolvedStore(opener, binding)


def open_run_store(selection: dict[str, Any], root: Path, *, resume: Path | None = None,
                   cancellation: Any = None, versioned: bool = True) -> Any:
    """Open a run through the configured store plugin and verify the run_store profile."""
    return resolve_store(selection).open(root, resume=resume, cancellation=cancellation, versioned=versioned)


def saved_store_selection(run: Path) -> dict[str, Any]:
    """Reconstruct the store selection recorded by the run that owns this directory."""
    # Read errors fall back to the builtin selection; opening that store then fails its own
    # checkpoint verification, so the underlying cause still surfaces at the run boundary.
    try:
        state = parse_json(read_public_bytes(run / 'checkpoint.json'))['payload']['state']
        binding = state.get('admission', {}).get('store')
        if binding:
            return {'plugin_id': binding['manifest']['plugin_id'], 'config': binding['config']}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return dict(DEFAULT_SELECTION)
