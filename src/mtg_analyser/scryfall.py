"""Download Scryfall's card database and keep a small local cache of it.

How it works:
1. Ask Scryfall's bulk-data API where today's "Oracle Cards" file is
   (one entry per unique card). Scryfall serves it as gzipped JSON Lines
   (about 25 MB compressed); older replies offered a plain JSON array instead,
   so both are understood.
2. Download that file into data/.
3. Slim it down to only the fields we use (see models.Card) and save that as
   data/cards.json, which is far smaller and loads in well under a second.
4. Re-download when the cache is more than 7 days old.

Scryfall asks API users to send a User-Agent and Accept header and to prefer
bulk files over thousands of single-card requests: https://scryfall.com/docs/api
"""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import IO, Any

import httpx

from mtg_analyser import __version__
from mtg_analyser.models import NON_DECK_LAYOUTS, Card

# Lists every bulk file Scryfall offers; we pick the one whose type is "oracle_cards".
BULK_DATA_URL = "https://api.scryfall.com/bulk-data"
BULK_TYPE = "oracle_cards"
# Link fields in a bulk-data entry, newest format first.
DOWNLOAD_URI_KEYS = ("jsonl_download_uri", "download_uri")
HEADERS = {
    "User-Agent": f"mtg-analyser/{__version__}",
    "Accept": "application/json",
}

# data/ sits at the project root: src/mtg_analyser/scryfall.py -> parents[2]
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_FILENAME = "oracle-cards.download"  # may be .json or .jsonl.gz; see iter_bulk_cards
CACHE_FILENAME = "cards.json"
MAX_AGE_DAYS = 7

ProgressCallback = Callable[[int, int | None], None]
"""Called as progress(bytes_downloaded, total_bytes_or_None) while downloading."""


class ScryfallError(Exception):
    """Something went wrong talking to Scryfall."""


def make_client() -> httpx.Client:
    """An HTTP client with Scryfall's requested headers and sensible timeouts."""
    return httpx.Client(headers=HEADERS, timeout=httpx.Timeout(30.0), follow_redirects=True)


def is_stale(path: Path, max_age_days: float = MAX_AGE_DAYS) -> bool:
    """True if the file is missing or older than max_age_days."""
    if not path.exists():
        return True
    age_seconds = time.time() - path.stat().st_mtime
    return age_seconds > max_age_days * 24 * 60 * 60


def get_bulk_download_uri(client: httpx.Client) -> str:
    """Ask Scryfall for the current download link of the Oracle Cards file."""
    try:
        response = client.get(BULK_DATA_URL)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ScryfallError(f"Could not reach Scryfall's bulk-data API: {exc}") from exc

    try:
        entries = response.json()["data"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ScryfallError(
            f"Unexpected reply from Scryfall's bulk-data API: {response.text[:200]!r}"
        ) from exc

    for entry in entries:
        if entry.get("type") != BULK_TYPE:
            continue
        for key in DOWNLOAD_URI_KEYS:
            if entry.get(key):
                return entry[key]
        raise ScryfallError(f"Scryfall's {BULK_TYPE!r} entry has no download link: {entry}")
    available = ", ".join(str(e.get("type")) for e in entries)
    raise ScryfallError(f"Scryfall has no {BULK_TYPE!r} bulk file (found: {available}).")


def download_file(
    client: httpx.Client, url: str, dest: Path, progress: ProgressCallback | None = None
) -> None:
    """Stream a file to disk. Writes to a .part file first so a failed download
    never leaves a half-written file behind."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            total = (
                int(response.headers["Content-Length"])
                if "Content-Length" in response.headers
                else None
            )
            written = 0
            with tmp.open("wb") as f:
                for chunk in response.iter_bytes(chunk_size=1 << 20):
                    f.write(chunk)
                    written += len(chunk)
                    if progress:
                        # Prefer bytes received over the wire: that matches Content-Length
                        # even when Scryfall sends the file compressed.
                        progress(response.num_bytes_downloaded or written, total)
    except httpx.HTTPError as exc:
        tmp.unlink(missing_ok=True)
        raise ScryfallError(f"Download failed: {exc}") from exc
    tmp.replace(dest)


def iter_bulk_cards(path: Path) -> Iterator[dict[str, Any]]:
    """Yield raw card objects from a downloaded bulk file.

    Handles gzip-compressed or plain files, holding either JSON Lines (one card
    per line) or a single JSON array. The format is sniffed from the content,
    not the file name, so it doesn't matter what the download was called.
    """
    with path.open("rb") as f:
        is_gzip = f.read(2) == b"\x1f\x8b"
    opener = gzip.open if is_gzip else open
    with opener(path, "rt", encoding="utf-8") as f:
        if _first_char(f) == "[":
            yield from json.load(f)
        else:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def _first_char(f: IO[str]) -> str:
    """First non-whitespace character of a text file, leaving the file rewound."""
    while ch := f.read(1):
        if not ch.isspace():
            f.seek(0)
            return ch
    f.seek(0)
    return ""


def slim_cards(raw_cards: Iterable[dict[str, Any]]) -> list[Card]:
    """Turn raw Scryfall card objects into Cards, skipping tokens and other non-deck cards."""
    return [Card.from_scryfall(c) for c in raw_cards if c.get("layout") not in NON_DECK_LAYOUTS]


def save_cache(cards: list[Card], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump([c.to_dict() for c in cards], f, ensure_ascii=False)


def load_cache(path: Path) -> list[Card]:
    with path.open(encoding="utf-8") as f:
        return [Card.from_dict(d) for d in json.load(f)]


def update_cards(
    data_dir: Path = DEFAULT_DATA_DIR,
    client: httpx.Client | None = None,
    progress: ProgressCallback | None = None,
) -> list[Card]:
    """Download the latest card data and rebuild the slim cache. Returns the cards."""
    own_client = client is None
    client = client or make_client()
    try:
        url = get_bulk_download_uri(client)
        raw_path = data_dir / RAW_FILENAME
        download_file(client, url, raw_path, progress)
    finally:
        if own_client:
            client.close()

    try:
        cards = slim_cards(iter_bulk_cards(raw_path))
    except (OSError, ValueError, KeyError) as exc:  # bad gzip, bad JSON, missing "name"
        raise ScryfallError(f"Could not read the downloaded card file: {exc}") from exc
    save_cache(cards, data_dir / CACHE_FILENAME)
    raw_path.unlink()  # the big file isn't needed once the slim cache exists
    return cards


def load_cards(
    data_dir: Path = DEFAULT_DATA_DIR,
    *,
    force_refresh: bool = False,
    client: httpx.Client | None = None,
    progress: ProgressCallback | None = None,
) -> list[Card]:
    """Load cards from the cache, downloading first if it's missing or stale.

    If the cache is stale but Scryfall can't be reached, the old cache is used
    so the tool still works offline.
    """
    cache_path = data_dir / CACHE_FILENAME
    if force_refresh or is_stale(cache_path):
        try:
            return update_cards(data_dir, client, progress)
        except ScryfallError:
            if cache_path.exists() and not force_refresh:
                return load_cache(cache_path)
            raise
    return load_cache(cache_path)
