"""Resource bridges for fixed, trusted MIT OptiMUS stage functions.

No generated Python is evaluated here. Original modules have per-run namespaces;
client, file, logging and execution imports are supplied by explicit bridges.
"""

import ast
import builtins
from enum import Enum
import hashlib
import inspect
import io
import json
from pathlib import Path, PurePosixPath
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

from llm4om.contracts import RunError

SOURCE = Path(__file__).with_name("optimus_source")


class SourceRuntime:
    def __init__(self, files: dict[str, bytes], complete: Callable[..., str],
                 execute: Callable[[str, bytes], dict[str, Any]], record: Callable[[str, bytes], Any]) -> None:
        self.files = dict(files)
        self.complete = complete
        self.execute = execute
        self.record = record
        self.modules: dict[str, Any] = {}
        self.manifest = json.loads((SOURCE / "manifest.json").read_text())
        self.abort: BaseException | None = None
        self.selected: str | None = None
        self.last_executed: str | None = None

    def source(self, name: str) -> bytes:
        entry = self.manifest["files"][name]
        raw: bytes = (SOURCE / entry["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            raise RunError("source_hash_mismatch", "admission", "Fixed OptiMUS source bytes changed.")
        return raw

    def open(self, name: str, mode: str = "r", **kwargs: Any) -> io.StringIO:
        key = PurePosixPath(name).name
        if mode not in ("r", "w", "a"):
            raise ValueError("Unsupported source file bridge operation.")
        if mode == "r" and key not in self.files:
            raise FileNotFoundError(key)
        runtime = self

        class SourceFile(io.StringIO):
            def close(self) -> None:
                if not self.closed and mode != "r":
                    value = self.getvalue().encode()
                    runtime.files[key] = value
                    if key != "log.txt":
                        runtime.record(key, value)
                super().close()

        stream = SourceFile(self.files.get(key, b"").decode() if mode != "w" else "")
        if mode == "a":
            stream.seek(0, 2)
        return stream

    def _client(self, **kwargs: Any) -> Any:
        def create(*, messages: list[dict[str, Any]], model: str) -> Any:
            if self.abort is not None:
                raise self.abort
            frame = inspect.currentframe()
            # The vendored get_response->create call chain is hash-locked upstream; this frame walk
            # resolves the requesting LLM role and is only valid against that fixed chain.
            caller = frame.f_back.f_back if frame is not None and frame.f_back is not None else None
            role = f"{Path(caller.f_code.co_filename).stem}.{caller.f_code.co_name}" if caller else "source"
            try:
                text = self.complete(messages, model, role)
            except BaseException as error:
                self.abort = error
                raise
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def _run(self, command: list[str], **kwargs: Any) -> Any:
        from subprocess import CalledProcessError
        filename = command[1]
        self.last_executed = filename
        try:
            result = self.execute(filename, self.files[filename])
        except BaseException as error:
            self.abort = error
            raise
        source = result["source"]
        if source["status"] != "completed":
            self.abort = RunError("execution_" + source["status"], "execution", "Source execution exceeded platform limits.")
            raise self.abort
        if source["exit_code"] != 0:
            raise CalledProcessError(source["exit_code"], command, stderr=source["stderr"])
        self.selected = filename
        return SimpleNamespace(stdout=source["stdout"])

    def load(self, name: str, *, reference_main: bool = False) -> Any:
        if name in self.modules:
            return self.modules[name]
        module = ModuleType(name)
        module.__dict__["__builtins__"] = {**vars(builtins), "__import__": self.import_module,
                                          "open": self.open, "print": lambda *args, **kwargs: None}
        module.__dict__["__name__"] = "__main__" if reference_main else name
        self.modules[name] = module
        exec(compile(self.source(name + ".py"), name + ".py", "exec"), module.__dict__)
        return module

    def import_module(self, name: str, globals: Any = None, locals: Any = None,
                      fromlist: Any = (), level: int = 0) -> Any:
        if name + ".py" in self.manifest["files"]:
            return self.load(name)
        if name in ("json", "re", "time"):
            return builtins.__import__(name, globals, locals, fromlist, level)
        if name == "os":
            return SimpleNamespace(path=SimpleNamespace(join=lambda *args: "/".join(args), exists=lambda path: True),
                                   makedirs=lambda path: None)
        if name in ("numpy", "pandas"):
            return SimpleNamespace()
        if name == "groq":
            return SimpleNamespace(Groq=self._client)
        if name == "openai":
            return SimpleNamespace(Client=self._client)
        if name == "subprocess":
            from subprocess import CalledProcessError
            return SimpleNamespace(run=self._run, CalledProcessError=CalledProcessError)
        if name == "argparse":
            return SimpleNamespace(ArgumentParser=lambda **kwargs: SimpleNamespace(
                add_argument=lambda *args, **kwargs: None,
                parse_args=lambda: SimpleNamespace(dir="public", devmode=1, rag_mode=None)))
        if name == "rag.rag_utils":
            if name not in self.modules:
                tree = ast.parse(self.source("rag/rag_utils.py"))
                enum = ast.Module(body=[node for node in tree.body if isinstance(node, ast.ClassDef)], type_ignores=[])
                namespace: dict[str, Any] = {"Enum": Enum}
                exec(compile(enum, "rag/rag_utils.py", "exec"), namespace)
                self.modules[name] = SimpleNamespace(RAGMode=namespace["RAGMode"], constraint_path=None)
            return self.modules[name]
        if name == "rag.query_vector_db":
            def unavailable(*args: Any, **kwargs: Any) -> Any:
                raise RunError("rag_resources_unavailable", "admission", "No rights-cleared compatible corpus/index is admitted.")
            return SimpleNamespace(RAGFormat=SimpleNamespace(), get_rag_from_problem_categories=unavailable,
                get_rag_from_problem_description=unavailable, get_rag_from_constraint=unavailable, get_rag_from_objective=unavailable)
        raise ImportError("Fixed source requested an undeclared external resource: " + name)

    def run(self) -> None:
        utils = self.load("utils")
        state = utils.create_state("public", "run")
        labels = utils.get_labels("public")
        logger = utils.Logger("run/log.txt")
        logger.reset()
        names = ["state_1_params.json", "state_2_objective.json", "state_3_constraints.json",
                 "state_4_constraints_modeled.json", "state_5_objective_modeled.json", "state_6_code.json"]
        utils.save_state(state, names[0])
        options = {"model": "gpt-4o", "check": True, "rag_mode": None, "labels": labels}
        state = utils.load_state(names[0])
        state["objective"] = self.load("objective").get_objective(state["description"], state["parameters"], logger=logger, **options)
        utils.save_state(state, names[1])
        state = utils.load_state(names[1])
        state["constraints"] = self.load("constraint").get_constraints(state["description"], state["parameters"], logger=logger, **options)
        utils.save_state(state, names[2])
        state = utils.load_state(names[2])
        state["constraints"], state["variables"] = self.load("constraint_model").get_constraint_formulations(
            state["description"], state["parameters"], state["constraints"], logger=logger, **options)
        utils.save_state(state, names[3])
        state = utils.load_state(names[3])
        state["objective"] = self.load("objective_model").get_objective_formulation(
            state["description"], state["parameters"], state["variables"], state["objective"], **options)
        utils.save_state(state, names[4])
        state = utils.load_state(names[4])
        state["constraints"], state["objective"] = self.load("target_code").get_codes(
            state["description"], state["parameters"], state["variables"], state["constraints"], state["objective"], model="gpt-4o", check=True)
        utils.save_state(state, names[5])
        state = utils.load_state(names[5])
        self.load("generate_code").generate_code(state, "run")
        self.load("execute_code").execute_and_debug(state, "run", "gpt-4o", logger)

    def compare_reference(self, responses: list[dict[str, Any]], executions: list[dict[str, Any]]) -> dict[str, Any]:
        """Run unchanged fixed main; compare observations, never generated expected states."""
        calls = 0
        attempts = 0
        differences = []

        def complete(messages: list[dict[str, Any]], model: str, role: str) -> str:
            nonlocal calls
            expected = responses[calls]
            if {"messages": messages, "model": model, "role": role} != {key: expected[key] for key in ("messages", "model", "role")}:
                differences.append("prompt/role/model:" + str(calls))
            calls += 1
            text: str = expected["response"]
            return text

        def execute(filename: str, source: bytes) -> dict[str, Any]:
            nonlocal attempts
            expected = executions[attempts]
            if filename != expected["filename"] or source != expected["source"]:
                differences.append("script-attempt:" + str(attempts))
            attempts += 1
            result: dict[str, Any] = expected["result"]
            return result

        files: dict[str, bytes] = {}
        reference = SourceRuntime({name: self.files[name] for name in ("params.json", "labels.json", "desc.txt")},
                                  complete, execute, lambda name, value: files.update({name: value}))
        try:
            reference.load("main", reference_main=True)
        except Exception as error:
            differences.append("reference_exception:" + type(error).__name__)
        for name, value in files.items():
            if self.files.get(name) != value:
                differences.append("file:" + name)
        if calls != len(responses) or attempts != len(executions):
            differences.append("resource_tape_length")
        if (reference.selected, reference.last_executed) != (self.selected, self.last_executed):
            differences.append("selection")
        return {"schema_version": "0.1.0", "status": "match" if not differences else "mismatch",
            "reference_entry": "fixed main.py __main__", "upstream_commit": self.manifest["upstream_commit"],
            "differences": differences, "prompt_comparisons": calls, "execution_comparisons": attempts,
            "file_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
            "source_selected": reference.selected, "last_executed": reference.last_executed,
            "substitutions": ["external clients through shared Gateway", "in-memory source file/log bridge",
                "no-RAG import resources disabled", "source execution tape; generated code never runs on reference host",
                "configured general chat model replaces GPT-4o", "platform budgets, cancellation, isolated script capture and independent collector"],
            "paper_differences": ["supplied parameters", "no connected graph/structure/sifting agents", "three executions, not five", "confidence above three"],
            "rag_resources": "not admitted: corpus rights/splits/objective-key joins unresolved",
            "evidence_scope": "same-tape orchestration only; no external-model quality or complete paper reproduction claim"}


def main() -> int:
    """Trusted source driver process; resource requests are mediated by the parent."""
    import resource
    import sys
    import ctypes
    import os
    import signal
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != int(sys.argv[1]):
        return 1
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    initial = json.loads(sys.stdin.readline(16 * 1024 * 1024))
    responses: list[dict[str, Any]] = []
    executions: list[dict[str, Any]] = []

    def exchange(value: dict[str, Any]) -> Any:
        print(json.dumps(value, allow_nan=False), flush=True)
        reply = json.loads(sys.stdin.readline(16 * 1024 * 1024))
        return reply["value"]

    def complete(messages: list[dict[str, Any]], model: str, role: str) -> str:
        text: str = exchange({"operation": "complete", "messages": messages, "model": model, "role": role})
        responses.append({"messages": messages, "model": model, "role": role, "response": text})
        return text

    def execute(filename: str, source: bytes) -> dict[str, Any]:
        result: dict[str, Any] = exchange({"operation": "execute", "filename": filename, "source": source.decode()})
        executions.append({"filename": filename, "source": source, "result": result})
        return result

    def record(name: str, value: bytes) -> Any:
        return exchange({"operation": "record", "name": name, "value": value.decode()})

    runtime = SourceRuntime({name: value.encode() for name, value in initial["files"].items()}, complete, execute, record)
    try:
        runtime.run()
        record("source-lock.json", json.dumps(runtime.manifest, indent=2).encode())
        record("fidelity-report.json", json.dumps(runtime.compare_reference(responses, executions), indent=2).encode())
        print(json.dumps({"operation": "done", "selected": runtime.selected, "last_executed": runtime.last_executed}), flush=True)
        return 0
    except Exception as error:
        print(json.dumps({"operation": "failed", "exception": type(error).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
