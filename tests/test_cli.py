"""The command line."""

from pathlib import Path
from typing import Any

from llm4om.cli import _print_step, main


def test_cli_reports_failed_solve_without_a_status(capsys: Any) -> None:
    _print_step({"type": "solve", "title": "final solve", "running": False, "failed": True})
    assert "final solve" in capsys.readouterr().err


def test_cli_reports_a_missing_input_file_without_a_traceback(tmp_path: Path, capsys: Any) -> None:
    missing = tmp_path / "missing.txt"
    assert main(["run", "--file", str(missing), "--workspace", str(tmp_path)]) == 2
    assert capsys.readouterr().err.strip() == f"Error: Cannot read {missing}: No such file or directory."
