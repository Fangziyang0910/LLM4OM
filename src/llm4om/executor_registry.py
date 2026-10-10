"""Bind installed execution infrastructure to the existing owned process seams."""

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from llm4om.contracts import RunError
from llm4om.executors import ContainerExecution, run_container, run_owned_process
from llm4om.plugins import Plugin, discover_plugins, resolve_configured_plugin, _quiet, _exception_details


CONTAINER_CONFIG = {'type': 'object', 'properties': {
    'network': {'const': False}, 'cpu_limit': {'type': 'number', 'exclusiveMinimum': 0},
    'memory_limit_mb': {'type': 'integer', 'minimum': 1},
    'wall_time_s': {'type': 'number', 'exclusiveMinimum': 0},
    'image': {'type': 'string', 'minLength': 1}, 'output_limit_bytes': {'type': 'integer', 'minimum': 1},
    'pids_limit': {'type': 'integer', 'minimum': 1}},
    'required': ['network', 'cpu_limit', 'memory_limit_mb', 'wall_time_s'], 'additionalProperties': False}


class ContainerExecutorFactory:
    mode = 'container'
    profile = 'container_process/0.1.0'
    runner: Callable[..., Any] = staticmethod(run_container)

    def describe(self) -> dict[str, Any]:
        return {'schema_version': '0.2.0', 'plugin_id': 'llm4om.executors.' + self.mode, 'kind': 'executor',
            'plugin_version': '0.1.0', 'contract_range': '>=0.2.0,<0.3.0', 'display_name': self.mode,
            'description': 'Owned Worker execution with explicit public inputs and bounded cleanup.',
            'capabilities': {'problem_types': ['lp', 'milp'], 'input_artifact_kinds': ['worker_request'],
                'output_artifact_kinds': ['execution_result'], 'executor_profile': self.profile,
                'execution_modes': [self.mode]},
            'config_schema': deepcopy(CONTAINER_CONFIG) if self.mode == 'container' else {'type': 'object', 'additionalProperties': False},
            'dependencies': {'python': []}, 'source': None}

    def create(self, config: dict[str, Any]) -> Callable[..., Any]:
        return self.runner


class TrustedLocalExecutorFactory(ContainerExecutorFactory):
    mode = 'trusted_local'
    profile = 'owned_process/0.1.0'
    runner = staticmethod(run_owned_process)


@dataclass(frozen=True)
class ResolvedExecutor:
    instance: Callable[..., Any]
    mode: str
    binding: dict[str, Any]

    def run(self, *arguments: Any, **options: Any) -> Any:
        try:
            with _quiet():
                result = self.instance(*arguments, **options)
        except RunError:
            raise
        except (Exception, SystemExit) as error:
            raise RunError('executor_plugin_error', 'execution', 'The declared Executor failed.',
                           details=_exception_details(error)) from error
        if self.mode == 'container':
            valid = isinstance(result, ContainerExecution)
        else:
            valid = (isinstance(result, tuple) and len(result) == 3 and isinstance(result[0], bytes)
                     and isinstance(result[1], bytes) and type(result[2]) is int)
        if not valid:
            raise RunError('executor_protocol_error', 'execution', 'Executor result does not match its declared process profile.')
        return result


def resolve_executor(selection: dict[str, Any], *, inventory: dict[tuple[str, str], Plugin] | None = None,
                     expected: dict[str, Any] | None = None) -> ResolvedExecutor:
    instance, binding = resolve_configured_plugin('executor', selection,
        inventory=discover_plugins() if inventory is None else inventory, expected=expected)
    if not callable(instance):
        raise RunError('invalid_plugin_manifest', 'admission', 'Executor factory must provide its declared process callable.')
    mode = binding['manifest']['capabilities']['execution_modes'][0]
    return ResolvedExecutor(instance, mode, binding)
