"""LLM4OM public application, task and evaluation interfaces."""

from llm4om.storage import cancel_run
from llm4om.control import CancellationToken
from llm4om.backends import ModelHandle, ModelBackend, NativeModelBackend, PyomoBackendFactory, GurobiBackendFactory
from llm4om.solvers import SolverBackend, HighsSolverFactory, GurobiSolverFactory
from llm4om.execution_plugins import ExecutionResources, resolve_execution_resources
from llm4om.compilers import Compiler, LPIRPyomoFactory, LPIRPyomoCompiler, resolve_compiler
from llm4om.linear import CompiledCode
from llm4om.methods import FactoryCodeProposal, ScriptCodeProposal, GenerationFailure, MethodContext, MethodResources, MethodOutcome, ModelProposal
from llm4om.application import RunResult, run_problem, resume_run
from llm4om.tasks import EvaluationCase, TaskAdapter, Evaluator, FrozenTaskAdapter, NL4OptAdapter, import_dataset
from llm4om.evaluation import NL4OptEvaluator, evaluate_case, evaluate_outcome
from llm4om.mamo import MAMOAdapter, MAMOEvaluator
from llm4om.nlp4lp import NLP4LPAdapter, NLP4LPEvaluator
from llm4om.checkers import SolutionChecker, ProductionChecker, UnitCapChecker
from llm4om.checker_tasks import CheckerFixtureAdapter, IndependentCheckerEvaluator
from llm4om.plugins import discover_plugins, discover_methods
from llm4om.task_plugins import prepare_task

__all__ = [
    "ModelHandle", "FactoryCodeProposal", "ScriptCodeProposal", "GenerationFailure", "MethodContext", "MethodResources", "MethodOutcome", "ModelProposal",
    "CancellationToken", "RunResult", "run_problem", "resume_run", "cancel_run", "EvaluationCase", "TaskAdapter", "Evaluator",
    "NL4OptAdapter", "MAMOAdapter", "NLP4LPAdapter", "CheckerFixtureAdapter", "import_dataset",
    "NL4OptEvaluator", "MAMOEvaluator", "NLP4LPEvaluator", "IndependentCheckerEvaluator", "evaluate_case",
    "SolutionChecker", "ProductionChecker", "UnitCapChecker",
    "discover_plugins", "discover_methods",
    "FrozenTaskAdapter", "evaluate_outcome", "prepare_task",
    "Compiler", "CompiledCode", "LPIRPyomoFactory", "LPIRPyomoCompiler", "resolve_compiler",
    "ModelBackend", "NativeModelBackend", "SolverBackend", "PyomoBackendFactory", "GurobiBackendFactory",
    "HighsSolverFactory", "GurobiSolverFactory", "ExecutionResources", "resolve_execution_resources",
]
