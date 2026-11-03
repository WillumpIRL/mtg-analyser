"""Tests for the deck-construction notes."""

import pytest

from mtg_analyser.legality import check_deck, copy_limit
from mtg_analyser.models import Card, Deck, DeckEntry, ResolvedEntry, Section


def card(
    name: str, type_line: str = "Instant", identity: tuple[str, ...] = (), text: str = ""
) -> Card:
    return Card(name, "", 1, identity, identity, type_line, (), text)


MOUNTAIN = card("Mountain", "Basic Land — Mountain", ("R",))
BOLT = card("Lightning Bolt", identity=("R",))
SWORDS = card("Swords to Plowshares", identity=("W",))
RATS = card(
    "Relentless Rats",
    "Creature — Rat",
    ("B",),
    "A deck can have any number of cards named Relentless Rats.",
)
DWARVES = card(
    "Seven Dwarves",
    "Creature — Dwarf",
    ("R",),
    "A deck can have up to seven cards named Seven Dwarves.",
)
KRENKO = card("Krenko, Mob Boss", "Legendary Creature — Goblin", ("R",))


def deck_of(*items: tuple) -> tuple[Deck, list[ResolvedEntry]]:
    entries, resolved = [], []
    for line, (quantity, c, *section) in enumerate(items, start=1):
        entry = DeckEntry(quantity, c.name, section[0] if section else Section.MAINBOARD, line)
        entries.append(entry)
        resolved.append(ResolvedEntry(entry, c))
    return Deck(entries), resolved


def messages(*items: tuple) -> list[str]:
    return [n.message for n in check_deck(*deck_of(*items))]


@pytest.mark.parametrize(
    "c, limit",
    [(BOLT, 4), (MOUNTAIN, None), (RATS, None), (DWARVES, 7)],
)
def test_copy_limit(c: Card, limit: int | None) -> None:
    assert copy_limit(c, 4) == limit


def test_clean_constructed_deck() -> None:
    assert messages((56, MOUNTAIN), (4, BOLT), (4, SWORDS, Section.SIDEBOARD)) == []


def test_constructed_copy_limit_counts_sideboard_too() -> None:
    notes = messages((56, MOUNTAIN), (4, BOLT), (1, BOLT, Section.SIDEBOARD))
    assert notes == [
        "5 copies of Lightning Bolt; Constructed allows 4 (main deck and sideboard together)."
    ]


def test_copy_limit_exceptions() -> None:
    assert messages((30, MOUNTAIN), (23, RATS), (7, DWARVES)) == []
    assert "8 copies of Seven Dwarves" in messages((30, MOUNTAIN), (22, RATS), (8, DWARVES))[0]


def test_sideboard_limit() -> None:
    notes = messages((56, MOUNTAIN), (4, BOLT), (16, SWORDS, Section.SIDEBOARD))
    assert any("Sideboard has 16 cards" in n for n in notes)


def test_limited_has_no_copy_limit() -> None:
    assert messages((17, MOUNTAIN), (23, BOLT)) == []


def test_too_small_for_any_format() -> None:
    assert messages((10, MOUNTAIN)) == ["Only 10 cards: too few for any format (Limited needs 40)."]


def test_commander_clean() -> None:
    assert messages((1, KRENKO, Section.COMMANDER), (99, MOUNTAIN)) == []


def test_commander_size_singleton_and_identity() -> None:
    deck, resolved = deck_of((1, KRENKO, Section.COMMANDER), (96, MOUNTAIN), (2, BOLT), (1, SWORDS))
    notes = check_deck(deck, resolved)
    assert [n.message for n in notes] == [
        "2 copies of Lightning Bolt; Commander is singleton.",
        "1 card(s) outside the commander's colour identity (R).",
    ]
    assert notes[1].cards == ("Swords to Plowshares",)


def test_commander_wrong_size() -> None:
    notes = messages(
        (1, KRENKO, Section.COMMANDER), (99, MOUNTAIN), (1, card("Shock", identity=("R",)))
    )
    assert notes == [
        "Commander decks have exactly 100 cards, including the commander; this one has 101."
    ]


def test_commander_without_commander_section() -> None:
    assert messages((100, MOUNTAIN)) == ["No Commander section, so colour identity wasn't checked."]
