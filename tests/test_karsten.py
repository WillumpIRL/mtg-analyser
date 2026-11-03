"""Tests for Karsten's tables and formulas, checked against his articles' examples,
plus the hypergeometric odds they rely on."""

from math import comb

import pytest

from mtg_analyser import karsten
from mtg_analyser.odds import cards_seen, prob_at_least, prob_exactly

COL60, COL80, COL99, COL40 = range(4)


# ---------- source table ----------


@pytest.mark.parametrize(
    "generic, pips, column, expected",
    [
        (0, 1, COL60, 14),  # Monastery Swiftspear
        (2, 2, COL60, 16),  # Wrath of God
        (0, 2, COL60, 21),  # Lord of Atlantis
        (0, 3, COL99, 36),  # Goblin Chainwhirler in Commander
        (2, 2, COL40, 11),
        (1, 4, COL80, 31),  # Unnatural Growth
    ],
)
def test_sources_required_matches_table(generic, pips, column, expected) -> None:
    assert karsten.sources_required(generic, pips, column) == expected


def test_sources_required_clamps_costs_beyond_the_table() -> None:
    # {7}{G} isn't listed; more generic mana is easier, so reuse the 5C row
    assert karsten.sources_required(7, 1, COL60) == karsten.sources_required(5, 1, COL60)
    # five pips use the four-pip rows
    assert karsten.sources_required(0, 5, COL60) == 24
    assert karsten.sources_required(0, 0, COL60) == 0


@pytest.mark.parametrize(
    "size, commander, column",
    [
        (40, False, COL40),
        (42, False, COL40),
        (60, False, COL60),
        (80, False, COL80),
        (99, True, COL99),
    ],
)
def test_deck_size_column(size, commander, column) -> None:
    assert karsten.deck_size_column(size, commander) == column


# ---------- land formula ----------


def test_land_formula_boros_example() -> None:
    # Article: average mana value 2.2, no cheap spells -> 23.77 lands
    assert karsten.recommended_lands(2.2, 0, 60) == pytest.approx(23.77, abs=0.005)


def test_land_formula_esper_example() -> None:
    assert karsten.recommended_lands(2.9, 0, 60) == pytest.approx(25.10, abs=0.005)


def test_land_formula_cheap_spells_and_companion() -> None:
    base = karsten.recommended_lands(3.0, 0, 60)
    assert karsten.recommended_lands(3.0, 4, 60) == pytest.approx(base - 1.12)
    assert karsten.recommended_lands(3.0, 0, 60, companion=True) == pytest.approx(base + 0.27)


def test_land_formula_commander() -> None:
    # Article: "if your average mana value is three ... start with 40 or 41 lands"
    assert karsten.recommended_lands(3.0, 0, 99, commander=True) == pytest.approx(40.81)


def test_land_formula_limited_gives_about_17() -> None:
    assert karsten.recommended_lands(3.0, 0, 40) == pytest.approx(16.86)


# ---------- odds ----------


def test_prob_exactly_matches_hand_count() -> None:
    # 2 lands in a 4-card deck, draw 2: 4 of the 6 possible pairs have exactly 1 land
    assert prob_exactly(1, 2, 4, 2) == pytest.approx(4 / 6)
    assert prob_exactly(0, 24, 60, 7) == pytest.approx(comb(36, 7) / comb(60, 7))


def test_opening_hand_probabilities_sum_to_one() -> None:
    assert sum(prob_exactly(k, 24, 60, 7) for k in range(8)) == pytest.approx(1.0)


def test_prob_at_least_edges() -> None:
    assert prob_at_least(0, 17, 40, 7) == pytest.approx(1.0)
    assert prob_at_least(8, 17, 40, 7) == 0.0
    assert prob_exactly(1, 1, 5, 9) == 0.0  # can't draw more cards than the library holds


def test_cards_seen() -> None:
    assert cards_seen(1, on_play=True) == 7
    assert cards_seen(1, on_play=False) == 8
    assert cards_seen(4, on_play=True) == 10
