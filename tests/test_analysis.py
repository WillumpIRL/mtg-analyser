"""Tests for deck analysis, using small hand-built cards so each rule is visible."""

import pytest

from mtg_analyser.analysis import (
    LandStatus,
    analyse,
    card_text,
    cost_requirements,
    enters_untapped,
    is_cheap_draw,
    is_cheap_ramp,
    land_colours,
)
from mtg_analyser.mana import parse_mana_cost
from mtg_analyser.models import (
    Card,
    CardFace,
    Deck,
    DeckEntry,
    DeckFormat,
    ResolvedEntry,
    Section,
)

COL60, COL40 = 0, 3
W, U, B, R = (frozenset({c}) for c in "WUBR")

# Real Oracle wording, kept here to keep the test tables readable.
DIG_TEXT = (
    "Look at the top four cards of your library. Put one of them into your hand and "
    "the rest on the bottom."
)
RAMP_TEXT = (
    "Search your library for a basic land card, put it onto the battlefield tapped, then shuffle."
)
SPRAWL_TEXT = "Whenever enchanted land is tapped for mana, its controller adds an additional {G}."
WILDS_TEXT = (
    "{T}, Sacrifice this land: Search your library for a basic land card, put it onto"
    " the battlefield tapped, then shuffle."
)
FOOTHILLS_TEXT = (
    "{T}, Pay 1 life, Sacrifice this land: Search your library for a Mountain or "
    "Forest card, put it onto the battlefield, then shuffle."
)


def spell(
    name: str = "Spell",
    cost: str = "{R}",
    mana_value: float | None = None,
    type_line: str = "Instant",
    text: str = "",
    produced: tuple[str, ...] = (),
) -> Card:
    mv = parse_mana_cost(cost).mana_value if mana_value is None else mana_value
    return Card(name, cost, mv, (), (), type_line, produced, text)


def land(name: str = "Mountain", produced: tuple[str, ...] = ("R",), text: str = "") -> Card:
    return Card(name, "", 0, (), (), "Basic Land — Mountain", produced, text)


def mdfc(name: str = "Shatterskull Smashing") -> Card:
    faces = (
        CardFace(name, "{X}{R}{R}", "Sorcery", ("R",), "Deals X damage."),
        CardFace(
            "Shatterskull, the Hammer Pass",
            "",
            "Land",
            (),
            "As this land enters, you may pay 3 life. If you don't, it enters tapped.\n"
            "{T}: Add {R}.",
        ),
    )
    return Card(
        name, "{X}{R}{R}", 2, ("R",), ("R",), "Sorcery // Land", ("R",), "", "modal_dfc", faces
    )


def build(*items: tuple[int, Card] | tuple[int, Card, Section]) -> tuple[Deck, list[ResolvedEntry]]:
    entries, resolved = [], []
    for line, item in enumerate(items, start=1):
        quantity, card, *rest = item
        entry = DeckEntry(quantity, card.name, rest[0] if rest else Section.MAINBOARD, line)
        entries.append(entry)
        resolved.append(ResolvedEntry(entry, card))
    return Deck(entries), resolved


# ---------- Karsten's cheap card draw / ramp rules ----------


@pytest.mark.parametrize(
    "card, expected",
    [
        (spell(cost="{U}", text="Scry 1.\nDraw a card."), True),  # Opt
        (
            spell(
                cost="{1}{U}",
                text=DIG_TEXT,
            ),
            True,
        ),  # dig
        (
            spell(
                cost="{1}{U}", type_line="Creature", text="When this creature enters, draw a card."
            ),
            True,
        ),
        (
            spell(
                cost="{1}{U}",
                type_line="Creature",
                text="Whenever this creature attacks, draw a card.",
            ),
            False,
        ),
        (spell(cost="{2}{U}", text="Draw two cards."), False),  # mana value 3
        (spell(cost="{1}{B}", text="Draw a card. Create a Blood token."), False),
        (spell(cost="{4}{U}{U}", type_line="Creature", text="Flying\nCycling {U}"), True),  # any MV
        (spell(cost="{4}{G}", type_line="Creature", text="Cycling {2}"), False),
        (spell(cost="{4}{G}", type_line="Creature", text="Forestcycling {1}"), False),
    ],
)
def test_cheap_draw(card: Card, expected: bool) -> None:
    assert is_cheap_draw(card) is expected


@pytest.mark.parametrize(
    "card, expected",
    [
        (spell(cost="{G}", type_line="Creature — Elf", text="{T}: Add {G}."), True),
        (spell(cost="{1}", type_line="Artifact", text="{T}: Add {C}{C}."), True),  # Sol Ring
        (
            spell(
                cost="{1}{G}",
                text=RAMP_TEXT,
            ),
            True,
        ),
        (
            spell(
                cost="{1}{G}",
                text="Search your library for up to two basic land cards... sacrifice a land.",
            ),
            False,
        ),
        (
            spell(
                cost="{G}",
                type_line="Enchantment — Aura",
                text=SPRAWL_TEXT,
            ),
            True,
        ),
        (
            spell(cost="{1}{G}", type_line="Creature", text="When this creature dies, add {G}."),
            False,
        ),
        (spell(cost="{2}{G}", type_line="Creature", text="{T}: Add {G}."), False),  # MV 3
        (spell(cost="{U}", text="Draw a card. Add {U}."), False),  # already counts as draw
    ],
)
def test_cheap_ramp(card: Card, expected: bool) -> None:
    assert is_cheap_ramp(card) is expected


def test_lands_are_never_cheap_spells() -> None:
    assert not is_cheap_draw(land(text="Cycling {R}"))
    assert not is_cheap_ramp(land(text="{T}: Add {R}."))


# ---------- lands as sources ----------


@pytest.mark.parametrize(
    "card, colours, untapped",
    [
        (land(), {"R"}, True),
        (
            land("Azorius Guildgate", ("W", "U"), "This land enters tapped.\n{T}: Add {W} or {U}."),
            {"W", "U"},
            False,
        ),
        (
            land(
                "Hallowed Fountain",
                ("W", "U"),
                "As this land enters, you may pay 2 life. If you don't, it enters tapped.",
            ),
            {"W", "U"},
            True,
        ),
        (
            land(
                "Castle Embereth", ("R",), "This land enters tapped unless you control a Mountain."
            ),
            {"R"},
            True,
        ),
        (
            land(
                "Evolving Wilds",
                (),
                WILDS_TEXT,
            ),
            {"W", "U", "B", "R", "G"},
            False,
        ),
        (
            land(
                "Wooded Foothills",
                (),
                FOOTHILLS_TEXT,
            ),
            {"R", "G"},
            True,
        ),
        (mdfc(), {"R"}, True),
    ],
)
def test_land_colours_and_tapped(card: Card, colours: set[str], untapped: bool) -> None:
    assert land_colours(card) == colours
    assert enters_untapped(card) is untapped


# ---------- colour requirements ----------


def test_single_colour_requirement() -> None:
    assert cost_requirements(parse_mana_cost("{2}{W}{W}"), COL60) == {W: 16}  # Wrath of God


def test_gold_requirements_teferi_example() -> None:
    # Article: Teferi, Time Raveler {1}{W}{U} needs 13 white, 13 blue and
    # 19 sources of white and/or blue.
    needs = cost_requirements(parse_mana_cost("{1}{W}{U}"), COL60)
    assert needs == {W: 13, U: 13, W | U: 19}


def test_gold_requirements_liesa_example() -> None:
    # Article: Liesa, Forgotten Archangel {2}{W}{W}{B}: 16 white, 10 black, 20 either
    needs = cost_requirements(parse_mana_cost("{2}{W}{W}{B}"), COL60)
    assert needs == {W: 16, B: 10, W | B: 20}


def test_hybrid_is_one_requirement_on_either_colour() -> None:
    needs = cost_requirements(parse_mana_cost("{W/U}{W/U}"), COL60)
    assert needs == {W | U: 21}


def test_x_spell_checked_with_x_as_one() -> None:
    deck, resolved = build((3, mdfc()), (19, land()), (38, spell()))
    [req] = analyse(deck, resolved).requirements
    # {X}{R}{R} is checked as {1}{R}{R} on turn 3 (18 sources), not {R}{R} on turn 2 (21),
    # because the {R} one-drops are met and this is the harder card.
    assert (req.card, req.turn, req.required) == ("Shatterskull Smashing", 3, 18)


def test_turn_one_counts_only_untapped_lands() -> None:
    tapland = land("Tapland", ("R",), "This land enters tapped.")
    deck, resolved = build((10, land()), (10, tapland), (40, spell(cost="{R}")))
    [req] = analyse(deck, resolved).requirements
    assert req.required == 14
    assert req.available == 10
    assert not req.met
    assert req.shortfall == 4


@pytest.mark.parametrize(
    "cost, available",
    [
        ("{R}", 10),  # turn 1: lands only
        ("{1}{R}", 10 + 4 * 0.5),  # dorks count as half a source from turn 2
        ("{2}{R}", 10 + 4 * 0.5 + 4 * 0.75),  # rocks count three-quarters from turn 3
    ],
)
def test_dorks_and_rocks_count_partially(cost: str, available: float) -> None:
    dork = spell("Dork", "{G}", type_line="Creature — Elf", produced=("R",))
    rock = spell("Rock", "{2}", type_line="Artifact", produced=("R",))
    deck, resolved = build(
        (10, land()), (4, dork), (4, rock), (1, spell("Red", cost)), (41, spell("Filler", "{1}"))
    )
    [req] = [r for r in analyse(deck, resolved).requirements if r.colours == R]
    assert req.available == available


def test_requirements_report_hardest_card_per_colour() -> None:
    deck, resolved = build(
        (8, land()),
        (8, land("Plains", ("W",))),
        (4, spell("Bolt", "{R}")),
        (4, spell("Chainwhirler", "{R}{R}{R}", type_line="Creature")),
        (4, spell("Wrath", "{2}{W}{W}")),
        (32, spell("Filler", "{1}")),
    )
    reqs = analyse(deck, resolved).requirements
    assert [(r.colours, r.card) for r in reqs] == [(W, "Wrath"), (R, "Chainwhirler")]


# ---------- the whole analysis ----------


def test_curve_average_and_pips() -> None:
    deck, resolved = build(
        (1, spell("Commander", "{3}{R}", type_line="Legendary Creature"), Section.COMMANDER),
        (4, spell("One", "{R}")),
        (2, spell("Three", "{1}{R}{R}")),
        (1, spell("Big", "{9}{R}")),
        (3, land()),
    )
    analysis = analyse(deck, resolved)
    assert analysis.curve == {0: 0, 1: 4, 2: 0, 3: 2, 4: 0, 5: 0, 6: 0, 7: 1}  # 7 means 7+
    assert analysis.average_mana_value == pytest.approx((4 + 6 + 10) / 7)  # no lands/commander
    assert analysis.pips == {"R": 4 + 4 + 1 + 1}  # commander's pip counts
    assert analysis.pip_share == {"R": 1.0}
    assert analysis.sources == {"R": 3}


def test_land_check_counts_mdfcs_as_half() -> None:
    deck, resolved = build((20, land()), (4, mdfc()), (36, spell(cost="{2}{R}")))
    check = analyse(deck, resolved).land_check
    assert (check.lands, check.mdfc_lands, check.effective) == (20, 4, 22.0)
    assert check.recommended is not None


@pytest.mark.parametrize(
    "lands, status",
    [(25, LandStatus.OK), (20, LandStatus.TOO_FEW), (30, LandStatus.TOO_MANY)],
)
def test_land_status(lands: int, status: LandStatus) -> None:
    # Average mana value 3, no cheap spells: Karsten recommends 25.29
    deck, resolved = build((lands, land()), (60 - lands, spell(cost="{2}{R}")))
    assert analyse(deck, resolved).land_check.status == status


def test_cheap_spells_lower_the_recommendation() -> None:
    opt = spell("Opt", "{U}", text="Draw a card.")
    shock = spell("Shock", "{U}")  # same mana value, no card draw
    plain = analyse(*build((24, land()), (8, shock), (28, spell(cost="{2}{R}")))).land_check
    cheap = analyse(*build((24, land()), (8, opt), (28, spell(cost="{2}{R}")))).land_check
    assert cheap.cheap_draw_or_ramp == 8
    assert cheap.recommended == pytest.approx(plain.recommended - 8 * 0.28)


def test_small_deck_is_not_judged() -> None:
    deck, resolved = build((10, land()), (10, spell()))
    analysis = analyse(deck, resolved)
    assert analysis.format == DeckFormat.UNKNOWN
    assert analysis.land_check.status == LandStatus.UNKNOWN
    assert analysis.requirements == []


def test_hand_odds_limited() -> None:
    deck, resolved = build((17, land()), (23, spell(cost="{2}{R}")))
    hand = analyse(deck, resolved).hand
    assert (hand.library_size, hand.lands) == (40, 17)
    assert sum(hand.opening_lands) == pytest.approx(1.0)
    assert hand.keepable == pytest.approx(sum(hand.opening_lands[2:6]))
    turns = [t for t, _, _ in hand.land_drops]
    assert turns == [1, 2, 3, 4]
    for _, play, draw in hand.land_drops:
        assert draw > play  # the extra card helps


def test_hand_odds_count_mdfcs_as_lands() -> None:
    deck, resolved = build((20, land()), (4, mdfc()), (36, spell()))
    assert analyse(deck, resolved).hand.lands == 24


def test_commander_deck() -> None:
    deck, resolved = build(
        (1, spell("Krenko", "{2}{R}{R}", type_line="Legendary Creature"), Section.COMMANDER),
        (38, land()),
        (61, spell(cost="{2}{R}")),
    )
    analysis = analyse(deck, resolved)
    assert analysis.format == DeckFormat.COMMANDER
    assert analysis.library_size == 99  # the commander isn't in the library
    # Free first-turn draw: on the play is the same as on the draw
    assert all(play == draw for _, play, draw in analysis.hand.land_drops)
    # The commander's {2}{R}{R} is the hardest red cost: 2CC in 99 cards needs 26
    assert analysis.requirements[0].card == "Krenko"
    assert analysis.requirements[0].required == 26


def test_unresolved_cards_count_towards_library_size() -> None:
    deck, resolved = build((17, land()), (20, spell()))
    deck.entries.append(DeckEntry(3, "Unknown Card", Section.MAINBOARD, 99))
    assert analyse(deck, resolved).library_size == 40


def test_sideboard_and_companion_ignored_except_companion_land_bonus() -> None:
    lurrus = spell("Lurrus", "{1}{W/B}{W/B}", type_line="Legendary Creature")
    base_deck, base_resolved = build((24, land()), (36, spell(cost="{2}{R}")))
    deck, resolved = build(
        (24, land()),
        (36, spell(cost="{2}{R}")),
        (1, lurrus, Section.COMPANION),
        (15, spell("Side", "{W}"), Section.SIDEBOARD),
    )
    base, with_companion = analyse(base_deck, base_resolved), analyse(deck, resolved)
    assert with_companion.pips == base.pips
    assert with_companion.land_check.recommended == pytest.approx(
        base.land_check.recommended + 0.27
    )


def test_card_text_reads_both_halves_of_split_cards(db) -> None:
    text = card_text(db.get("Fire // Ice"))
    assert "divided as you choose" in text  # Fire
    assert "draw a card" in text  # Ice


def test_card_text_reads_only_the_spell_side_of_an_mdfc(db) -> None:
    text = card_text(db.get("Shatterskull Smashing"))
    assert "add {r}" not in text  # that's the land side
