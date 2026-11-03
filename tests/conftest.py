"""Shared test fixtures. Tests use saved sample data, never the real network."""

import json
from pathlib import Path
from typing import Any

import pytest

from mtg_analyser.card_db import CardDatabase
from mtg_analyser.models import Card
from mtg_analyser.scryfall import slim_cards

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE_PATH = FIXTURES / "scryfall_sample.json"


@pytest.fixture
def raw_cards() -> list[dict[str, Any]]:
    """Raw Scryfall card objects, exactly as Scryfall's bulk file holds them."""
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def raw_by_name(raw_cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in raw_cards}


@pytest.fixture
def cards(raw_cards: list[dict[str, Any]]) -> list[Card]:
    return slim_cards(raw_cards)


@pytest.fixture
def db(cards: list[Card]) -> CardDatabase:
    return CardDatabase(cards)
