# MTG Analyser

Analyse a Magic: The Gathering decklist's mana curve, colour requirements and land balance.
Supports Limited (40), Constructed (60) and Commander (100) decks.

> **Status:** Phases 0–4 are done: card data, decklist parsing, the analysis engine and
> the `analyse` command, with charts, JSON output and deck checks.

## What it does

- **Card data** from [Scryfall](https://scryfall.com/docs/api), downloaded once (about 25 MB)
  and cached in `data/cards.json`. It refreshes weekly, and if you're offline the old cache
  is used.
- **Forgiving card lookup**: ignores case and accents, accepts either face of a two-faced
  card, and suggests the closest names for typos ("lightnig bolt" → Lightning Bolt).
- **Decklist parsing** for plain text, MTG Arena and MTGO exports, with sections
  (Commander, Companion, Deck, Sideboard). Lines it can't read are reported with their
  line numbers instead of stopping the parse.
- **Analysis**:
  - mana curve and average mana value
  - coloured pips, and mana sources per colour
  - land count against a recommendation
  - whether each colour has enough sources to cast its hardest card on curve
  - opening-hand land odds and the chance of hitting land drops on turns 1–4
- **Deck checks**: deck size, copy limits (4 in Constructed, singleton in Commander),
  sideboard size and Commander colour identity. Ban lists aren't checked.
- **Output** as a terminal report, JSON (`--json`) or a PNG chart (`--chart`).

## Setup

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                          # create .venv and install everything
uv run mtg-analyser update-cards # download card data (also happens automatically)
```

## Usage

```bash
uv run mtg-analyser analyse sample_decks/limited_rg_m20.txt
uv run mtg-analyser analyse - < my_deck.txt        # or paste a list on stdin
uv run mtg-analyser card "lightning bolt"         # look up one card
uv run mtg-analyser update-cards                   # force a fresh download
uv run mtg-analyser version
```

`analyse` (or `analyze`) options:

| Option | What it does |
| --- | --- |
| `--list` | Also list every line and the card it matched |
| `--with-sideboard` | Analyse the sideboard as well, e.g. a whole Limited pool |
| `--chart` | Save a PNG chart to `output/<deck name>.png` |
| `--json` | Print the full analysis as JSON instead of the report |

Lines that couldn't be used, such as unknown names with "did you mean" suggestions, are
listed at the top of the report. Progress and status messages go to stderr, so
`analyse deck.txt --json > deck.json` always gives clean JSON.

A shortened report for the sample mono-red deck:

```text
constructed_mono_red_arena.txt ─────────────────────────────────────────
Constructed deck · 60 cards · sideboard 13 (not analysed; --with-sideboard)

Lands ──────────────────────────────────────────────────────────────────
19 lands + 3 MDFCs (worth 2.22) = 21.2
Recommended: 23.4  ✗ too few, by 2.2

Colours ────────────────────────────────────────────────────────────────
Sources needed to cast each colour's hardest card on curve:
Colours  Hardest card           Cost       Turn  Need  Have
Red      Shatterskull Smashing  {X}{R}{R}     3    18    22  ✓ ok

Opening hand ───────────────────────────────────────────────────────────
Keepable (2–5 lands): 80%
Turn  On the play  On the draw
   3          72%          80%
```

The chart shows the mana curve, and each colour's sources against what its hardest
card needs.

### Decklist format

```text
About                          # Arena's header block is skipped
Name Mono-Red Aggro

Commander                      # headers: Commander, Companion, Deck, Sideboard
1 Krenko, Mob Boss             #   (any case, optional trailing colon)

Deck
4 Lightning Bolt               # plain
4x Lightning Bolt              # "x" after the quantity
4 Lightning Bolt (M10) 146     # Arena/MTGO: set code and collector number are ignored
1 Lightning Bolt (2X2) 117 *F* # foil marks too
SB: 2 Duress                   # MTGO-style sideboard line
// comments start with // or #
```

Only the mainboard and commander are analysed. The sideboard and companion are kept
separately. In a list with **no headers** (MTGO, older Arena exports), a blank line
followed by 15 cards or fewer is treated as the sideboard. Otherwise blank lines are
just spacing.

The format is guessed from the size: a commander or exactly 100 cards means Commander,
60+ means Constructed, and 40+ means Limited.

### Using it from Python

The command is a thin layer over the library, which you can also use directly:

```python
from pathlib import Path

from mtg_analyser.analysis import analyse
from mtg_analyser.card_db import CardDatabase
from mtg_analyser.parser import read_decklist, resolve_cards
from mtg_analyser.scryfall import load_cards

db = CardDatabase(load_cards())
deck, problems = read_decklist(Path("sample_decks/limited_rg_m20.txt"))
resolved, unknown = resolve_cards(deck, db)
result = analyse(deck, resolved)

print(result.land_check.status, round(result.land_check.recommended, 1))  # ok 16.5
for req in result.requirements:
    if not req.met:
        print(f"{req.card}: needs {req.required} sources, has {req.available:g}")
# Keldon Raider: needs 11 sources, has 8
# Gnarlback Rhino: needs 11 sources, has 9
```

## How the analysis works

The land and colour checks follow Frank Karsten's published research:
[land counts](https://www.tcgplayer.com/content/article/How-Many-Lands-Do-You-Need-in-Your-Deck-An-Updated-Analysis/cd1c1a24-d439-4a8e-b369-b936edb0b38a/)
and
[coloured sources](https://www.tcgplayer.com/content/article/How-Many-Sources-Do-You-Need-to-Consistently-Cast-Your-Spells-A-2022-Update/dc23a7d2-0a16-4c0b-ad36-586fcca03ad8/)
(both 2022). His numbers are in [`karsten.py`](src/mtg_analyser/karsten.py).

- **Recommended lands** = 19.59 + 1.90 × average mana value − 0.28 × cheap card draw/ramp
  spells (+0.27 with a companion), for 60 cards.
  - Other non-Commander sizes are scaled by size/60. For 40 cards this gives about 17 lands.
  - Commander uses Karsten's 99-card version: 31.42 + 3.13 × average − 0.28 × cheap spells.
  - "Cheap draw/ramp" uses Karsten's own text rules: mana value 2 or less and draws,
    digs, adds mana or fetches lands, plus any card that cycles for one mana.
  - Within ±1 land of the recommendation counts as fine.
- **Colour requirements**: for each card, the coloured sources Karsten's table says you need
  to cast it on curve about 90–96% of the time, for your deck size.
  - Gold cards check each colour, plus "either colour", all +1. Hybrid pips accept either
    colour.
  - Turn-1 spells count only lands that enter untapped.
  - Mana dorks count as ½ a source (for spells of mana value 2+) and mana rocks as ¾
    (for 3+).
  - Fetchlands count for every colour they can fetch.
  - The hardest card per colour is reported.
- **Land/spell MDFCs** (e.g. Shatterskull Smashing):
  - In the curve they count as spells.
  - In the land count they count as **0.38** of a land, or **0.74** if mythic (Karsten's
    regression).
  - As colour sources they count fully.
- **X spells** are colour-checked as if X = 1 (the curve still counts X as 0).
- **Opening-hand odds** are exact hypergeometric probabilities, with no mulligans modelled.
  MDFCs count as lands here, since they can be played as one. In Commander the commander is
  left out of the library, and the first player draws on turn 1.

These are guidelines, not rules: Karsten's land formula has a typical error of about
±2.75 lands, and cards like scry lands or card selection aren't modelled.

## Sample decks

| File | Format | Notes |
| --- | --- | --- |
| [`limited_rg_m20.txt`](sample_decks/limited_rg_m20.txt) | Limited, 40 | Hand-typed: `2x`, comments, `Deck:`/`Sideboard:` |
| [`constructed_mono_red_arena.txt`](sample_decks/constructed_mono_red_arena.txt) | Constructed, 60 + 13 | MTG Arena export with set codes and MDFCs |
| [`commander_krenko.txt`](sample_decks/commander_krenko.txt) | Commander, 1 + 99 | Commander and Deck sections |

## Project layout

```text
src/mtg_analyser/
  models.py     Card, Deck and friends (plain dataclasses)
  scryfall.py   download and cache card data
  card_db.py    forgiving name lookup and suggestions
  parser.py     decklist text -> Deck, then names -> cards
  mana.py       read mana costs like {2}{W/U}
  karsten.py    Karsten's tables and formulas
  odds.py       hypergeometric probabilities
  analysis.py   the analysis itself
  legality.py   deck size, copy limit and colour identity checks
  charts.py     PNG chart (matplotlib)
  report.py     terminal report (Rich), used only by the CLI
  cli.py        thin command-line layer (Typer)
tests/          pytest; never touches the network
sample_decks/   example decklists
data/           card cache (git-ignored)
output/         charts from --chart (git-ignored)
```

The core library has no terminal code. `cli.py` and `report.py` only format what the
library returns, and matplotlib is only imported when `--chart` is used, so a normal
run stays well under the 2-second target.

## Development

```bash
uv run pytest                      # tests (offline: Scryfall is mocked)
uv run pytest --cov=mtg_analyser   # with coverage
uv run ruff check .                # lint
uv run ruff format .               # format
```

- The card cache has a format version. When a release stores new card fields, older
  caches are rebuilt automatically on the next run.
- On Windows terminals that aren't native consoles (e.g. MSYS2), output is switched to
  UTF-8 so symbols like `—` display properly.

## Credits

Card data comes from [Scryfall](https://scryfall.com/). The deckbuilding guidelines are
by Frank Karsten (articles linked above). MTG Analyser is
unofficial Fan Content and is not approved or endorsed by Wizards of the Coast. Magic: The
Gathering is a trademark of Wizards of the Coast LLC.
