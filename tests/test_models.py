"""Tests for turning Scryfall data into Card objects (FR-6, FR-8)."""

import pytest

from mtg_analyser.models import Card, Deck, DeckEntry, DeckFormat, Section


def test_normal_card(raw_by_name) -> None:
    bolt = Card.from_scryfall(raw_by_name["Lightning Bolt"])
    assert bolt.mana_cost == "{R}"
    assert bolt.mana_value == 1.0
    assert bolt.colors == ("R",)
    assert bolt.type_line == "Instant"
    assert not bolt.is_land
    assert bolt.faces == ()


def test_basic_land_produces_mana(raw_by_name) -> None:
    forest = Card.from_scryfall(raw_by_name["Forest"])
    assert forest.is_land
    assert forest.produced_mana == ("G",)
    assert forest.colors == ()  # lands are colourless...
    assert forest.color_identity == ("G",)  # ...but have a colour identity


def test_mana_rock_produces_colourless(raw_by_name) -> None:
    sol_ring = Card.from_scryfall(raw_by_name["Sol Ring"])
    assert sol_ring.produced_mana == ("C",)
    assert not sol_ring.is_land


def test_split_card_keeps_both_faces(raw_by_name) -> None:
    fire_ice = Card.from_scryfall(raw_by_name["Fire // Ice"])
    assert fire_ice.layout == "split"
    assert [f.name for f in fire_ice.faces] == ["Fire", "Ice"]
    assert fire_ice.faces[0].mana_cost == "{1}{R}"
    assert fire_ice.mana_value == 4.0  # split cards add both halves together


def test_transform_card_uses_front_face_cost_and_colours(raw_by_name) -> None:
    delver = Card.from_scryfall(raw_by_name["Delver of Secrets // Insectile Aberration"])
    assert delver.mana_cost == "{U}"
    assert delver.colors == ("U",)
    assert not delver.is_mdfc_land


def test_mdfc_land_is_flagged(raw_by_name) -> None:
    smash = Card.from_scryfall(
        raw_by_name["Shatterskull Smashing // Shatterskull, the Hammer Pass"]
    )
    assert smash.is_mdfc_land
    assert not smash.is_land  # front face is a sorcery
    assert smash.mana_cost == "{X}{R}{R}"
    assert smash.has_x_cost


def test_x_cost_detected(raw_by_name) -> None:
    assert Card.from_scryfall(raw_by_name["Fireball"]).has_x_cost
    assert not Card.from_scryfall(raw_by_name["Lightning Bolt"]).has_x_cost


@pytest.mark.parametrize(
    ("name", "cost"),
    [("Kitchen Finks", "{1}{G/W}{G/W}"), ("Gitaxian Probe", "{U/P}")],
)
def test_hybrid_and_phyrexian_costs_kept_as_is(raw_by_name, name, cost) -> None:
    assert Card.from_scryfall(raw_by_name[name]).mana_cost == cost


def test_dict_round_trip(cards) -> None:
    for card in cards:
        assert Card.from_dict(card.to_dict()) == card


# ---------- decks (FR-4) ----------


def make_deck(*entries: tuple[int, Section]) -> Deck:
    return Deck([DeckEntry(qty, f"Card {i}", section) for i, (qty, section) in enumerate(entries)])


def test_fr4_analysed_is_mainboard_plus_commander() -> None:
    deck = make_deck(
        (1, Section.COMMANDER),
        (59, Section.MAINBOARD),
        (1, Section.COMPANION),
        (15, Section.SIDEBOARD),
    )
    assert deck.total_cards() == 60
    assert {e.section for e in deck.analysed()} == {Section.COMMANDER, Section.MAINBOARD}
    assert deck.total_cards(Section.SIDEBOARD) == 15
    assert len(deck.mainboard()) == len(deck.sideboard()) == len(deck.commanders()) == 1


@pytest.mark.parametrize(
    "entries, fmt",
    [
        ([(40, Section.MAINBOARD)], DeckFormat.LIMITED),
        ([(42, Section.MAINBOARD), (30, Section.SIDEBOARD)], DeckFormat.LIMITED),
        ([(60, Section.MAINBOARD), (15, Section.SIDEBOARD)], DeckFormat.CONSTRUCTED),
        ([(100, Section.MAINBOARD)], DeckFormat.COMMANDER),
        ([(1, Section.COMMANDER), (99, Section.MAINBOARD)], DeckFormat.COMMANDER),
        ([(1, Section.COMMANDER), (58, Section.MAINBOARD)], DeckFormat.COMMANDER),  # unfinished
        ([(20, Section.MAINBOARD)], DeckFormat.UNKNOWN),
    ],
)
def test_deck_format_detection(entries, fmt) -> None:
    assert make_deck(*entries).format == fmt


def test_min_deck_size() -> None:
    assert DeckFormat.LIMITED.min_deck_size == 40
    assert DeckFormat.CONSTRUCTED.min_deck_size == 60
    assert DeckFormat.COMMANDER.min_deck_size == 100
    assert DeckFormat.UNKNOWN.min_deck_size == 0
