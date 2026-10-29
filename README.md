# MTG Analyser

Analyse a Magic: The Gathering decklist's mana curve, colour requirements and land balance.
Supports Limited (40), Constructed (60) and Commander (100) decks.

> Status: Phase 0 (project setup). Analysis features are coming in later phases.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync            # creates .venv and installs everything
uv run pytest      # run the tests
uv run mtg-analyser version
```

## Development

```bash
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pytest --cov=mtg_analyser   # tests with coverage
```

Card data comes from the [Scryfall API](https://scryfall.com/docs/api).
