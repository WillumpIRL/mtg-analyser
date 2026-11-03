"""Tests for the command-line commands, with card loading swapped for sample data."""

import io
import sys

import pytest
from typer.testing import CliRunner

from mtg_analyser import cli
from mtg_analyser.scryfall import ScryfallError

runner = CliRunner()


@pytest.fixture
def use_sample_cards(monkeypatch, cards) -> None:
    """Make the CLI load the sample cards instead of the real cache."""
    monkeypatch.setattr(cli, "load_cards_with_progress", lambda force_refresh=False: cards)


def test_card_lookup(use_sample_cards) -> None:
    result = runner.invoke(cli.app, ["card", "lightning bolt"])
    assert result.exit_code == 0
    assert "Lightning Bolt" in result.output
    assert "Instant" in result.output


def test_card_lookup_shows_faces_and_mdfc_flag(use_sample_cards) -> None:
    result = runner.invoke(cli.app, ["card", "Shatterskull Smashing"])
    assert result.exit_code == 0
    assert "MDFC land" in result.output
    assert "Shatterskull, the Hammer Pass" in result.output


def test_card_not_found_suggests(use_sample_cards) -> None:
    result = runner.invoke(cli.app, ["card", "Lightnig Bolt"])
    assert result.exit_code == 1
    assert "Did you mean" in result.output


def test_output_switched_to_utf8(monkeypatch) -> None:
    # Regression: under MSYS2/mintty, Python on Windows wrote cp1252 and "—" came out as "�".
    raw = io.BytesIO()
    fake_stdout = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    cli.use_utf8_output()
    print("Creature — Faerie • Rogue", end="")
    fake_stdout.flush()
    assert raw.getvalue().decode("utf-8") == "Creature — Faerie • Rogue"


def test_parse_shows_entries_and_problems(use_sample_cards, tmp_path) -> None:
    path = tmp_path / "deck.txt"
    path.write_text("Deck\n4 brazen borrower (ELD) 39\n4 Lightnig Bolt\nnonsense [x]\n")
    result = runner.invoke(cli.app, ["parse", str(path)], terminal_width=200)
    assert result.exit_code == 0
    assert "Brazen Borrower // Petty Theft" in result.output  # resolved name
    assert "Did you mean: Lightning Bolt" in result.output  # FR-5 suggestion
    assert "nonsense [x]" in result.output  # user text shown literally, not as markup


def test_parse_reads_pasted_text_from_stdin(use_sample_cards) -> None:
    result = runner.invoke(cli.app, ["parse", "-"], input="4 Counterspell\n", terminal_width=200)
    assert result.exit_code == 0
    assert "Counterspell" in result.output


def test_parse_without_card_data_still_shows_entries(monkeypatch, tmp_path) -> None:
    def offline(force_refresh=False):
        raise ScryfallError("Could not reach Scryfall")

    monkeypatch.setattr(cli, "load_cards_with_progress", offline)
    path = tmp_path / "deck.txt"
    path.write_text("4 Lightning Bolt\n")
    result = runner.invoke(cli.app, ["parse", str(path)], terminal_width=200)
    assert result.exit_code == 0
    assert "Card names not checked" in result.output
    assert "Lightning Bolt" in result.output


def test_parse_missing_file(use_sample_cards, tmp_path) -> None:
    result = runner.invoke(cli.app, ["parse", str(tmp_path / "nope.txt")])
    assert result.exit_code == 1
    assert "Can't read" in result.output


def test_update_cards_reports_errors(monkeypatch) -> None:
    def fail(force_refresh=False):
        raise ScryfallError("Could not reach Scryfall")

    monkeypatch.setattr(cli, "load_cards_with_progress", fail)
    result = runner.invoke(cli.app, ["update-cards"])
    assert result.exit_code == 1
    assert "Could not reach Scryfall" in result.output
