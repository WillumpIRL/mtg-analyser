"""Tests for the command-line commands, with card loading swapped for sample data."""

import io
import json
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


# A 40-card Limited deck from the sample cards, with one typo and one unreadable line.
DECK = """Deck
17 Forest
4 Lightning Bolt
4 Counterspell
4 brazen borrower (ELD) 39
4 Kitchen Finks
3 Shatterskull Smashing
4 Lightnig Bolt
nonsense [x]

Sideboard
2 Fireball
"""


def run(*args: str, input: str | None = None, deck: str = DECK, tmp_path=None):
    """Invoke the CLI; a `{deck}` argument is replaced by a file holding `deck`."""
    if tmp_path is not None:
        path = tmp_path / "my_deck.txt"
        path.write_text(deck, encoding="utf-8")
        args = tuple(str(path) if a == "{deck}" else a for a in args)
    return runner.invoke(cli.app, list(args), input=input, terminal_width=200)


def test_analyse_report_sections(use_sample_cards, tmp_path) -> None:
    result = run("analyse", "{deck}", tmp_path=tmp_path)
    assert result.exit_code == 0
    out = result.stdout
    for heading in ("Mana curve", "Lands", "Colours", "Opening hand", "Deck checks"):
        assert heading in out
    assert "Limited deck · 40 cards" in out
    assert "sideboard 2 (not analysed" in out
    assert "Recommended:" in out


def test_analyse_reports_problem_lines_with_suggestions(use_sample_cards, tmp_path) -> None:
    out = run("analyse", "{deck}", tmp_path=tmp_path).stdout
    assert "Did you mean: Lightning Bolt" in out  # FR-5
    assert "Line 9" in out  # "nonsense [x]"


def test_analyse_list_shows_matched_cards(use_sample_cards, tmp_path) -> None:
    out = run("analyse", "{deck}", "--list", tmp_path=tmp_path).stdout
    assert "Brazen Borrower // Petty Theft" in out  # forgiving lookup
    assert "not found" in out  # the typo line


def test_analyse_escapes_user_text(use_sample_cards, tmp_path) -> None:
    deck = "4 Lightning Bolt\n4 Odd Card [promo]\n"
    out = run("analyse", "{deck}", "--list", deck=deck, tmp_path=tmp_path).stdout
    assert "Odd Card [promo]" in out  # shown literally, not eaten as Rich markup


def test_analyse_reads_pasted_text_from_stdin(use_sample_cards) -> None:
    result = run("analyse", "-", input=DECK)
    assert result.exit_code == 0
    assert "pasted deck" in result.stdout


def test_analyze_spelling_works_too(use_sample_cards) -> None:
    assert run("analyze", "-", input=DECK).exit_code == 0


def test_parse_command_is_gone(use_sample_cards) -> None:
    assert run("parse", "-", input=DECK).exit_code != 0


def test_analyse_json(use_sample_cards, tmp_path) -> None:
    result = run("analyse", "{deck}", "--json", tmp_path=tmp_path)
    assert result.exit_code == 0
    data = json.loads(result.stdout)  # stdout is pure JSON
    assert data["deck"] == "my_deck.txt"
    assert data["analysis"]["format"] == "limited"
    assert data["analysis"]["library_size"] == 40
    assert data["problems"][0]["suggestions"][0] == "Lightning Bolt"
    assert data["chart"] is None


def test_analyse_with_sideboard(use_sample_cards, tmp_path) -> None:
    result = run("analyse", "{deck}", "--json", "--with-sideboard", tmp_path=tmp_path)
    data = json.loads(result.stdout)
    assert data["analysis"]["library_size"] == 42
    assert data["analysis"]["include_sideboard"] is True


def test_analyse_chart(use_sample_cards, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = run("analyse", "{deck}", "--chart", "--json", tmp_path=tmp_path)
    assert result.exit_code == 0
    chart = tmp_path / "output" / "my_deck.png"
    assert chart.read_bytes().startswith(b"\x89PNG")
    assert "Saved chart" in result.stderr  # status goes to stderr...
    assert json.loads(result.stdout)["chart"].endswith("my_deck.png")  # ...JSON stays clean


def test_analyse_deck_checks(use_sample_cards, tmp_path) -> None:
    deck = "40 Forest\n12 Lightning Bolt\n8 Counterspell\n"
    out = run("analyse", "{deck}", deck=deck, tmp_path=tmp_path).stdout
    assert "12 copies of Lightning Bolt" in out


def test_analyse_missing_file(use_sample_cards, tmp_path) -> None:
    result = run("analyse", str(tmp_path / "nope.txt"))
    assert result.exit_code == 1
    assert "Can't read" in result.stderr


def test_analyse_without_card_data(monkeypatch, tmp_path) -> None:
    def offline(force_refresh=False):
        raise ScryfallError("Could not reach Scryfall")

    monkeypatch.setattr(cli, "load_cards_with_progress", offline)
    result = run("analyse", "{deck}", tmp_path=tmp_path)
    assert result.exit_code == 1
    assert "Could not reach Scryfall" in result.stderr


def test_analyse_nothing_recognised(use_sample_cards) -> None:
    result = run("analyse", "-", input="4 Not A Card\n")
    assert result.exit_code == 1
    assert "No cards recognised" in result.stderr
    assert "Not A Card" in result.stderr


def test_update_cards_reports_errors(monkeypatch) -> None:
    def fail(force_refresh=False):
        raise ScryfallError("Could not reach Scryfall")

    monkeypatch.setattr(cli, "load_cards_with_progress", fail)
    result = runner.invoke(cli.app, ["update-cards"])
    assert result.exit_code == 1
    assert "Could not reach Scryfall" in result.stderr


def test_analyse_commander_deck(use_sample_cards) -> None:
    deck = "Commander\n1 Kitchen Finks\n\nDeck\n1 Sol Ring\n98 Forest\n"
    out = run("analyse", "-", input=deck).stdout
    assert "Commander deck · 100 cards · commander: Kitchen Finks" in out
    assert "everyone draws on turn 1" in out
    assert "Land drop made" in out
