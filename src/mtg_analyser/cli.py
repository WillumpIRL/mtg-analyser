"""Command-line interface: a thin layer that loads, analyses and prints.

Results go to stdout; progress bars, status messages and errors go to stderr, so
`analyse --json > out.json` stays valid JSON even when card data downloads first.
"""

import io
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn

from mtg_analyser import __version__, report
from mtg_analyser.analysis import analyse as run_analysis
from mtg_analyser.card_db import CardDatabase, CardNotFoundError
from mtg_analyser.legality import check_deck
from mtg_analyser.parser import parse_decklist, read_decklist, resolve_cards
from mtg_analyser.scryfall import CACHE_FILENAME, DEFAULT_DATA_DIR, ScryfallError, needs_update
from mtg_analyser.scryfall import load_cards as _load_cards

app = typer.Typer(help="Analyse an MTG decklist's mana curve, colours and lands.")
console = Console()
err_console = Console(stderr=True)
CHART_DIR = "output"


def load_cards_with_progress(force_refresh: bool = False):
    """Load card data, showing a progress bar if a download is needed."""
    needs_download = force_refresh or needs_update(DEFAULT_DATA_DIR / CACHE_FILENAME)
    if not needs_download:
        return _load_cards()

    err_console.print("Downloading card data from Scryfall (about 25 MB, once a week)...")
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=err_console,
    ) as bar:
        task = bar.add_task("Oracle cards", total=None)

        def on_progress(done: int, total: int | None) -> None:
            bar.update(task, completed=done, total=total)

        cards = _load_cards(force_refresh=force_refresh, progress=on_progress)
    err_console.print(f"[green]Saved {len(cards):,} cards to the local cache.[/]")
    return cards


def use_utf8_output() -> None:
    """Write UTF-8 even when Windows Python would default to cp1252.

    Terminals like MSYS2's mintty aren't native Windows consoles, so Python treats
    them as pipes and uses the ANSI code page, garbling "—", "•" and Rich's box lines.
    """
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8")


@app.callback()
def main() -> None:
    """MTG Analyser."""
    use_utf8_output()


@app.command()
def version() -> None:
    """Show the installed version."""
    console.print(f"[bold green]mtg-analyser[/] {__version__}")


@app.command("update-cards")
def update_cards() -> None:
    """Download the latest card data from Scryfall."""
    try:
        load_cards_with_progress(force_refresh=True)
    except ScryfallError as exc:
        err_console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc


@app.command()
def card(name: Annotated[str, typer.Argument(help='Card name, e.g. "Lightning Bolt"')]) -> None:
    """Look up a single card."""
    try:
        db = CardDatabase(load_cards_with_progress())
    except ScryfallError as exc:
        err_console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    try:
        c = db.get(name)
    except CardNotFoundError as exc:
        err_console.print(f"[yellow]{escape(str(exc))}[/]")
        raise typer.Exit(code=1) from exc

    lines = [
        f"[bold]Mana cost:[/] {c.mana_cost or '—'}   [bold]Mana value:[/] {c.mana_value:g}",
        f"[bold]Type:[/] {c.type_line}",
        f"[bold]Colours:[/] {''.join(c.colors) or 'Colourless'}   "
        f"[bold]Identity:[/] {''.join(c.color_identity) or 'Colourless'}",
    ]
    if c.produced_mana:
        lines.append(f"[bold]Produces:[/] {', '.join(c.produced_mana)}")
    if c.layout != "normal":
        lines.append(f"[bold]Layout:[/] {c.layout}" + ("  (MDFC land)" if c.is_mdfc_land else ""))
    for face in c.faces:
        lines.append(f"  • {face.name} {face.mana_cost} — {face.type_line}")
    console.print(Panel("\n".join(lines), title=c.name, expand=False))


@app.command()
def analyse(
    path: Annotated[str, typer.Argument(help='Decklist file, or "-" to paste text on stdin')],
    show_cards: Annotated[
        bool, typer.Option("--list", help="Also list every line and the card it matched.")
    ] = False,
    with_sideboard: Annotated[
        bool, typer.Option("--with-sideboard", help="Analyse the sideboard too (e.g. a pool).")
    ] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print the analysis as JSON.")] = False,
    chart: Annotated[
        bool, typer.Option("--chart", help=f"Also save a PNG chart in {CHART_DIR}/.")
    ] = False,
) -> None:
    """Analyse a decklist's mana curve, colours, lands and opening hands."""
    name = "pasted deck" if path == "-" else Path(path).name
    if path == "-":
        deck, problems = parse_decklist(sys.stdin.read())
    else:
        try:
            deck, problems = read_decklist(Path(path))
        except OSError as exc:
            err_console.print(f"[red]Can't read {escape(path)}: {exc.strerror}[/]")
            raise typer.Exit(code=1) from exc

    try:
        db = CardDatabase(load_cards_with_progress())
    except ScryfallError as exc:
        err_console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc
    resolved, unknown = resolve_cards(deck, db)
    problems = sorted(problems + unknown, key=lambda p: p.line_number)

    if not resolved:
        if problems:
            err_console.print(report.problems_section(problems))
        err_console.print("[red]No cards recognised, so there's nothing to analyse.[/]")
        raise typer.Exit(code=1)

    analysis = run_analysis(deck, resolved, include_sideboard=with_sideboard)
    notes = check_deck(deck, resolved)

    chart_path = None
    if chart:
        # Imported here: matplotlib takes longer to load than the whole analysis (NFR-1).
        from mtg_analyser.charts import save_chart

        stem = "pasted-deck" if path == "-" else Path(path).stem
        title = f"{name} · {deck.format.capitalize()}, {deck.total_cards()} cards"
        chart_path = save_chart(analysis, Path(CHART_DIR) / f"{stem}.png", title)
        err_console.print(f"Saved chart to {chart_path}")

    if as_json:
        data = {
            "deck": name,
            "problems": [asdict(p) for p in problems],
            "analysis": analysis.to_dict(),
            "deck_checks": [asdict(n) for n in notes],
            "chart": str(chart_path) if chart_path else None,
        }
        sys.stdout.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return

    for part in report.full_report(
        name, deck, resolved, analysis, notes, problems, show_cards=show_cards
    ):
        console.print(part)


app.command("analyze", hidden=True)(analyse)  # US spelling


if __name__ == "__main__":
    app()
