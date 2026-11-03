"""Tests for looking cards up by name (FR-5, FR-6)."""

import pytest

from mtg_analyser.card_db import CardNotFoundError, normalise


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("Lightning Bolt", "Lightning Bolt"),
        ("lightning bolt", "Lightning Bolt"),
        ("  LIGHTNING   BOLT ", "Lightning Bolt"),
        ("Lim-Dul's Vault", "Lim-Dûl's Vault"),
        ("Lim-Dul’s Vault", "Lim-Dûl's Vault"),  # curly apostrophe
        ("Aether Vial", "Æther Vial"),
        ("Fire // Ice", "Fire // Ice"),
        ("Fire", "Fire // Ice"),
        ("Ice", "Fire // Ice"),
        ("Brazen Borrower", "Brazen Borrower // Petty Theft"),
        ("Delver of Secrets", "Delver of Secrets // Insectile Aberration"),
        ("Insectile Aberration", "Delver of Secrets // Insectile Aberration"),
        ("Shatterskull Smashing", "Shatterskull Smashing // Shatterskull, the Hammer Pass"),
    ],
)
def test_find(db, query, expected) -> None:
    card = db.find(query)
    assert card is not None
    assert card.name == expected


def test_find_unknown_returns_none(db) -> None:
    assert db.find("Black Lotus") is None


def test_tokens_are_not_in_the_database(db) -> None:
    assert db.find("Goblin") is None


def test_len_and_contains(db) -> None:
    assert len(db) == 13  # 14 sample cards minus the token
    assert "Counterspell" in db
    assert "Not A Card" not in db


def test_suggest_for_typo(db) -> None:
    assert db.suggest("Lightening Bolt")[0] == "Lightning Bolt"
    assert db.suggest("Counterspel")[0] == "Counterspell"


def test_get_raises_with_suggestions(db) -> None:
    with pytest.raises(CardNotFoundError) as exc_info:
        db.get("Lightnig Bolt")
    assert exc_info.value.suggestions[0] == "Lightning Bolt"
    assert "Did you mean" in str(exc_info.value)


def test_get_raises_without_suggestions_for_nonsense(db) -> None:
    with pytest.raises(CardNotFoundError) as exc_info:
        db.get("zzzzqqqq")
    assert exc_info.value.suggestions == []


def test_normalise() -> None:
    assert normalise("  Æther   VIAL ") == "aether vial"
    assert normalise("Jötun Grunt") == "jotun grunt"
