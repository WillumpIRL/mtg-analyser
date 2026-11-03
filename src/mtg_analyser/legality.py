"""Basic deck-construction checks: deck size, copy limits and Commander colour identity.

These are notes, not a full legality check: ban lists and which sets a format
allows are not checked.

Rules used, by guessed format:
- Limited: at least 40 cards.
- Constructed: at least 60 cards, at most 4 copies of a card across main deck and
  sideboard, at most 15 sideboard cards.
- Commander: exactly 100 cards including the commander, one copy of each card, and
  every card within the commander's colour identity.
Basic lands, and cards that say "A deck can have any number of cards named ..."
(or "up to seven"), are exempt from copy limits.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from mtg_analyser.mana import colour_key
from mtg_analyser.models import Card, Deck, DeckFormat, ResolvedEntry, Section

CONSTRUCTED_COPY_LIMIT = 4
SIDEBOARD_LIMIT = 15
COMMANDER_DECK_SIZE = 100

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}
_ANY_NUMBER_RE = re.compile(r"a deck can have any number of cards named")
_UP_TO_RE = re.compile(r"a deck can have up to (\w+) cards named")


@dataclass(frozen=True, slots=True)
class LegalityNote:
    """One thing that breaks a deck-construction rule, with the cards involved."""

    message: str
    cards: tuple[str, ...] = ()


def copy_limit(card: Card, normal_limit: int) -> int | None:
    """How many copies of a card a deck may hold; None means any number."""
    if "Basic" in card.type_line:
        return None
    text = card.oracle_text.lower()
    if _ANY_NUMBER_RE.search(text):
        return None
    if match := _UP_TO_RE.search(text):
        word = match[1]
        return int(word) if word.isdigit() else _NUMBER_WORDS.get(word, normal_limit)
    return normal_limit


def _over_limit(entries: Iterable[ResolvedEntry], normal_limit: int) -> list[tuple[str, int]]:
    """(card name, copies) for every card with more copies than it's allowed."""
    copies: Counter[str] = Counter()
    cards: dict[str, Card] = {}
    for r in entries:
        copies[r.card.name] += r.entry.quantity
        cards[r.card.name] = r.card
    over = []
    for name, count in copies.items():
        limit = copy_limit(cards[name], normal_limit)
        if limit is not None and count > limit:
            over.append((name, count))
    return over


def check_deck(deck: Deck, resolved: list[ResolvedEntry]) -> list[LegalityNote]:
    """Deck-construction notes for the deck's guessed format (empty if all is well)."""
    fmt = deck.format
    total = deck.total_cards()
    notes: list[LegalityNote] = []

    # The format is guessed from the size, so Limited and Constructed decks always
    # meet their minimums; only Commander's exact size and tiny decks need a note.
    if fmt == DeckFormat.UNKNOWN:
        notes.append(
            LegalityNote(
                f"Only {total} cards: too few for any format "
                f"(Limited needs {DeckFormat.LIMITED.min_deck_size})."
            )
        )
    elif fmt == DeckFormat.COMMANDER and total != COMMANDER_DECK_SIZE:
        notes.append(
            LegalityNote(
                f"Commander decks have exactly {COMMANDER_DECK_SIZE} cards, "
                f"including the commander; this one has {total}."
            )
        )

    if fmt == DeckFormat.CONSTRUCTED:
        playable = [
            r
            for r in resolved
            if r.entry.section in (Section.MAINBOARD, Section.SIDEBOARD, Section.COMPANION)
        ]
        for name, count in _over_limit(playable, CONSTRUCTED_COPY_LIMIT):
            notes.append(
                LegalityNote(
                    f"{count} copies of {name}; Constructed allows {CONSTRUCTED_COPY_LIMIT} "
                    "(main deck and sideboard together).",
                    (name,),
                )
            )
        sideboard = deck.total_cards(Section.SIDEBOARD)
        if sideboard > SIDEBOARD_LIMIT:
            notes.append(
                LegalityNote(f"Sideboard has {sideboard} cards; the limit is {SIDEBOARD_LIMIT}.")
            )

    if fmt == DeckFormat.COMMANDER:
        in_deck = [r for r in resolved if r.entry.section in (Section.MAINBOARD, Section.COMMANDER)]
        for name, count in _over_limit(in_deck, 1):
            notes.append(
                LegalityNote(f"{count} copies of {name}; Commander is singleton.", (name,))
            )
        notes.extend(_colour_identity_notes(resolved))

    return notes


def _colour_identity_notes(resolved: list[ResolvedEntry]) -> list[LegalityNote]:
    commanders = [r.card for r in resolved if r.entry.section == Section.COMMANDER]
    if not commanders:
        return [LegalityNote("No Commander section, so colour identity wasn't checked.")]
    identity = set().union(*(c.color_identity for c in commanders))
    outside = sorted(
        {
            r.card.name
            for r in resolved
            if r.entry.section == Section.MAINBOARD and not set(r.card.color_identity) <= identity
        }
    )
    if not outside:
        return []
    shown = colour_key(identity) or "colourless"
    return [
        LegalityNote(
            f"{len(outside)} card(s) outside the commander's colour identity ({shown}).",
            tuple(outside),
        )
    ]
