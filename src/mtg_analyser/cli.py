"""Command-line interface. Phase 0 only has a version command; `analyse` arrives in Phase 4."""

import typer
from rich.console import Console

from mtg_analyser import __version__

app = typer.Typer(help="Analyse an MTG decklist's mana curve, colours and lands.")
console = Console()


@app.callback()
def main() -> None:
    """MTG Analyser."""


@app.command()
def version() -> None:
    """Show the installed version."""
    console.print(f"[bold green]mtg-analyser[/] {__version__}")


if __name__ == "__main__":
    app()
