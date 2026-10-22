"""The command line."""

from typing import Any

from llm4om.cli import _print_step


def test_cli_reports_failed_solve_without_a_status(capsys: Any) -> None:
    _print_step({"type": "solve", "title": "final solve", "running": False, "failed": True})
    assert "final solve" in capsys.readouterr().err
