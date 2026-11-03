"""Frank Karsten's published guidelines for land counts and coloured sources.

Sources:
- Lands: "How Many Lands Do You Need in Your Deck? An Updated Analysis" (2022)
  https://www.tcgplayer.com/content/article/How-Many-Lands-Do-You-Need-in-Your-Deck-An-Updated-Analysis/cd1c1a24-d439-4a8e-b369-b936edb0b38a/
- Sources: "How Many Sources Do You Need to Consistently Cast Your Spells? A 2022 Update"
  https://www.tcgplayer.com/content/article/How-Many-Sources-Do-You-Need-to-Consistently-Cast-Your-Spells-A-2022-Update/dc23a7d2-0a16-4c0b-ad36-586fcca03ad8/

The source table answers: to cast a spell on curve (turn = its mana value) about
89 + mana value percent of the time, given enough lands, how many sources of its
colour does the deck need? Rows are keyed by (generic mana, coloured pips): Wrath of
God, {2}{W}{W}, is the row (2, 2).
"""

from __future__ import annotations

# Columns of SOURCES_REQUIRED, by deck size.
DECK_SIZES = (60, 80, 99, 40)

# (generic, pips) -> sources needed in a (60, 80, 99, 40)-card deck. Copied verbatim
# from the summary table of the 2022 sources article.
SOURCES_REQUIRED: dict[tuple[int, int], tuple[int, int, int, int]] = {
    (5, 1): (9, 12, 14, 6),  # Drowner of Hope
    (4, 1): (9, 14, 15, 6),  # Doubling Season
    (3, 1): (10, 15, 16, 7),  # Collected Company
    (2, 1): (12, 16, 18, 8),  # Reckless Stormseeker
    (5, 2): (12, 17, 20, 8),  # Hullbreaker Horror
    (1, 1): (13, 18, 19, 9),  # Ledger Shredder
    (4, 2): (13, 19, 22, 9),  # Primeval Titan
    (0, 1): (14, 19, 19, 9),  # Monastery Swiftspear
    (3, 2): (15, 20, 23, 10),  # Baneslayer Angel
    (4, 3): (16, 22, 26, 10),  # Nyxbloom Ancient
    (2, 2): (16, 23, 26, 11),  # Wrath of God
    (3, 3): (17, 24, 28, 11),  # Massacre Wurm
    (1, 2): (18, 25, 28, 12),  # Narset, Parter of Veils
    (2, 3): (19, 26, 30, 13),  # Garruk, Primal Hunter
    (0, 2): (21, 28, 30, 14),  # Lord of Atlantis
    (1, 3): (21, 29, 33, 14),  # Cryptic Command
    (1, 4): (22, 31, 36, 15),  # Unnatural Growth
    (0, 3): (23, 32, 36, 16),  # Goblin Chainwhirler
    (0, 4): (24, 34, 39, 17),  # Dawn Elemental
}

# Largest generic amount in the table for each pip count. More generic mana only
# makes a spell easier to cast on curve, so beyond these we reuse the last row.
_MAX_GENERIC = {1: 5, 2: 5, 3: 4, 4: 1}
MAX_PIPS = 4

# Gold cards need every colour at once, so Karsten adds one to each requirement.
GOLD_EXTRA = 1

# How much of a land a land/spell MDFC is worth, from the land-count article's
# regression (the formula below was fitted counting MDFCs this way). Mythic MDFCs
# enter untapped more easily, so they're closer to real lands.
MDFC_LAND_WEIGHT = 0.38
MYTHIC_MDFC_LAND_WEIGHT = 0.74

# Land-count formula coefficients (60-card regression).
LANDS_BASE = 19.59
LANDS_PER_MANA_VALUE = 1.90
LANDS_PER_CHEAP_SPELL = -0.28
LANDS_FOR_COMPANION = 0.27
# 99-card version: 60-card formula scaled to 99 cards, minus 1.35 lands for the
# free mulligan and free first-turn draw, treating the commander as a companion.
COMMANDER_BASE = 31.42
COMMANDER_PER_MANA_VALUE = 3.13


def deck_size_column(library_size: int, commander: bool) -> int:
    """Which column of SOURCES_REQUIRED fits a deck: the nearest published size."""
    if commander:
        return DECK_SIZES.index(99)
    if library_size < 50:
        return DECK_SIZES.index(40)
    if library_size < 70:
        return DECK_SIZES.index(60)
    return DECK_SIZES.index(80)


def sources_required(generic: int, pips: int, column: int) -> int:
    """Sources needed for a spell with this many generic and coloured symbols.

    Costs beyond the table are clamped to the nearest row: extra generic mana uses
    the largest listed amount, and more than four pips use the four-pip rows.
    """
    if pips <= 0:
        return 0
    pips = min(pips, MAX_PIPS)
    generic = max(0, min(generic, _MAX_GENERIC[pips]))
    return SOURCES_REQUIRED[(generic, pips)][column]


def recommended_lands(
    average_mana_value: float,
    cheap_draw_or_ramp: int,
    library_size: int,
    *,
    companion: bool = False,
    commander: bool = False,
) -> float:
    """Recommended land count, counting land/spell MDFCs as partial lands.

    For 60 cards this is Karsten's regression. Other non-Commander sizes are scaled
    by size/60, the way he ports it to 80-card decks; for 40-card Limited decks that
    gives about 17 lands at average mana value 3, matching his usual Limited advice.
    """
    cheap = LANDS_PER_CHEAP_SPELL * cheap_draw_or_ramp
    if commander:
        return COMMANDER_BASE + COMMANDER_PER_MANA_VALUE * average_mana_value + cheap
    base = LANDS_BASE + LANDS_PER_MANA_VALUE * average_mana_value
    if companion:
        base += LANDS_FOR_COMPANION
    return library_size / 60 * base + cheap
