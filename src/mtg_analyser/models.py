"""Data models for cards and decks.

We keep only the Scryfall fields this project needs, so the local cache stays small
and loads fast. `Card.from_scryfall` turns one raw Scryfall card object into a Card.

A `Deck` is what the parser produces from a decklist: card names and quantities,
not yet matched to Cards. `ResolvedEntry` pairs an entry with its Card once matched.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

# Scryfall layouts that are not real deck cards (tokens, art cards, etc.).
NON_DECK_LAYOUTS = frozenset(
    {
        "token",
        "double_faced_token",
        "emblem",
        "art_series",
        "planar",
        "scheme",
        "vanguard",
    }
)

# Layouts where each face is played separately (two faces, two mana costs).
MULTI_FACE_LAYOUTS = frozenset(
    {"split", "flip", "adventure", "transform", "modal_dfc", "meld", "reversible_card"}
)


@dataclass(frozen=True, slots=True)
class CardFace:
    """One face of a multi-faced card (e.g. one half of a split card)."""

    name: str
    mana_cost: str = ""
    type_line: str = ""
    colors: tuple[str, ...] = ()
    oracle_text: str = ""

    @property
    def is_land(self) -> bool:
        return "Land" in self.type_line

    @classmethod
    def from_scryfall(cls, data: dict[str, Any]) -> CardFace:
        return cls(
            name=data["name"],
            mana_cost=data.get("mana_cost", ""),
            type_line=data.get("type_line", ""),
            colors=tuple(data.get("colors", ())),
            oracle_text=data.get("oracle_text", ""),
        )


@dataclass(frozen=True, slots=True)
class Card:
    """A single Magic card, as far as deck analysis cares.

    Attributes:
        name: Full Oracle name, e.g. "Fire // Ice" for split cards.
        mana_cost: Mana cost string like "{1}{R}". For multi-faced cards whose faces
            have separate costs (transform, MDFC), this is the FRONT face's cost.
        mana_value: Scryfall's `cmc` (what the rules call mana value).
        colors: Card colours, e.g. ("R",). Empty for colourless.
        color_identity: Commander colour identity.
        type_line: Full type line, e.g. "Creature — Human Wizard".
        produced_mana: Colours of mana this card can produce, e.g. ("G",) for Forest.
        layout: Scryfall layout, e.g. "normal", "split", "modal_dfc".
        faces: The card's faces, if it has more than one.
    """

    name: str
    mana_cost: str
    mana_value: float
    colors: tuple[str, ...]
    color_identity: tuple[str, ...]
    type_line: str
    produced_mana: tuple[str, ...] = ()
    oracle_text: str = ""
    layout: str = "normal"
    faces: tuple[CardFace, ...] = field(default_factory=tuple)

    # ---------- handy properties ----------

    @property
    def front_face(self) -> CardFace | None:
        return self.faces[0] if self.faces else None

    @property
    def is_land(self) -> bool:
        """True if the card is a land when you play it normally (its front face)."""
        front = self.front_face
        return front.is_land if front else "Land" in self.type_line

    @property
    def is_mdfc_land(self) -> bool:
        """True for modal double-faced cards with a spell front and a land back."""
        return (
            self.layout == "modal_dfc"
            and len(self.faces) == 2
            and not self.faces[0].is_land
            and self.faces[1].is_land
        )

    @property
    def has_x_cost(self) -> bool:
        return "{X}" in self.mana_cost

    # ---------- converting to and from dicts ----------

    @classmethod
    def from_scryfall(cls, data: dict[str, Any]) -> Card:
        """Build a Card from one raw Scryfall card object."""
        raw_faces = data.get("card_faces", [])
        faces = tuple(CardFace.from_scryfall(f) for f in raw_faces)

        # Transform and MDFC cards have no top-level mana_cost or colors; the
        # front face has them instead.
        mana_cost = data.get("mana_cost")
        if mana_cost is None:
            mana_cost = faces[0].mana_cost if faces else ""

        colors = data.get("colors")
        if colors is None:
            colors = faces[0].colors if faces else ()

        return cls(
            name=data["name"],
            mana_cost=mana_cost,
            mana_value=float(data.get("cmc", 0.0)),
            colors=tuple(colors),
            color_identity=tuple(data.get("color_identity", ())),
            type_line=data.get("type_line", ""),
            produced_mana=tuple(data.get("produced_mana", ())),
            oracle_text=data.get("oracle_text", ""),
            layout=data.get("layout", "normal"),
            faces=faces,
        )

    def to_dict(self) -> dict[str, Any]:
        """Plain dict for saving to the JSON cache."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Card:
        """Rebuild a Card from `to_dict` output."""
        faces = tuple(
            CardFace(**{**f, "colors": tuple(f.get("colors", ()))}) for f in data.get("faces", ())
        )
        return cls(
            name=data["name"],
            mana_cost=data.get("mana_cost", ""),
            mana_value=float(data.get("mana_value", 0.0)),
            colors=tuple(data.get("colors", ())),
            color_identity=tuple(data.get("color_identity", ())),
            type_line=data.get("type_line", ""),
            produced_mana=tuple(data.get("produced_mana", ())),
            oracle_text=data.get("oracle_text", ""),
            layout=data.get("layout", "normal"),
            faces=faces,
        )


# ---------- decks ----------


class Section(StrEnum):
    """Which part of a decklist a card belongs to (FR-3)."""

    COMMANDER = "commander"
    COMPANION = "companion"
    MAINBOARD = "mainboard"
    SIDEBOARD = "sideboard"


# FR-4: these sections are analysed; the others are kept but set aside.
ANALYSED_SECTIONS = frozenset({Section.COMMANDER, Section.MAINBOARD})


class DeckFormat(StrEnum):
    """Format guessed from the deck's size."""

    LIMITED = "limited"
    CONSTRUCTED = "constructed"
    COMMANDER = "commander"
    UNKNOWN = "unknown"

    @property
    def min_deck_size(self) -> int:
        """Smallest legal deck for the format (0 if unknown)."""
        return _MIN_DECK_SIZE.get(self, 0)


_MIN_DECK_SIZE = {DeckFormat.LIMITED: 40, DeckFormat.CONSTRUCTED: 60, DeckFormat.COMMANDER: 100}


@dataclass(frozen=True, slots=True)
class DeckEntry:
    """One decklist line, e.g. `4 Lightning Bolt` -> DeckEntry(4, "Lightning Bolt")."""

    quantity: int
    name: str
    section: Section = Section.MAINBOARD
    line_number: int = 0


@dataclass(slots=True)
class Deck:
    """A parsed decklist. Entries keep their original order and line numbers."""

    entries: list[DeckEntry] = field(default_factory=list)

    def section(self, section: Section) -> list[DeckEntry]:
        return [e for e in self.entries if e.section == section]

    def mainboard(self) -> list[DeckEntry]:
        return self.section(Section.MAINBOARD)

    def sideboard(self) -> list[DeckEntry]:
        return self.section(Section.SIDEBOARD)

    def commanders(self) -> list[DeckEntry]:
        return self.section(Section.COMMANDER)

    def analysed(self) -> list[DeckEntry]:
        """The cards analysis looks at: mainboard plus commander (FR-4)."""
        return [e for e in self.entries if e.section in ANALYSED_SECTIONS]

    def total_cards(self, section: Section | None = None) -> int:
        """Card count for one section, or for the analysed cards if none is given."""
        entries = self.section(section) if section else self.analysed()
        return sum(e.quantity for e in entries)

    @property
    def format(self) -> DeckFormat:
        """Guess the format: a commander or exactly 100 cards means Commander,
        60+ means Constructed, 40+ means Limited."""
        total = self.total_cards()
        if self.commanders() or total == 100:
            return DeckFormat.COMMANDER
        if total >= 60:
            return DeckFormat.CONSTRUCTED
        if total >= 40:
            return DeckFormat.LIMITED
        return DeckFormat.UNKNOWN


@dataclass(frozen=True, slots=True)
class ResolvedEntry:
    """A deck entry matched to its card in the database."""

    entry: DeckEntry
    card: Card


@dataclass(frozen=True, slots=True)
class DeckProblem:
    """A decklist line that couldn't be used, with the reason (FR-5)."""

    line_number: int
    line: str
    message: str
    suggestions: tuple[str, ...] = ()
