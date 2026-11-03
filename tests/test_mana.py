"""Tests for reading mana costs."""

import pytest

from mtg_analyser.mana import parse_face_costs, parse_mana_cost

R, W, U, G = (frozenset({c}) for c in "RWUG")


@pytest.mark.parametrize(
    "cost, mana_value, pips",
    [
        ("{R}", 1, {R: 1}),
        ("{2}{W}{W}", 4, {W: 2}),
        ("{1}{W}{U}", 3, {W: 1, U: 1}),
        ("{10}", 10, {}),
        ("", 0, {}),
        ("{C}{C}", 2, {frozenset({"C"}): 2}),  # colourless must be paid with {C}
        ("{W/U}{W/U}", 2, {frozenset({"W", "U"}): 2}),  # hybrid
        ("{1}{G/P}", 2, {}),  # Phyrexian: can pay life instead
        ("{2/W}{2/W}", 4, {}),  # twobrid: can pay 2 instead
        ("{S}{S}", 2, {}),  # snow
    ],
)
def test_parse_mana_cost(cost: str, mana_value: int, pips: dict) -> None:
    parsed = parse_mana_cost(cost)
    assert parsed.mana_value == mana_value
    assert parsed.pips == pips


def test_x_counts_as_zero_but_is_remembered() -> None:
    cost = parse_mana_cost("{X}{X}{R}")
    assert cost.mana_value == 1
    assert cost.x_count == 2
    assert cost.has_x


def test_lower_case_symbols() -> None:
    assert parse_mana_cost("{1}{r}").pips == {R: 1}


def test_colour_weights_split_hybrid() -> None:
    weights = parse_mana_cost("{R}{R}{R/G}").colour_weights()
    assert weights == {"R": 2.5, "G": 0.5}


def test_face_costs() -> None:
    faces = parse_face_costs("{1}{U}{U} // {1}{U}")  # Brazen Borrower // Petty Theft
    assert [f.mana_value for f in faces] == [3, 2]
    assert parse_face_costs("") == []
