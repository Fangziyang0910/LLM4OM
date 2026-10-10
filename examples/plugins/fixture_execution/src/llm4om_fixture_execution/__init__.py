"""Rename constructed components and solve with a separately selected real adapter."""

from typing import Any, Mapping, Iterator
from contextlib import contextmanager
from llm4om.backends import PyomoBackendFactory, PyomoFactoryBackend, GurobiBackendFactory, GurobiFactoryBackend, ModelBackend, ModelHandle
from llm4om.solvers import HighsSolverFactory, HighsSolverBackend, GurobiSolverFactory, GurobiSolverBackend, SolverBackend
from llm4om.linear import CompiledCode
from llm4om.contracts import RunError

SCHEMA = {"type": "object", "properties": {"component": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$"}},
    "required": ["component"], "additionalProperties": False}


class RenamingBackend(PyomoFactoryBackend):
    def __init__(self, component: str) -> None:
        self.component = component

    def load(self, build: str | CompiledCode, data: Mapping[str, bytes]) -> ModelHandle:
        handle = super().load(build, data)
        import pyomo.environ as pyo
        variable = next(handle.model.component_objects(pyo.Var, active=True, descend_into=True), None)
        if variable is not None:
            parent = variable.parent_block()
            parent.del_component(variable)
            parent.add_component(self.component, variable)
        return handle


class CheckingHighsSolver(HighsSolverBackend):
    def __init__(self, component: str) -> None:
        self.component = component

    def solve(self, handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
        if handle.model.component(self.component) is None:
            raise RunError("invalid_model_handle", "solve", "The selected Backend's constructed component is missing.")
        result = super().solve(handle, options)
        result["effective_options"]["fixture_component"] = self.component
        return result


class BackendFactory(PyomoBackendFactory):
    plugin_id = "llm4om.examples.renaming_pyomo"

    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(config_schema=SCHEMA, source={"kind": "engineering_fixture", "variant_id": "component_rename"})
        return manifest

    def create(self, config: dict[str, Any]) -> ModelBackend:
        return RenamingBackend(config["component"])


class SolverFactory(HighsSolverFactory):
    plugin_id = "llm4om.examples.checking_highs"

    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(config_schema=SCHEMA, source={"kind": "engineering_fixture", "variant_id": "checked_component"})
        return manifest

    def create(self, config: dict[str, Any]) -> SolverBackend:
        return CheckingHighsSolver(config["component"])


backend = BackendFactory()
solver = SolverFactory()


class MarkingNativeBackend(GurobiFactoryBackend):
    def __init__(self, component: str) -> None:
        self.component = component

    def load(self, build: str | CompiledCode, data: Mapping[str, bytes]) -> ModelHandle:
        handle = super().load(build, data)
        handle.model._fixture_component = self.component
        return handle

    @contextmanager
    def read_transport(self, exported: dict[str, Any]) -> Iterator[ModelHandle]:
        with super().read_transport(exported) as handle:
            handle.model._fixture_component = self.component
            yield handle


class CheckingGurobiSolver(GurobiSolverBackend):
    def __init__(self, component: str) -> None:
        self.component = component

    def solve(self, handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
        if getattr(handle.model, "_fixture_component", None) != self.component:
            raise RunError("invalid_model_handle", "solve", "The selected native Backend's transport marker is missing.")
        result = super().solve(handle, options)
        result["effective_options"]["fixture_component"] = self.component
        return result


class NativeBackendFactory(GurobiBackendFactory):
    plugin_id = "llm4om.examples.marking_gurobipy"

    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(config_schema=SCHEMA, source={"kind": "engineering_fixture", "variant_id": "native_transport_marker"})
        return manifest

    def create(self, config: dict[str, Any]) -> ModelBackend:
        return MarkingNativeBackend(config["component"])


class NativeSolverFactory(GurobiSolverFactory):
    plugin_id = "llm4om.examples.checking_gurobi"
    handle_profiles = ["gurobipy_linear/0.1.0"]

    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(config_schema=SCHEMA, source={"kind": "engineering_fixture", "variant_id": "checked_native_transport"})
        return manifest

    def create(self, config: dict[str, Any]) -> SolverBackend:
        return CheckingGurobiSolver(config["component"])


native_backend = NativeBackendFactory()
native_solver = NativeSolverFactory()
