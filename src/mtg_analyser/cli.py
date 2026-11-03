"""Command-line interface. The `analyse` command arrives in Phase 4."""

import io
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, DownloadColumn, Progress, TransferSpeedColumn
from rich.table import Table

from mtg_analyser import __version__
from mtg_analyser.card_db import CardDatabase, CardNotFoundError
from mtg_analyser.models import Section
from mtg_analyser.parser import parse_decklist, read_decklist, resolve_cards
from mtg_analyser.scryfall import CACHE_FILENAME, DEFAULT_DATA_DIR, ScryfallError, needs_update
from mtg_analyser.scryfall import load_cards as _load_cards

app = typer.Typer(help="Analyse an MTG decklist's mana curve, colours and lands.")
console = Console()


def load_cards_with_progress(force_refresh: bool = False):
    """Load card data, showing a progress bar if a download is needed."""
    needs_download = force_refresh or needs_update(DEFAULT_DATA_DIR / CACHE_FILENAME)
    if not needs_download:
        return _load_cards()

    console.print("Downloading card data from Scryfall (about 25 MB, once a week)...")
    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        console=console,
    ) as bar:
        task = bar.add_task("Oracle cards", total=None)

        def on_progress(done: int, total: int | None) -> None:
            bar.update(task, completed=done, total=total)

        cards = _load_cards(force_refresh=force_refresh, progress=on_progress)
    console.print(f"[green]Saved {len(cards):,} cards to the local cache.[/]")
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
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc


@app.command()
def card(name: Annotated[str, typer.Argument(help='Card name, e.g. "Lightning Bolt"')]) -> None:
    """Look up a single card."""
    try:
        db = CardDatabase(load_cards_with_progress())
    except ScryfallError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(code=1) from exc

    try:
        c = db.get(name)
    except CardNotFoundError as exc:
        console.print(f"[yellow]{exc}[/]")
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
def parse(
    path: Annotated[str, typer.Argument(help='Decklist file, or "-" to paste text on stdin')],
) -> None:
    """Show how a decklist is read (temporary, until `analyse` arrives)."""
    if path == "-":
        deck, problems = parse_decklist(sys.stdin.read())
    else:
        try:
            deck, problems = read_decklist(Path(path))
        except OSError as exc:
            console.print(f"[red]Can't read {path}: {exc.strerror}[/]")
            raise typer.Exit(code=1) from exc

    cards_by_line: dict[int, str] = {}
    try:
        resolved, unknown = resolve_cards(deck, CardDatabase(load_cards_with_progress()))
        cards_by_line = {r.entry.line_number: r.card.name for r in resolved}
        problems = sorted(problems + unknown, key=lambda p: p.line_number)
    except ScryfallError as exc:
        console.print(f"[yellow]Card names not checked: {exc}[/]")

    table = Table(title="Decklist")
    for column in ("Line", "Section", "Qty", "Name", "Card"):
        table.add_column(column, justify="right" if column in ("Line", "Qty") else "left")
    for e in deck.entries:
        card_name = cards_by_line.get(e.line_number, "")
        # escape(): decklist text is user input, and Rich would read "[...]" as markup
        table.add_row(str(e.line_number), e.section, str(e.quantity), escape(e.name), card_name)
    console.print(table)
    console.print(
        f"[bold]Format:[/] {deck.format}   [bold]Analysed cards:[/] {deck.total_cards()}   "
        f"[bold]Sideboard:[/] {deck.total_cards(Section.SIDEBOARD)}"
    )

    if problems:
        problem_table = Table(title="Problems", title_style="bold yellow")
        problem_table.add_column("Line", justify="right")
        problem_table.add_column("Text")
        problem_table.add_column("Problem")
        for p in problems:
            hint = f"\nDid you mean: {', '.join(p.suggestions)}?" if p.suggestions else ""
            problem_table.add_row(str(p.line_number), escape(p.line), escape(p.message + hint))
        console.print(problem_table)


if __name__ == "__main__":
    app()
