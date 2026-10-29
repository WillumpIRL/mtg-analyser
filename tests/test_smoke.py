"""Smoke tests: prove the package installs, imports and the CLI runs."""

from typer.testing import CliRunner

import mtg_analyser
from mtg_analyser.cli import app


def test_package_has_version() -> None:
    assert mtg_analyser.__version__ == "0.1.0"


def test_cli_version_command() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
