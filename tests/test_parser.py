"""Tests for decklist parsing (FR-1 to FR-5).

Parsing needs no card data; only the resolve_cards tests use the sample database.
"""

from pathlib import Path

import pytest

from mtg_analyser.models import DeckEntry, DeckFormat, Section
from mtg_analyser.parser import parse_decklist, read_decklist, resolve_cards

SAMPLE_DECKS = Path(__file__).parents[1] / "sample_decks"


def parse_one(line: str) -> DeckEntry:
    deck, problems = parse_decklist(line)
    assert problems == []
    assert len(deck.entries) == 1
    return deck.entries[0]


# ---------- FR-2: card lines ----------


@pytest.mark.parametrize(
    "line",
    [
        "4 Lightning Bolt",
        "4x Lightning Bolt",
        "4X Lightning Bolt",
        "4 x Lightning Bolt",
        "4 Lightning Bolt (M10) 146",
        "4 Lightning Bolt (M10)",
        "4 Lightning Bolt (2X2) 117 *F*",
        "4 Lightning Bolt *F*",
        "4 Lightning Bolt (PLST) M10-146",
        "  4\tLightning Bolt  ",
        "4 Lightning Bolt",  # non-breaking space from a web page
    ],
)
def test_fr2_card_line_formats(line: str) -> None:
    entry = parse_one(line)
    assert (entry.quantity, entry.name) == (4, "Lightning Bolt")


def test_fr2_name_starting_with_x_is_not_a_quantity_mark() -> None:
    assert parse_one("4 Xathrid Necromancer").name == "Xathrid Necromancer"


@pytest.mark.parametrize(
    "line, name",
    [
        ("1 Fire // Ice (MH2) 290", "Fire // Ice"),
        ("1 Lim-Dûl's Vault", "Lim-Dûl's Vault"),
        ("1 B.F.M. (Big Furry Monster)", "B.F.M. (Big Furry Monster)"),  # not a set code
        ("1 Krenko, Mob Boss (DDT) 52", "Krenko, Mob Boss"),
    ],
)
def test_fr2_awkward_names(line: str, name: str) -> None:
    assert parse_one(line).name == name


def test_fr2_records_line_numbers() -> None:
    deck, _ = parse_decklist("// my deck\n\n4 Lightning Bolt\n2 Counterspell")
    assert [e.line_number for e in deck.entries] == [3, 4]


def test_fr2_large_quantities() -> None:
    assert parse_one("24 Forest").quantity == 24


# ---------- FR-3: headers, blank lines, comments ----------


@pytest.mark.parametrize("header", ["Sideboard", "sideboard", "SIDEBOARD:", "Sideboard :"])
def test_fr3_header_variants(header: str) -> None:
    deck, problems = parse_decklist(f"4 Lightning Bolt\n{header}\n2 Counterspell")
    assert problems == []
    assert deck.sideboard() == [DeckEntry(2, "Counterspell", Section.SIDEBOARD, 3)]


def test_fr3_all_sections() -> None:
    text = """Commander
1 Krenko, Mob Boss

Companion
1 Lurrus of the Dream-Den

Deck
1 Sol Ring

Sideboard
1 Lightning Bolt
"""
    deck, problems = parse_decklist(text)
    assert problems == []
    assert [(e.name, e.section) for e in deck.entries] == [
        ("Krenko, Mob Boss", Section.COMMANDER),
        ("Lurrus of the Dream-Den", Section.COMPANION),
        ("Sol Ring", Section.MAINBOARD),
        ("Lightning Bolt", Section.SIDEBOARD),
    ]


def test_fr3_comments_ignored() -> None:
    deck, problems = parse_decklist("# hash comment\n// slash comment\n4 Lightning Bolt")
    assert problems == []
    assert [e.name for e in deck.entries] == ["Lightning Bolt"]


def test_fr3_arena_about_block_skipped() -> None:
    text = "About\nName Mono-Red Aggro\n\nDeck\n4 Lightning Bolt (M10) 146"
    deck, problems = parse_decklist(text)
    assert problems == []
    assert [e.name for e in deck.entries] == ["Lightning Bolt"]


def test_fr3_headerless_blank_line_starts_sideboard() -> None:
    # MTGO / old Arena export: mainboard, blank line, sideboard
    deck, problems = parse_decklist("4 Lightning Bolt\n56 Mountain\n\n3 Abrade\n")
    assert problems == []
    assert deck.total_cards(Section.MAINBOARD) == 60
    assert deck.sideboard() == [DeckEntry(3, "Abrade", Section.SIDEBOARD, 4)]


def test_fr3_headerless_big_second_block_stays_mainboard() -> None:
    # 20 cards is too many for a sideboard, so the blank line is just spacing.
    deck, _ = parse_decklist("40 Mountain\n\n20 Lightning Bolt")
    assert deck.sideboard() == []
    assert deck.total_cards() == 60


def test_fr3_headerless_several_groups_stay_mainboard() -> None:
    # Hand-typed lists often group cards with blank lines.
    deck, _ = parse_decklist("4 Goblin Guide\n\n4 Lightning Bolt\n\n4 Mountain")
    assert deck.sideboard() == []
    assert deck.total_cards() == 12


def test_fr3_blank_lines_are_spacing_when_headers_exist() -> None:
    deck, _ = parse_decklist("Deck\n4 Lightning Bolt\n\n2 Counterspell")
    assert deck.sideboard() == []


def test_fr3_extra_blank_lines_dont_count_as_groups() -> None:
    deck, _ = parse_decklist("\n\n4 Lightning Bolt\n\n\n\n2 Abrade\n\n")
    assert [e.section for e in deck.entries] == [Section.MAINBOARD, Section.SIDEBOARD]


def test_fr3_sb_prefix_lines() -> None:
    deck, problems = parse_decklist("4 Lightning Bolt\nSB: 2 Abrade\nsb:1 Duress")
    assert problems == []
    assert [(e.name, e.section) for e in deck.sideboard()] == [
        ("Abrade", Section.SIDEBOARD),
        ("Duress", Section.SIDEBOARD),
    ]


def test_fr3_windows_line_endings() -> None:
    deck, problems = parse_decklist("Deck\r\n4 Lightning Bolt\r\n")
    assert problems == []
    assert deck.entries[0].name == "Lightning Bolt"


# ---------- FR-5: problems instead of crashes ----------


def test_fr5_unreadable_lines_reported_with_line_numbers() -> None:
    text = "4 Lightning Bolt\nLightning Bolt\nCreatures (20)\n2 Counterspell"
    deck, problems = parse_decklist(text)
    assert [e.name for e in deck.entries] == ["Lightning Bolt", "Counterspell"]
    assert [(p.line_number, p.line) for p in problems] == [
        (2, "Lightning Bolt"),
        (3, "Creatures (20)"),
    ]
    assert "quantity" in problems[0].message


def test_fr5_zero_quantity_is_a_problem() -> None:
    deck, problems = parse_decklist("0 Lightning Bolt")
    assert deck.entries == []
    assert problems[0].message == "Quantity is 0."


def test_fr5_empty_text() -> None:
    deck, problems = parse_decklist("")
    assert deck.entries == []
    assert problems == []


def test_fr5_resolve_reports_unknown_names_with_suggestions(db) -> None:
    deck, _ = parse_decklist("4 Lightnig Bolt\n4 Counterspell\n1 Totally Fake Card")
    resolved, problems = resolve_cards(deck, db)

    assert [r.card.name for r in resolved] == ["Counterspell"]
    assert [p.line_number for p in problems] == [1, 3]
    assert "Lightning Bolt" in problems[0].suggestions
    assert problems[1].suggestions == ()


def test_resolve_uses_forgiving_lookup(db) -> None:
    deck, _ = parse_decklist("4 brazen borrower (ELD) 39\n1 lim-dul's vault\n1 Fire // Ice")
    resolved, problems = resolve_cards(deck, db)
    assert problems == []
    assert [r.card.name for r in resolved] == [
        "Brazen Borrower // Petty Theft",
        "Lim-Dûl's Vault",
        "Fire // Ice",
    ]
    assert resolved[0].entry.quantity == 4


# ---------- FR-1: reading files ----------


def test_fr1_read_file_with_bom(tmp_path) -> None:
    path = tmp_path / "deck.txt"
    path.write_bytes("﻿Deck\n4 Lightning Bolt\n".encode())  # Notepad-style BOM
    deck, problems = read_decklist(path)
    assert problems == []
    assert deck.entries[0].name == "Lightning Bolt"


def test_fr1_read_cp1252_file(tmp_path) -> None:
    path = tmp_path / "deck.txt"
    path.write_bytes("1 Lim-Dûl's Vault\n".encode("cp1252"))
    deck, _ = read_decklist(path)
    assert deck.entries[0].name == "Lim-Dûl's Vault"


# ---------- sample decks ----------


@pytest.mark.parametrize(
    "filename, fmt, main, side, commander",
    [
        ("limited_rg_m20.txt", DeckFormat.LIMITED, 40, 4, 0),
        ("constructed_mono_red_arena.txt", DeckFormat.CONSTRUCTED, 60, 13, 0),
        ("commander_krenko.txt", DeckFormat.COMMANDER, 99, 0, 1),
    ],
)
def test_sample_decks_parse_cleanly(filename, fmt, main, side, commander) -> None:
    deck, problems = read_decklist(SAMPLE_DECKS / filename)
    assert problems == []
    assert deck.format == fmt
    assert deck.total_cards(Section.MAINBOARD) == main
    assert deck.total_cards(Section.SIDEBOARD) == side
    assert deck.total_cards(Section.COMMANDER) == commander
