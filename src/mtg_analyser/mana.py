"""Read mana costs like "{2}{R}{R}" or "{1}{W/U}{G/P}".

A cost's coloured requirements are kept as "pips" keyed by the colours that can pay
them: {R} is frozenset({"R"}), and the hybrid {W/U} is frozenset({"W", "U"}). Keying
hybrid pips this way lets the colour checks treat "W or U" like any other colour
requirement, using the sources that make either colour.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field

COLOURS = ("W", "U", "B", "R", "G")
# Colourless {C} must be paid with colourless mana, so it's checked like a colour.
SOURCE_COLOURS = (*COLOURS, "C")

Pip = frozenset[str]

_SYMBOL_RE = re.compile(r"\{([^}]+)\}")


@dataclass(frozen=True, slots=True)
class ManaCost:
    """A parsed mana cost.

    Attributes:
        mana_value: Total mana value, counting X as 0 (as the rules do off the stack).
        pips: Coloured requirements, e.g. {frozenset({"R"}): 2} for {R}{R}.
        x_count: Number of {X} symbols ({X}{X}{R} has 2).

    Phyrexian ({R/P}), "twobrid" ({2/W}) and snow ({S}) symbols add to the mana value
    but not to pips: they can be paid without that colour, so they don't make
    colour demands on the mana base.
    """

    mana_value: int = 0
    pips: dict[Pip, int] = field(default_factory=dict)
    x_count: int = 0

    @property
    def has_x(self) -> bool:
        return self.x_count > 0

    @property
    def pip_count(self) -> int:
        return sum(self.pips.values())

    def colour_weights(self) -> Counter[str]:
        """Pips per single colour, splitting hybrid pips evenly ({W/U} = 0.5 W + 0.5 U)."""
        weights: Counter[str] = Counter()
        for pip, count in self.pips.items():
            for colour in pip:
                weights[colour] += count / len(pip)
        return weights


COLOUR_NAMES = {
    "W": "White",
    "U": "Blue",
    "B": "Black",
    "R": "Red",
    "G": "Green",
    "C": "Colourless",
}


def colour_key(colours: Iterable[str]) -> str:
    """Colours in the usual WUBRG(C) order as one string: {"U", "W"} -> "WU"."""
    present = set(colours)
    return "".join(c for c in SOURCE_COLOURS if c in present)


def parse_mana_cost(cost: str) -> ManaCost:
    """Parse one face's cost. For "A // B" costs use parse_face_costs instead."""
    mana_value = 0
    pips: Counter[Pip] = Counter()
    x_count = 0

    for symbol in _SYMBOL_RE.findall(cost.upper()):
        if symbol.isdigit():
            mana_value += int(symbol)
        elif symbol in ("X", "Y", "Z"):
            x_count += 1
        elif symbol in SOURCE_COLOURS:
            mana_value += 1
            pips[frozenset({symbol})] += 1
        elif "/" in symbol:
            parts = symbol.split("/")
            if parts[0].isdigit():  # {2/W}: pay 2 generic instead
                mana_value += int(parts[0])
            elif "P" in parts:  # {R/P}: pay 2 life instead
                mana_value += 1
            else:  # {W/U}: hybrid
                mana_value += 1
                pips[frozenset(parts)] += 1
        elif symbol == "S":
            mana_value += 1
        # Anything else (e.g. Un-set half mana) is ignored.

    return ManaCost(mana_value, dict(pips), x_count)


def parse_face_costs(cost: str) -> list[ManaCost]:
    """Parse a cost that may cover several faces, e.g. "{1}{U}{U} // {1}{U}".

    Faces without a cost (such as the land back of an MDFC) are skipped.
    """
    return [parse_mana_cost(part) for part in cost.split("//") if part.strip()]
