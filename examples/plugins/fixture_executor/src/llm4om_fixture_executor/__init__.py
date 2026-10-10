"""Record real process invocations outside the core and delegate owned execution."""

import json
from pathlib import Path
from typing import Any, Callable

from llm4om.executor_registry import ContainerExecutorFactory, TrustedLocalExecutorFactory
from llm4om.executors import run_container, run_owned_process


def record(path: Path, command: list[str]) -> None:
    with path.open('a') as stream:
        stream.write(json.dumps({'command': command}) + '\n')
    print('Fixture Executor host output must not enter CLI JSON.')


class ContainerFactory(ContainerExecutorFactory):
    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(plugin_id='llm4om.fixtures.container_executor', display_name='Recorded container Executor')
        manifest['config_schema']['properties']['receipt_path'] = {'type': 'string', 'minLength': 1}
        manifest['config_schema']['required'].append('receipt_path')
        return manifest

    def create(self, config: dict[str, Any]) -> Callable[..., Any]:
        path = Path(config['receipt_path'])

        def run(command, inputs, limits, **options):
            record(path, command)
            return run_container(command, inputs, {key: value for key, value in limits.items() if key != 'receipt_path'}, **options)

        return run


class LocalFactory(TrustedLocalExecutorFactory):
    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(plugin_id='llm4om.fixtures.local_executor', display_name='Recorded local Executor')
        manifest['config_schema'] = {'type': 'object', 'properties': {'receipt_path': {'type': 'string', 'minLength': 1}},
            'required': ['receipt_path'], 'additionalProperties': False}
        return manifest

    def create(self, config: dict[str, Any]) -> Callable[..., Any]:
        path = Path(config['receipt_path'])

        def run(command, payload, **options):
            record(path, command)
            return run_owned_process(command, payload, **options)

        return run


container_plugin = ContainerFactory()
local_plugin = LocalFactory()
