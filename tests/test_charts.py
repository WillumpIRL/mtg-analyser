"""Tests for the PNG chart. They check a valid image is written, not how it looks;
looking is done by eye (see the dataviz notes in charts.py)."""

from mtg_analyser.analysis import analyse
from mtg_analyser.charts import _requirement_label, save_chart
from mtg_analyser.parser import parse_decklist, resolve_cards

PNG = b"\x89PNG"


def analysed(db, text: str):
    deck, _ = parse_decklist(text)
    resolved, _ = resolve_cards(deck, db)
    return analyse(deck, resolved)


def test_chart_written(db, tmp_path) -> None:
    analysis = analysed(db, "17 Forest\n12 Lightning Bolt\n11 Kitchen Finks\n")
    path = save_chart(analysis, tmp_path / "nested" / "deck.png", "Test deck")
    assert path.read_bytes().startswith(PNG)


def test_chart_without_colour_requirements(db, tmp_path) -> None:
    analysis = analysed(db, "20 Forest\n20 Sol Ring\n")
    assert analysis.requirements == []
    assert save_chart(analysis, tmp_path / "x.png", "Colourless").read_bytes().startswith(PNG)


def test_requirement_labels(db) -> None:
    analysis = analysed(db, "17 Forest\n12 Lightning Bolt\n11 Kitchen Finks\n")
    labels = [_requirement_label(r) for r in analysis.requirements]
    assert labels == ["Red: Lightning Bolt", "White or Green: Kitchen Finks"]
