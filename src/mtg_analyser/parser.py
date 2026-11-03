"""Turn decklist text into a Deck, then match its names to real cards.

The two steps are separate so parsing can be tested without any card data:

1. `parse_decklist(text)` -> (Deck, problems). Pure text handling (FR-1 to FR-3).
2. `resolve_cards(deck, db)` -> (resolved entries, problems). Looks each name up in
   the CardDatabase and reports unknown names with suggestions (FR-5).

Lines the parser understands:
    4 Lightning Bolt                  plain
    4x Lightning Bolt                 "x" after the quantity
    4 Lightning Bolt (M10) 146        Arena/MTGO export: set code and collector number
    1 Lightning Bolt (2X2) 117 *F*    foil mark
    SB: 2 Duress                      MTGO-style sideboard line
    Sideboard / SIDEBOARD: / deck     section headers (any case, optional colon)
    // comment   # comment            ignored

Blank lines separate groups of cards. In a list with no headers at all (MTGO and
older Arena exports), a single blank line followed by at most 15 cards marks the
sideboard; otherwise blank lines are just spacing.
"""

from __future__ import annotations

import re
from pathlib import Path

from mtg_analyser.card_db import CardDatabase
from mtg_analyser.models import Deck, DeckEntry, DeckProblem, ResolvedEntry, Section

# Header word -> section. None means "skip lines until the next header": Arena
# exports start with an "About" block holding "Name <deck name>".
HEADERS: dict[str, Section | None] = {
    "deck": Section.MAINBOARD,
    "main": Section.MAINBOARD,
    "mainboard": Section.MAINBOARD,
    "sideboard": Section.SIDEBOARD,
    "commander": Section.COMMANDER,
    "companion": Section.COMPANION,
    "about": None,
}

MAX_SIDEBOARD = 15

HEADER_RE = re.compile(r"^(?P<word>[A-Za-z]+)\s*:?$")
SIDEBOARD_PREFIX_RE = re.compile(r"^SB:\s*", re.IGNORECASE)
CARD_LINE_RE = re.compile(
    r"""
    ^(?P<quantity>\d+)\s*[xX]?\s+   # 4 / 4x / 4 x
    (?P<name>.+?)                   # the name (lazy, so it leaves the extras below alone)
    (?:\s+\([A-Za-z0-9]{2,6}\)      # (M10) set code...
       (?:\s+[^\s*]+)?              # ...and optional collector number like 146 or 12a
    )?
    (?:\s+\*[A-Za-z]+\*)?           # *F* foil / *E* etched mark
    $
    """,
    re.VERBOSE,
)


def is_comment(line: str) -> bool:
    return line.startswith(("//", "#"))


def header_section(line: str) -> tuple[bool, Section | None]:
    """(True, section) if the line is a section header, else (False, None)."""
    match = HEADER_RE.match(line)
    if match and (word := match["word"].lower()) in HEADERS:
        return True, HEADERS[word]
    return False, None


def parse_decklist(text: str) -> tuple[Deck, list[DeckProblem]]:
    """Parse decklist text. Never raises on bad lines; they come back as problems."""
    # Tidy each line: unusual spaces (tabs, non-breaking) become single spaces.
    lines = [" ".join(raw.split()) for raw in text.splitlines()]
    has_headers = any(header_section(line)[0] or SIDEBOARD_PREFIX_RE.match(line) for line in lines)

    entries: list[DeckEntry] = []
    problems: list[DeckProblem] = []
    section: Section | None = Section.MAINBOARD
    blocks: list[list[int]] = [[]]  # indexes into entries, split at blank lines

    for line_number, line in enumerate(lines, start=1):
        if not line:
            if blocks[-1]:
                blocks.append([])
            continue
        if is_comment(line):
            continue

        is_header, new_section = header_section(line)
        if is_header:
            section = new_section
            continue
        if section is None:  # inside an "About" block
            continue

        entry_section = section
        if prefix := SIDEBOARD_PREFIX_RE.match(line):
            entry_section = Section.SIDEBOARD
            line = line[prefix.end() :]

        match = CARD_LINE_RE.match(line)
        if not match:
            problems.append(
                DeckProblem(
                    line_number,
                    line,
                    "Couldn't read this line; expected a quantity and name, "
                    "like '4 Lightning Bolt'.",
                )
            )
            continue
        quantity = int(match["quantity"])
        if quantity == 0:
            problems.append(DeckProblem(line_number, line, "Quantity is 0."))
            continue

        blocks[-1].append(len(entries))
        entries.append(DeckEntry(quantity, match["name"], entry_section, line_number))

    if not has_headers:
        _split_off_sideboard(entries, [b for b in blocks if b])
    return Deck(entries), problems


def _split_off_sideboard(entries: list[DeckEntry], blocks: list[list[int]]) -> None:
    """For a headerless list of exactly two blocks, make the second the sideboard
    if it's small enough to be one. Changes `entries` in place."""
    if len(blocks) != 2:
        return
    second = blocks[1]
    if sum(entries[i].quantity for i in second) > MAX_SIDEBOARD:
        return
    for i in second:
        e = entries[i]
        entries[i] = DeckEntry(e.quantity, e.name, Section.SIDEBOARD, e.line_number)


def read_decklist(path: Path) -> tuple[Deck, list[DeckProblem]]:
    """Parse a decklist file (FR-1). Accepts UTF-8 (with or without a BOM, as
    Notepad writes it), falling back to Windows-1252 for older files."""
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1252", errors="replace")
    return parse_decklist(text)


def resolve_cards(deck: Deck, db: CardDatabase) -> tuple[list[ResolvedEntry], list[DeckProblem]]:
    """Match every entry to a card. Unknown names become problems with
    "did you mean" suggestions (FR-5); the rest of the deck still resolves."""
    resolved: list[ResolvedEntry] = []
    problems: list[DeckProblem] = []
    for entry in deck.entries:
        card = db.find(entry.name)
        if card is None:
            problems.append(
                DeckProblem(
                    entry.line_number,
                    entry.name,
                    f"Unknown card: {entry.name!r}.",
                    tuple(db.suggest(entry.name)),
                )
            )
        else:
            resolved.append(ResolvedEntry(entry, card))
    return resolved, problems
