"""Analyse a resolved deck: mana curve, colour pips, mana sources, land count,
colour requirements and opening-hand odds.

Everything here is plain data in, plain data out: `analyse()` returns a
DeckAnalysis, and how to show it is up to the CLI (or anything else).

Conventions, mostly following Frank Karsten (see karsten.py for the articles):
- The library is the mainboard. A commander sits in the command zone, so it's left
  out of the curve, average mana value and draw odds, but its colours still count.
- Land/spell MDFCs (e.g. Shatterskull Smashing) are spells in the curve, count as
  0.38 of a land in the land check (0.74 if mythic), and as full colour sources.
- The curve uses Scryfall's mana values, where X counts as 0. For colour checks an
  X spell is assumed cast with X = ASSUMED_X: Karsten suggests picking a typical X
  by hand, which we can't, but X = 0 is rarely the point of casting one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from mtg_analyser import karsten
from mtg_analyser.mana import SOURCE_COLOURS, ManaCost, Pip, parse_face_costs
from mtg_analyser.models import Card, Deck, DeckFormat, ResolvedEntry, Section
from mtg_analyser.odds import cards_seen, prob_at_least, prob_exactly

CURVE_TOP = 7  # the curve's last column is "7+"
LAND_DROP_TURNS = (1, 2, 3, 4)
KEEPABLE_LANDS = range(2, 6)  # 2-5 lands in an opening seven
OPENING_HAND = 7
ASSUMED_X = 1

# Nonland mana sources, per Karsten: dorks may die, so half a source for spells of
# mana value 2+; rocks are sturdier, three-quarters of a source for mana value 3+.
DORK_WEIGHT, DORK_MIN_MANA_VALUE = 0.5, 2
ROCK_WEIGHT, ROCK_MIN_MANA_VALUE = 0.75, 3
# A land count within this many lands of the recommendation is fine.
LAND_TOLERANCE = 1.0


# ---------- results ----------


class LandStatus(StrEnum):
    OK = "ok"
    TOO_FEW = "too few"
    TOO_MANY = "too many"
    UNKNOWN = "unknown"  # deck too small to say


@dataclass(frozen=True, slots=True)
class LandCheck:
    lands: int
    mdfc_lands: int
    mdfc_land_value: float  # what the MDFCs are worth in lands, see mdfc_land_weight()
    cheap_draw_or_ramp: int
    recommended: float | None

    @property
    def effective(self) -> float:
        """Lands with MDFCs counted partially, comparable to `recommended`."""
        return self.lands + self.mdfc_land_value

    @property
    def status(self) -> LandStatus:
        if self.recommended is None:
            return LandStatus.UNKNOWN
        difference = self.effective - self.recommended
        if difference < -LAND_TOLERANCE:
            return LandStatus.TOO_FEW
        if difference > LAND_TOLERANCE:
            return LandStatus.TOO_MANY
        return LandStatus.OK


@dataclass(frozen=True, slots=True)
class Requirement:
    """The coloured sources one card needs to be cast on curve.

    `colours` is the set of colours that can pay: {"R"}, or {"W", "U"} for a hybrid
    pip or for the "either colour" check on a gold card.
    """

    colours: Pip
    card: str
    mana_cost: str
    turn: int
    required: int
    available: float

    @property
    def shortfall(self) -> float:
        return max(0.0, self.required - self.available)

    @property
    def met(self) -> bool:
        return self.shortfall == 0


@dataclass(frozen=True, slots=True)
class HandOdds:
    library_size: int
    lands: int
    opening_lands: tuple[float, ...]  # [k] = chance of exactly k lands in the opening 7
    keepable: float  # chance of 2-5 lands in the opening 7
    land_drops: tuple[tuple[int, float, float], ...]  # (turn, on the play, on the draw)


@dataclass(frozen=True, slots=True)
class DeckAnalysis:
    format: DeckFormat
    library_size: int
    curve: dict[int, int]  # mana value (CURVE_TOP means "7+") -> nonland cards
    average_mana_value: float
    pips: dict[str, float]  # colour -> coloured pips in the deck
    sources: dict[str, float]  # colour -> lands (incl. MDFCs) that make it
    land_check: LandCheck
    requirements: list[Requirement]  # the hardest card for each colour (set)
    hand: HandOdds

    @property
    def pip_share(self) -> dict[str, float]:
        total = sum(self.pips.values())
        return {c: n / total for c, n in self.pips.items()} if total else {}


# ---------- reading card text ----------


def card_text(card: Card) -> str:
    """Lower-case rules text of the side you'd cast (both sides for split/adventure)."""
    if card.is_mdfc_land:
        return card.faces[0].oracle_text.lower()
    if card.faces:
        return "\n".join(f.oracle_text for f in card.faces).lower()
    return card.oracle_text.lower()


def _front_type_line(card: Card) -> str:
    return (card.faces[0].type_line if card.faces else card.type_line).lower()


_DRAW_PHRASES = (
    "draw a card",
    "draw two cards",
    "draw three cards",
    "draws cards",
    "draws two cards",
    "draws three cards",
)
# "cycling {1}" or "cycling {R}" but not "cycling {2}" or "landcycling {1}"
_ONE_MANA_CYCLING_RE = re.compile(r"(?<![a-z])cycling \{(?:1|[wubrgc]|[wubrg]/[wubrgp])\}(?!\{)")


def is_cheap_draw(card: Card) -> bool:
    """Karsten's "cheap card draw spell", by his text rules (see the land-count
    article): a nonland card of mana value 2 or less that draws or digs, or any
    nonland card that cycles for one mana."""
    if card.is_land:
        return False
    text = card_text(card)
    if _ONE_MANA_CYCLING_RE.search(text):
        return True
    if card.mana_value > 2:
        return False
    creature = "creature" in _front_type_line(card)
    draws = (
        any(p in text for p in _DRAW_PHRASES)
        and not any(x in text for x in ("{4}", "blood token", "investigate"))
        and (not creature or ("when" in text and "enters" in text))
    )
    digs = (
        not creature
        and all(w in text for w in ("look", "library", "put", "your hand"))
        and "pay " not in text
        and "pays" not in text
    )
    return draws or digs


def is_cheap_ramp(card: Card) -> bool:
    """Karsten's "cheap mana ramp spell": nonland, mana value 2 or less, adds mana or
    fetches lands, by his text rules. (Cards already counted as draw don't count.)"""
    if card.is_land or card.mana_value > 2 or is_cheap_draw(card):
        return False
    text = card_text(card)
    creature = "creature" in _front_type_line(card)
    adds = (
        "add " in text
        and "add its ability" not in text
        and "add a lore counter" not in text
        and not (creature and "dies" in text)
    )
    fetches = (
        "search" in text
        and "your library" in text
        and ("land" in text or "basic" in text)
        and "sacrifice" not in text
    )
    doubles = "enchanted land is tapped" in text and "adds an additional" in text
    cheats = "put a creature card with" in text and "from your hand onto the battlefield" in text
    return adds or fetches or doubles or cheats


def mdfc_land_weight(card: Card) -> float:
    """How much of a land a land/spell MDFC counts as (0 for anything else)."""
    if not card.is_mdfc_land:
        return 0.0
    if card.rarity == "mythic":
        return karsten.MYTHIC_MDFC_LAND_WEIGHT
    return karsten.MDFC_LAND_WEIGHT


# ---------- mana sources ----------

_BASIC_TYPES = {"plains": "W", "island": "U", "swamp": "B", "mountain": "R", "forest": "G"}
_ALWAYS_TAPPED_RE = re.compile(r"enters (?:the battlefield )?tapped|onto the battlefield tapped")
_CONDITIONAL_UNTAPPED = ("unless", "if you don't", "you may pay")


def _land_text(card: Card) -> str:
    """Rules text of the land side (the back of a spell/land MDFC)."""
    if card.is_mdfc_land:
        return card.faces[1].oracle_text.lower()
    return card_text(card) if not card.faces else card.faces[0].oracle_text.lower()


def land_colours(card: Card) -> frozenset[str]:
    """Colours a land can make, including what a fetchland can fetch: any colour for
    "basic land" fetches (Evolving Wilds), named types for the rest (Wooded Foothills)."""
    colours = set(card.produced_mana) & set(SOURCE_COLOURS)
    text = _land_text(card)
    if "search your library for" in text:
        if "basic land" in text:
            colours |= set(_BASIC_TYPES.values())
        colours |= {c for name, c in _BASIC_TYPES.items() if name in text}
    return frozenset(colours)


def enters_untapped(card: Card) -> bool:
    """True unless the land always enters tapped. Conditional taplands ("unless you
    control...", shocklands) count as untapped."""
    text = _land_text(card)
    return not _ALWAYS_TAPPED_RE.search(text) or any(c in text for c in _CONDITIONAL_UNTAPPED)


@dataclass(frozen=True, slots=True)
class _Source:
    quantity: int
    colours: frozenset[str]
    weight: float
    min_mana_value: int  # only helps cast spells of at least this mana value
    is_land: bool = False
    untapped: bool = True


def _mana_sources(library: Iterable[ResolvedEntry]) -> list[_Source]:
    sources: list[_Source] = []
    for r in library:
        card, quantity = r.card, r.entry.quantity
        if card.is_land or card.is_mdfc_land:
            colours = land_colours(card)
            if colours:
                sources.append(_Source(quantity, colours, 1.0, 0, True, enters_untapped(card)))
        elif card.produced_mana:
            front = _front_type_line(card)
            colours = frozenset(card.produced_mana) & frozenset(SOURCE_COLOURS)
            if "creature" in front:
                sources.append(_Source(quantity, colours, DORK_WEIGHT, DORK_MIN_MANA_VALUE))
            elif "artifact" in front:
                sources.append(_Source(quantity, colours, ROCK_WEIGHT, ROCK_MIN_MANA_VALUE))
    return sources


def _available(sources: list[_Source], colours: Pip, mana_value: int) -> float:
    """Sources able to pay one of `colours` for a spell cast on turn `mana_value`.
    On turn one only untapped lands help."""
    total = 0.0
    for s in sources:
        if not s.colours & colours or mana_value < s.min_mana_value:
            continue
        if mana_value <= 1 and not s.untapped:
            continue
        total += s.quantity * s.weight
    return total


# ---------- colour requirements ----------


def casting_turn(cost: ManaCost) -> int:
    """The turn a spell is cast on curve: its mana value, with X = ASSUMED_X."""
    return cost.mana_value + ASSUMED_X * cost.x_count


def cost_requirements(cost: ManaCost, column: int) -> dict[Pip, int]:
    """Sources needed per colour (set) to cast a cost on curve.

    Gold costs follow Karsten: each colour is looked up on its own (the other
    colours' pips counting as generic), plus "any of these colours" for all the
    pips together, and every requirement goes up by one.
    """
    if not cost.pips:
        return {}
    m = casting_turn(cost)
    if len(cost.pips) == 1:
        [(colours, n)] = cost.pips.items()
        return {colours: karsten.sources_required(m - n, n, column)}

    extra = karsten.GOLD_EXTRA
    needs = {
        colours: karsten.sources_required(m - n, n, column) + extra
        for colours, n in cost.pips.items()
    }
    either: Pip = frozenset().union(*cost.pips)
    total = cost.pip_count
    needs[either] = max(
        needs.get(either, 0), karsten.sources_required(m - total, total, column) + extra
    )
    return needs


def _requirements(
    spells: Iterable[ResolvedEntry], sources: list[_Source], column: int
) -> list[Requirement]:
    """The hardest requirement for each colour (set): biggest shortfall, then most
    sources needed."""
    worst: dict[Pip, Requirement] = {}
    for r in spells:
        for cost in parse_face_costs(r.card.mana_cost):
            turn = casting_turn(cost)
            for colours, required in cost_requirements(cost, column).items():
                req = Requirement(
                    colours,
                    r.card.name,
                    r.card.mana_cost,
                    turn,
                    required,
                    _available(sources, colours, turn),
                )
                current = worst.get(colours)
                if current is None or (req.shortfall, req.required) > (
                    current.shortfall,
                    current.required,
                ):
                    worst[colours] = req
    order = {c: i for i, c in enumerate(SOURCE_COLOURS)}
    return sorted(
        worst.values(), key=lambda q: (len(q.colours), sorted(order[c] for c in q.colours))
    )


# ---------- the whole analysis ----------


def _curve(spells: Iterable[ResolvedEntry]) -> dict[int, int]:
    curve = dict.fromkeys(range(CURVE_TOP + 1), 0)
    for r in spells:
        curve[min(int(r.card.mana_value), CURVE_TOP)] += r.entry.quantity
    return curve


def _hand_odds(library_size: int, lands: int, commander: bool) -> HandOdds:
    opening = tuple(
        prob_exactly(k, lands, library_size, OPENING_HAND) for k in range(OPENING_HAND + 1)
    )
    keepable = sum(opening[k] for k in KEEPABLE_LANDS)
    drops = []
    for turn in LAND_DROP_TURNS:
        # In multiplayer Commander the starting player still draws on turn one.
        play = prob_at_least(turn, lands, library_size, cards_seen(turn, on_play=not commander))
        draw = prob_at_least(turn, lands, library_size, cards_seen(turn, on_play=False))
        drops.append((turn, play, draw))
    return HandOdds(library_size, lands, opening, keepable, tuple(drops))


def analyse(deck: Deck, resolved: list[ResolvedEntry]) -> DeckAnalysis:
    """Analyse a deck. `resolved` comes from parser.resolve_cards; cards that didn't
    resolve still count towards the library size but are otherwise left out."""
    fmt = deck.format
    commander = fmt == DeckFormat.COMMANDER
    library_size = deck.total_cards(Section.MAINBOARD)

    library = [r for r in resolved if r.entry.section == Section.MAINBOARD]
    commanders = [r for r in resolved if r.entry.section == Section.COMMANDER]
    library_spells = [r for r in library if not r.card.is_land]
    all_spells = library_spells + [r for r in commanders if not r.card.is_land]

    spell_count = sum(r.entry.quantity for r in library_spells)
    average = (
        sum(r.card.mana_value * r.entry.quantity for r in library_spells) / spell_count
        if spell_count
        else 0.0
    )

    pips: Counter[str] = Counter()
    for r in all_spells:
        for cost in parse_face_costs(r.card.mana_cost):
            for colour, n in cost.colour_weights().items():
                pips[colour] += n * r.entry.quantity

    sources = _mana_sources(library)
    land_sources = [s for s in sources if s.is_land]
    colour_sources = {
        c: sum(s.quantity for s in land_sources if c in s.colours) for c in SOURCE_COLOURS
    }

    lands = sum(r.entry.quantity for r in library if r.card.is_land)
    mdfcs = sum(r.entry.quantity for r in library if r.card.is_mdfc_land)
    mdfc_value = sum(r.entry.quantity * mdfc_land_weight(r.card) for r in library)
    cheap = sum(
        r.entry.quantity for r in library_spells if is_cheap_draw(r.card) or is_cheap_ramp(r.card)
    )
    recommended = (
        None
        if fmt == DeckFormat.UNKNOWN
        else karsten.recommended_lands(
            average,
            cheap,
            library_size,
            companion=bool(deck.section(Section.COMPANION)),
            commander=commander,
        )
    )

    requirements = (
        []
        if fmt == DeckFormat.UNKNOWN
        else _requirements(all_spells, sources, karsten.deck_size_column(library_size, commander))
    )

    return DeckAnalysis(
        format=fmt,
        library_size=library_size,
        curve=_curve(library_spells),
        average_mana_value=average,
        pips={c: n for c, n in pips.items() if n},
        sources={c: n for c, n in colour_sources.items() if n},
        land_check=LandCheck(lands, mdfcs, mdfc_value, cheap, recommended),
        requirements=requirements,
        hand=_hand_odds(library_size, lands + mdfcs, commander),
    )
