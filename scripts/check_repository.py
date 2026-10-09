"""Check the repository's documentation and hand-authored fixtures."""

import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from urllib.parse import unquote, urlsplit

import jsonschema
import yaml


ROOT = Path(__file__).resolve().parents[1]


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_nonfinite(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def check_json(files: list[Path]) -> list[str]:
    errors = []
    for path in files:
        if path.suffix != ".json":
            continue
        content = path.read_text(encoding="utf-8")
        try:
            value = json.loads(content, object_pairs_hook=unique_object, parse_constant=reject_nonfinite)
            if content != json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n":
                errors.append(f"{path.relative_to(ROOT)}: use two-space JSON formatting")
        except ValueError as error:
            errors.append(f"{path.relative_to(ROOT)}: {error}")
    return errors


def repository_files() -> list[Path]:
    result = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
    )
    paths = {ROOT / name for name in result.decode().split("\0") if name}
    return sorted(path for path in paths if path.is_file())


def markdown_anchors(text: str) -> set[str]:
    anchors = set(re.findall(r'<a\s+id="([^"]+)"', text))
    counts: dict[str, int] = {}
    for heading in re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE):
        slug = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def check_text(files: list[Path]) -> list[str]:
    errors = []
    source = ROOT / "src/llm4om/optimus_source"
    manifest = json.loads((source / "manifest.json").read_text())
    pinned = {source / entry["file"]: entry for entry in manifest["files"].values()}
    for path, entry in pinned.items():
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"] or path.stat().st_size != entry["size_bytes"]:
            errors.append(f"{path.relative_to(ROOT)}: fixed upstream bytes changed or missing")
    for path in files:
        name = path.relative_to(ROOT)
        # Fixed upstream files keep their original whitespace and license bytes.
        if path in pinned:
            continue
        text = path.read_text(encoding="utf-8")
        if not path.read_bytes().endswith(b"\n"):
            errors.append(f"{name}: missing final newline")
        if b"\r" in path.read_bytes():
            errors.append(f"{name}: use LF line endings")
        if path.name != "LICENSE" and re.search(r"[ \t]+$", text, re.MULTILINE):
            errors.append(f"{name}: trailing whitespace")
        if path.suffix == ".py":
            compile(text, str(path), "exec")
        if path.suffix != ".md":
            continue
        fences = re.findall(r"^\s*(?:```|~~~)", text, re.MULTILINE)
        if len(fences) % 2:
            errors.append(f"{name}: unclosed code fence")
        # ponytail: inline links only; add reference-link support when that syntax is used.
        for target in re.findall(r"\[[^\]]*\]\(([^\n)]+)\)", text):
            target = target.strip().strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme:
                continue
            destination = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
            if not destination.exists():
                errors.append(f"{name}: missing local link: {target}")
            elif parsed.fragment and destination.suffix == ".md":
                if unquote(parsed.fragment) not in markdown_anchors(destination.read_text()):
                    errors.append(f"{name}: missing anchor: {target}")
    return errors


def check_fixture_data() -> list[str]:
    fixture = ROOT / "examples/specs"
    problem = json.loads((fixture / "problem.json").read_text())
    errors = []
    for ref in problem["data_refs"]:
        data = (fixture / ref["path"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != ref["sha256"]:
            errors.append(f"data hash mismatch: {ref['data_id']}")
    return errors


def check_configs() -> list[str]:
    fixture = ROOT / "examples/specs"
    manifest = json.loads((fixture / "plugin-manifest.json").read_text())
    validator = jsonschema.Draft202012Validator(manifest["config_schema"])
    jsonschema.Draft202012Validator.check_schema(manifest["config_schema"])
    errors = []
    configs = []
    for name in ["run.yaml", "experiment.yaml", "solve.yaml", "plugin-run.yaml"]:
        config = yaml.safe_load((fixture / name).read_text())
        configs.append(config)
        if config["schema_version"] != manifest["schema_version"]:
            errors.append(f"{name}: fixture schema version mismatch")
        methods = config["methods"] if name == "experiment.yaml" else [config["method"]]
        selected_manifest = manifest if name != "plugin-run.yaml" else json.loads(
            (ROOT / "examples/plugins/fixture_method/src/llm4om_fixture_method/manifest.json").read_text())
        selected_validator = validator if name != "plugin-run.yaml" else jsonschema.Draft202012Validator(selected_manifest["config_schema"])
        for method in methods:
            if method["plugin_id"] == selected_manifest["plugin_id"]:
                for error in selected_validator.iter_errors(method["config"]):
                    errors.append(f"{name}: invalid method config at {list(error.path)}")
        if name != "experiment.yaml" and (
            {"task", "methods", "experiment_id", "repeats"} & config.keys()
            or "oracle_path" in json.dumps(config)
        ):
            errors.append(f"{name}: single-problem config contains experiment or oracle fields")
        for key, value in config["budget"].items():
            numeric = not isinstance(value, bool) and isinstance(value, (int, float))
            valid = numeric and math.isfinite(value) and value >= 0
            if valid:
                valid = value > 0 if key == "wall_time_s" else isinstance(value, int)
                if key == "max_concurrency":
                    valid = valid and value >= 1
            if not valid:
                errors.append(f"{name}: invalid budget: {key}")
        if name == "experiment.yaml" and (
            type(config["repeats"]) is not int or config["repeats"] < 1
        ):
            errors.append("experiment.yaml: repeats must be a positive integer")
        response = config["llm"]["config"]["response_artifact"]
        if response != "model-artifact.json" or not (fixture / response).is_file():
            errors.append(f"{name}: missing mock response artifact")
    if configs[0]["method"] != configs[1]["methods"][0]:
        errors.append("fixture method config differs between single run and experiment")
    if configs[2]["method"] != configs[0]["method"]:
        errors.append("fixture method config differs between offline and real solve")
    return errors


def check_stage_artifacts() -> list[str]:
    fixture = ROOT / "examples/specs"
    artifact, formulation, problem = [
        json.loads((fixture / name).read_text())
        for name in ["model-artifact.json", "formulation.json", "problem.json"]
    ]
    errors = []
    required = {"sets", "parameters", "variables", "objective", "constraints"}
    representation = formulation["representation"]
    if not isinstance(representation, dict):
        return ["formulation fixture: representation must be an object"]
    for field in sorted(required - representation.keys()):
        errors.append(f"formulation fixture: missing five-element field: {field}")
    if formulation["representation_kind"] != "five_element":
        errors.append("formulation fixture: expected five_element representation")
    if (
        formulation["problem_id"] != problem["problem_id"]
        or formulation["problem_revision"] != problem["revision"]
    ):
        errors.append("formulation fixture: problem identity differs")
    if formulation["data_bindings"] != artifact["data_bindings"]:
        errors.append("stage artifact fixture: data bindings differ")
    if artifact["stage_status"]["formulation"]["status"] != "available":
        errors.append("stage artifact fixture: expected available Formulation")
    if artifact["code_ref"] is not None or artifact["stage_status"]["code"]["status"] != "pending":
        errors.append("stage artifact fixture: Code must remain pending until actual compilation")
    for reference in [artifact["problem_ref"], artifact["formulation_ref"], formulation["structured_ir_ref"]]:
        path = (fixture / reference["relative_path"]).resolve()
        if not path.is_relative_to(fixture.resolve()):
            errors.append("stage artifact fixture: reference outside fixture directory")
            continue
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != reference["sha256"] or len(content) != reference["size_bytes"]:
            errors.append(f"stage artifact fixture: reference hash or size mismatch: {reference['relative_path']}")
        value = json.loads(content)
        if value["schema_version"] != reference["schema_version"]:
            errors.append(f"stage artifact fixture: reference schema mismatch: {reference['relative_path']}")
    return errors


def check_fixture_semantics() -> list[str]:
    # ponytail: fixed two-product fixture only; general IR validation belongs to platform contracts.
    fixture = ROOT / "examples/specs"
    problem, model, oracle, expected = [
        json.loads((fixture / name).read_text())
        for name in ["problem.json", "model-ir.json", "oracle.json", "expected-evaluation.json"]
    ]
    with (fixture / "data/products.csv").open(newline="") as stream:
        products = {row["product_id"]: row for row in csv.DictReader(stream)}
    with (fixture / "data/capacities.csv").open(newline="") as stream:
        capacities = {row["resource_id"]: int(row["capacity"]) for row in csv.DictReader(stream)}
    errors = []

    def require(condition: bool, message: str) -> None:
        if not condition:
            errors.append(f"fixture invariant failed: {message}")

    require(all(item["problem_id"] == problem["problem_id"] for item in [model, oracle, expected]), "problem identity")
    require(model["problem_revision"] == oracle["problem_revision"] == problem["revision"], "problem revision")
    bindings = {ref["data_id"]: ref["sha256"] for ref in problem["data_refs"]}
    require({ref["data_id"]: ref["sha256"] for ref in model["data_bindings"]} == bindings, "data binding hashes")
    variables = {variable["id"]: variable["name"] for variable in model["variables"]}
    require(set(variables.values()) == set(products), "decision mapping")
    require(all(v["domain"] == "integer" and v["lower_bound"] == 0 for v in model["variables"]), "integer domain")
    objective = model["objective"]
    coefficients = {variables[t["variable_id"]]: t["coefficient"] for t in objective["expression"]["terms"]}
    require(coefficients == {key: int(row["profit"]) for key, row in products.items()}, "objective data binding")
    require(objective["sense"] == "max" and objective["expression"]["constant"] == 0, "objective sense and constant")
    require(len(model["constraints"]) == len(capacities), "resource constraint count")
    for constraint in model["constraints"]:
        resource = constraint["id"].removeprefix("capacity_")
        terms = {variables[t["variable_id"]]: t["coefficient"] for t in constraint["expression"]["terms"]}
        require(terms == {key: int(row[resource]) for key, row in products.items()}, f"resource binding: {resource}")
        require(constraint["rhs"] == capacities[resource] and constraint["sense"] == "le", f"capacity: {resource}")
        require(constraint["expression"]["constant"] == 0, f"constraint constant: {resource}")
    # Independent enumeration uses CSV data, never the candidate IR or oracle rules.
    feasible = [
        {"A": a, "B": b}
        for a in range(9) for b in range(9)
        if all(a * int(products["A"][r]) + b * int(products["B"][r]) <= cap for r, cap in capacities.items())
    ]
    profit = lambda x: sum(x[key] * int(row["profit"]) for key, row in products.items())
    best = max(feasible, key=profit)
    require(profit(best) == oracle["reference_objective"]["value"] == expected["expected"]["candidate_objective"] == 13, "integer optimum")
    require(best == oracle["reference_solution"]["decisions"] == expected["expected"]["mapped_original_decisions"], "reference solution")
    swapped = max(feasible, key=lambda x: 2 * x["A"] + 3 * x["B"])
    require(swapped == {"A": 2, "B": 3} and profit(swapped) == 12, "wrong-binding counterexample")
    relaxation = expected["lp_relaxation_expected"]
    point = {key: Fraction(relaxation[key]) for key in products}
    require(point == {"A": Fraction(8, 3), "B": Fraction(8, 3)} and profit(point) == Fraction(relaxation["objective"]) == Fraction(40, 3), "LP relaxation")
    weights = {"cutting": Fraction(4, 3), "finishing": Fraction(1, 3)}
    require(all(sum(weights[r] * int(row[r]) for r in capacities) == int(row["profit"]) for row in products.values()), "LP dual coefficients")
    require(all(sum(point[key] * int(row[r]) for key, row in products.items()) <= cap for r, cap in capacities.items()), "LP primal feasibility")
    require(sum(weights[r] * cap for r, cap in capacities.items()) == profit(point), "LP primal-dual bound")
    require(expected["record_kind"] == "expected_fixture_assertions_not_actual_results", "expected fixture label")
    require(expected["expected"]["is_real_llm_benchmark"] is False and expected["expected"]["semantic_equivalence"] == "not_available", "evidence boundary")
    require(oracle["access"] == "evaluator_only" and oracle["independent_checker"]["implementation_status"] == "planned", "oracle boundary")
    return errors


def check_design_records() -> list[str]:
    errors = []
    requirements = (ROOT / "docs/requirements/v1.0.md").read_text()
    acceptance = (ROOT / "docs/acceptance.md").read_text()
    for prefix, count, content in [("FR", 36, requirements), ("NFR", 12, requirements), ("AC", 25, acceptance)]:
        identifiers = re.findall(rf"^\| ({prefix}-\d+) \|", content, re.MULTILINE)
        if identifiers != [f"{prefix}-{number:02}" for number in range(1, count + 1)]:
            errors.append(f"{prefix}: missing, duplicate or reordered baseline identifiers")
    records = json.loads((ROOT / "docs/references/catalog.json").read_text())["records"]
    for key in ["id", "citation_key"]:
        if len({record[key] for record in records}) != len(records):
            errors.append(f"reference catalog: duplicate {key}")
    bibliography = (ROOT / "docs/references/references.bib").read_text()
    keys = re.findall(r"^@\w+\{([^,]+),", bibliography, re.MULTILINE)
    if len(keys) != len(records) or set(keys) != {record["citation_key"] for record in records}:
        errors.append("reference catalog: BibTeX keys differ")
    depth = 0
    for character in bibliography:
        depth += (character == "{") - (character == "}")
        if depth < 0:
            break
    if depth:
        errors.append("BibTeX: unbalanced braces")
    agents = (ROOT / "AGENTS.md").read_text()
    if agents.count("## Agent skills\n") != 1:
        errors.append("AGENTS.md: expected one Agent skills block")
    return errors


def check_audit(files: list[Path]) -> list[str]:
    content = (ROOT / "docs/repository-audit.md").read_text()
    rows = re.findall(r"^\| `([^`]+)` \|", content, re.MULTILINE)
    recorded = set(rows)
    actual = {str(path.relative_to(ROOT)) for path in files}
    errors = [f"repository audit: missing file: {name}" for name in sorted(actual - recorded)]
    errors.extend(f"repository audit: stale file: {name}" for name in sorted(recorded - actual))
    if len(rows) != len(recorded):
        errors.append("repository audit: duplicate file rows")
    return errors


def main() -> int:
    try:
        files = repository_files()
        errors = (
            check_text(files) + check_json(files) + check_fixture_data()
            + check_configs() + check_fixture_semantics() + check_design_records()
            + check_stage_artifacts() + check_audit(files)
        )
        references = subprocess.run(
            [sys.executable, str(ROOT / "scripts/render_references.py"), "--check"],
            capture_output=True,
            text=True,
        )
        if references.returncode:
            errors.append(references.stdout.strip() or references.stderr.strip())
    except (
        OSError, UnicodeError, ValueError, SyntaxError, KeyError, TypeError,
        yaml.YAMLError, jsonschema.SchemaError, subprocess.CalledProcessError,
    ) as error:
        print(f"Repository check failed: {error}")
        return 1
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f"Repository checks passed: {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
