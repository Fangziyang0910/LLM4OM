import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RepositoryChecksTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = Path(self.directory.name)
        files = subprocess.check_output(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
        ).decode().split("\0")
        for name in filter(None, files):
            if not (ROOT / name).is_file():
                continue
            destination = self.repo / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, destination)
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)

    def check_repository(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.repo / "scripts/check_repository.py")],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def test_current_repository_passes(self) -> None:
        result = self.check_repository()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Repository checks passed", result.stdout)

    def test_reports_missing_local_link(self) -> None:
        readme = self.repo / "README.md"
        readme.write_text(readme.read_text() + "\n[Missing](missing.md)\n")
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("README.md: missing local link: missing.md", result.stdout)

    def test_rejects_changed_fixture_data(self) -> None:
        products = self.repo / "examples/specs/data/products.csv"
        products.write_text(products.read_text().replace("A,3,2,1", "A,9,2,1"))
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("data hash mismatch: products", result.stdout)

    def test_rejects_stale_reference_exports(self) -> None:
        path = self.repo / "docs/references/catalog.json"
        catalog = json.loads(path.read_text())
        catalog["records"][0]["title"] = "A changed title"
        path.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("generated references out of date", result.stdout)

    def test_rejects_duplicate_json_keys(self) -> None:
        path = self.repo / "examples/specs/problem.json"
        path.write_text(path.read_text().replace('"revision": "1",', '"revision": "1", "revision": "2",'))
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("duplicate JSON key: revision", result.stdout)

    def test_rejects_unsupported_method_config(self) -> None:
        path = self.repo / "examples/specs/run.yaml"
        path.write_text(path.read_text().replace('output_mode: "lp_ir"', 'output_mode: "unsupported"'))
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("run.yaml: invalid method config", result.stdout)

    def test_rejects_wrong_model_binding(self) -> None:
        path = self.repo / "examples/specs/model-ir.json"
        model = json.loads(path.read_text())
        model["objective"]["expression"]["terms"][0]["coefficient"] = 9
        path.write_text(json.dumps(model, ensure_ascii=False, indent=2) + "\n")
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("fixture invariant failed: objective data binding", result.stdout)

    def test_reports_file_missing_from_audit(self) -> None:
        (self.repo / "unrecorded.md").write_text("# Unrecorded file\n")
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("repository audit: missing file: unrecorded.md", result.stdout)

    def test_rejects_zero_concurrency(self) -> None:
        path = self.repo / "examples/specs/run.yaml"
        path.write_text(path.read_text().replace("max_concurrency: 1", "max_concurrency: 0"))
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("run.yaml: invalid budget: max_concurrency", result.stdout)

    def test_rejects_missing_formulation_element(self) -> None:
        path = self.repo / "examples/specs/formulation.json"
        formulation = json.loads(path.read_text())
        del formulation["representation"]["constraints"]
        path.write_text(json.dumps(formulation, ensure_ascii=False, indent=2) + "\n")
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("formulation fixture: missing five-element field: constraints", result.stdout)

    def test_rejects_stale_stage_reference(self) -> None:
        path = self.repo / "examples/specs/model-artifact.json"
        artifact = json.loads(path.read_text())
        artifact["formulation_ref"]["sha256"] = "0" * 64
        path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n")
        result = self.check_repository()
        self.assertEqual(result.returncode, 1)
        self.assertIn("stage artifact fixture: reference hash or size mismatch: formulation.json", result.stdout)

    def test_ignores_deleted_tracked_files(self) -> None:
        path = self.repo / "obsolete.txt"
        path.write_text("Obsolete content\n")
        subprocess.run(["git", "add", "obsolete.txt"], cwd=self.repo, check=True)
        path.unlink()
        result = self.check_repository()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
