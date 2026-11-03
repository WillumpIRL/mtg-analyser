"""Look up cards by name.

Decklists name cards in slightly different ways, so lookups are forgiving:
- case and accents are ignored ("lim-dul's vault" finds "Lim-Dûl's Vault")
- either face of a two-faced card works ("Brazen Borrower" finds
  "Brazen Borrower // Petty Theft"), as does the full "A // B" name
- a typo gets "did you mean" suggestions via rapidfuzz
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

from rapidfuzz import fuzz, process

from mtg_analyser.models import Card


class CardNotFoundError(KeyError):
    """No card matched the name. `suggestions` holds the closest real names."""

    def __init__(self, name: str, suggestions: list[str]) -> None:
        self.name = name
        self.suggestions = suggestions
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        super().__init__(f"Card not found: {name!r}.{hint}")

    def __str__(self) -> str:  # KeyError would otherwise wrap the message in quotes
        return self.args[0]


def normalise(name: str) -> str:
    """Lower-case, strip accents and tidy spacing so names compare reliably."""
    name = name.replace("Æ", "Ae").replace("æ", "ae")
    decomposed = unicodedata.normalize("NFKD", name)
    no_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    no_accents = no_accents.replace("’", "'")  # curly apostrophe from copy-paste
    return " ".join(no_accents.casefold().split())


class CardDatabase:
    """An in-memory index of cards by name."""

    def __init__(self, cards: Iterable[Card]) -> None:
        self._by_full_name: dict[str, Card] = {}
        self._by_face_name: dict[str, Card] = {}

        for card in cards:
            self._by_full_name[normalise(card.name)] = card
            for face in card.faces:
                # setdefault: if two cards share a face name, keep the first one
                self._by_face_name.setdefault(normalise(face.name), card)

        # Display names offered as suggestions, keyed by their normalised form.
        self._display_names: dict[str, str] = {
            normalise(c.name): c.name for c in self._by_full_name.values()
        }

    def __len__(self) -> int:
        return len(self._by_full_name)

    def __contains__(self, name: str) -> bool:
        return self.find(name) is not None

    def find(self, name: str) -> Card | None:
        """Exact (forgiving) lookup. Returns None if nothing matches."""
        key = normalise(name)
        return self._by_full_name.get(key) or self._by_face_name.get(key)

    def suggest(self, name: str, limit: int = 3, min_score: float = 70.0) -> list[str]:
        """Closest real card names to a misspelt one."""
        matches = process.extract(
            normalise(name),
            self._display_names.keys(),
            scorer=fuzz.WRatio,
            limit=limit,
            score_cutoff=min_score,
        )
        return [self._display_names[key] for key, _score, _index in matches]

    def get(self, name: str) -> Card:
        """Like find(), but raises CardNotFoundError with suggestions on a miss."""
        card = self.find(name)
        if card is None:
            raise CardNotFoundError(name, self.suggest(name))
        return card
