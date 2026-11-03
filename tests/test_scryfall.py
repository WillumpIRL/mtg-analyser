"""Tests for downloading and caching card data (FR-7, NFR-2).

httpx.MockTransport stands in for Scryfall, so these tests never touch the network.
"""

import gzip
import json
import os
import time

import httpx
import pytest

from mtg_analyser import scryfall
from mtg_analyser.scryfall import (
    CACHE_FILENAME,
    RAW_FILENAME,
    ScryfallError,
    is_stale,
    load_cache,
    load_cards,
    save_cache,
    slim_cards,
)

DOWNLOAD_URL = "https://data.scryfall.io/oracle-cards/oracle-cards-test.jsonl.gz"
LEGACY_DOWNLOAD_URL = "https://data.scryfall.io/oracle-cards/oracle-cards-test.json"

# Shape of Scryfall's GET /bulk-data reply (checked against the real API, Nov 2026):
# a list of every bulk file on offer, each linking to gzipped JSON Lines. There is
# no "download_uri" any more; expecting one caused a real-world failure.
BULK_LIST = {
    "object": "list",
    "has_more": False,
    "data": [
        {
            "object": "bulk_data",
            "type": "default_cards",
            "jsonl_download_uri": "https://data.scryfall.io/default-cards/test.jsonl.gz",
        },
        {
            "object": "bulk_data",
            "type": "oracle_cards",
            "name": "Oracle Cards",
            "jsonl_download_uri": DOWNLOAD_URL,
            "compressed_size": 25307048,
        },
        {
            "object": "bulk_data",
            "type": "rulings",
            "jsonl_download_uri": "https://data.scryfall.io/rulings/test.jsonl.gz",
        },
    ],
}

# The older reply format: a plain JSON array behind "download_uri".
LEGACY_BULK_LIST = {
    "object": "list",
    "data": [{"object": "bulk_data", "type": "oracle_cards", "download_uri": LEGACY_DOWNLOAD_URL}],
}


def to_jsonl_gz(raw_cards) -> bytes:
    """Encode cards the way Scryfall serves them now: one JSON object per line, gzipped."""
    lines = "\n".join(json.dumps(c) for c in raw_cards) + "\n"
    return gzip.compress(lines.encode())


def client_replying(**response_kwargs) -> httpx.Client:
    """A client whose every request gets the same canned response."""
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(**response_kwargs))
    )


def fake_scryfall(raw_cards, calls: list[str], *, legacy: bool = False) -> httpx.Client:
    """A client whose 'Scryfall' serves the sample cards and records each request.

    By default it behaves like today's Scryfall (gzipped JSON Lines); legacy=True
    serves the older plain JSON array instead.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if str(request.url) == scryfall.BULK_DATA_URL:
            return httpx.Response(200, json=LEGACY_BULK_LIST if legacy else BULK_LIST)
        if str(request.url) == DOWNLOAD_URL and not legacy:
            return httpx.Response(200, content=to_jsonl_gz(raw_cards))
        if str(request.url) == LEGACY_DOWNLOAD_URL and legacy:
            return httpx.Response(200, content=json.dumps(raw_cards).encode())
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler), headers=scryfall.HEADERS)


def offline_client() -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no internet", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def make_old(path, days: float) -> None:
    old = time.time() - days * 24 * 60 * 60
    os.utime(path, (old, old))


# ---------- slimming and the cache file ----------


def test_slim_cards_drops_tokens(raw_cards) -> None:
    names = [c.name for c in slim_cards(raw_cards)]
    assert "Goblin" not in names
    assert "Lightning Bolt" in names


def test_cache_round_trip(tmp_path, cards) -> None:
    path = tmp_path / CACHE_FILENAME
    save_cache(cards, path)
    assert load_cache(path) == cards


def test_cache_keeps_accented_names_readable(tmp_path, cards) -> None:
    path = tmp_path / CACHE_FILENAME
    save_cache(cards, path)
    assert "Lim-Dûl's Vault" in path.read_text(encoding="utf-8")


def test_is_stale(tmp_path) -> None:
    path = tmp_path / "x.json"
    assert is_stale(path)  # missing
    path.write_text("[]")
    assert not is_stale(path)  # brand new
    make_old(path, days=8)
    assert is_stale(path)  # older than 7 days


# ---------- downloading ----------


def test_first_run_downloads_and_builds_cache(tmp_path, raw_cards) -> None:
    calls: list[str] = []
    cards = load_cards(tmp_path, client=fake_scryfall(raw_cards, calls))

    assert calls == [scryfall.BULK_DATA_URL, DOWNLOAD_URL]
    assert len(cards) == 13
    assert (tmp_path / CACHE_FILENAME).exists()
    assert not (tmp_path / RAW_FILENAME).exists()  # big raw file cleaned up


def test_picks_oracle_cards_from_bulk_list() -> None:
    client = client_replying(status_code=200, json=BULK_LIST)
    assert scryfall.get_bulk_download_uri(client) == DOWNLOAD_URL


def test_bulk_entry_with_only_jsonl_link_is_accepted() -> None:
    # Regression: the real reply has "jsonl_download_uri" and no "download_uri".
    # We used to reject it with "Scryfall has no 'oracle_cards' bulk file".
    entry = BULK_LIST["data"][1]
    assert "download_uri" not in entry
    client = client_replying(status_code=200, json={"data": [entry]})
    assert scryfall.get_bulk_download_uri(client) == DOWNLOAD_URL


def test_picks_legacy_download_uri() -> None:
    client = client_replying(status_code=200, json=LEGACY_BULK_LIST)
    assert scryfall.get_bulk_download_uri(client) == LEGACY_DOWNLOAD_URL


def test_oracle_entry_without_any_link_raises() -> None:
    reply = {"data": [{"type": "oracle_cards"}]}
    with pytest.raises(ScryfallError, match="no download link"):
        scryfall.get_bulk_download_uri(client_replying(status_code=200, json=reply))


def test_legacy_json_array_download_still_works(tmp_path, raw_cards) -> None:
    cards = load_cards(tmp_path, client=fake_scryfall(raw_cards, [], legacy=True))
    assert len(cards) == 13


@pytest.mark.parametrize("compress", [True, False])
@pytest.mark.parametrize("as_jsonl", [True, False])
def test_iter_bulk_cards_reads_every_format(tmp_path, raw_cards, compress, as_jsonl) -> None:
    text = "\n".join(json.dumps(c) for c in raw_cards) if as_jsonl else json.dumps(raw_cards)
    data = text.encode()
    path = tmp_path / "bulk"
    path.write_bytes(gzip.compress(data) if compress else data)
    assert list(scryfall.iter_bulk_cards(path)) == raw_cards


def test_corrupt_download_raises_scryfall_error(tmp_path) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(200, json=BULK_LIST)
                if str(r.url) == scryfall.BULK_DATA_URL
                else httpx.Response(200, content=b"\x1f\x8bnot really gzip")
            )
        )
    )
    with pytest.raises(ScryfallError, match="Could not read"):
        load_cards(tmp_path, client=client)


def test_bulk_list_without_oracle_cards_raises() -> None:
    reply = {"object": "list", "data": [{"type": "rulings", "download_uri": "x"}]}
    with pytest.raises(ScryfallError, match="no 'oracle_cards'"):
        scryfall.get_bulk_download_uri(client_replying(status_code=200, json=reply))


def test_unexpected_bulk_reply_raises_scryfall_error() -> None:
    # e.g. an error object or an HTML page instead of the list
    for kwargs in ({"json": {"object": "error"}}, {"text": "<html>oops</html>"}):
        with pytest.raises(ScryfallError, match="Unexpected reply"):
            scryfall.get_bulk_download_uri(client_replying(status_code=200, **kwargs))


def test_sends_scryfall_headers(raw_cards) -> None:
    client = fake_scryfall(raw_cards, [])
    assert client.headers["User-Agent"].startswith("mtg-analyser/")
    assert client.headers["Accept"] == "application/json"


def test_fresh_cache_skips_network(tmp_path, cards) -> None:
    save_cache(cards, tmp_path / CACHE_FILENAME)
    calls: list[str] = []
    loaded = load_cards(tmp_path, client=fake_scryfall([], calls))
    assert calls == []
    assert loaded == cards


def test_stale_cache_is_refreshed(tmp_path, cards, raw_cards) -> None:
    cache = tmp_path / CACHE_FILENAME
    save_cache(cards[:1], cache)
    make_old(cache, days=8)

    calls: list[str] = []
    loaded = load_cards(tmp_path, client=fake_scryfall(raw_cards, calls))
    assert len(calls) == 2
    assert len(loaded) == 13


def test_stale_cache_used_when_offline(tmp_path, cards) -> None:
    cache = tmp_path / CACHE_FILENAME
    save_cache(cards, cache)
    make_old(cache, days=30)
    assert load_cards(tmp_path, client=offline_client()) == cards


def test_no_cache_and_offline_raises(tmp_path) -> None:
    with pytest.raises(ScryfallError):
        load_cards(tmp_path, client=offline_client())
    assert not list(tmp_path.glob("*.part"))  # no half-written files left behind


def test_force_refresh_offline_raises_even_with_cache(tmp_path, cards) -> None:
    save_cache(cards, tmp_path / CACHE_FILENAME)
    with pytest.raises(ScryfallError):
        load_cards(tmp_path, force_refresh=True, client=offline_client())


def test_progress_callback_reports_bytes(tmp_path, raw_cards) -> None:
    seen: list[int] = []
    load_cards(
        tmp_path,
        client=fake_scryfall(raw_cards, []),
        progress=lambda done, total: seen.append(done),
    )
    assert seen
    assert seen[-1] == len(to_jsonl_gz(raw_cards))  # compressed bytes, as sent
