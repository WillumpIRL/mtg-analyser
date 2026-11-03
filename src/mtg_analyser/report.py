"""Terminal rendering of an analysis with Rich. Only the CLI imports this module.

Every function returns Rich renderables rather than printing, so the CLI decides
where output goes (and tests can render to a string).
"""

from __future__ import annotations

from rich.console import Group, RenderableType
from rich.markup import escape
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from mtg_analyser.analysis import CURVE_TOP, KEEPABLE_LANDS, DeckAnalysis, LandStatus
from mtg_analyser.legality import LegalityNote
from mtg_analyser.mana import COLOUR_NAMES, colour_key
from mtg_analyser.models import Deck, DeckFormat, DeckProblem, ResolvedEntry, Section

BAR_WIDTH = 30
OK = "[green]✓[/]"
BAD = "[red]✗[/]"


def _heading(title: str) -> Rule:
    return Rule(f"[bold]{title}[/]", align="left", style="dim")


def _plain_table(*columns: str, right: tuple[str, ...] = ()) -> Table:
    table = Table(box=None, pad_edge=False, padding=(0, 2, 0, 0), header_style="bold")
    for column in columns:
        table.add_column(column, justify="right" if column in right else "left")
    return table


# ---------- sections ----------


def problems_section(problems: list[DeckProblem]) -> RenderableType:
    lines = [f"[yellow]⚠ {len(problems)} line(s) couldn't be used:[/]"]
    for p in problems:
        hint = f" Did you mean: {', '.join(p.suggestions)}?" if p.suggestions else ""
        lines.append(f"  Line {p.line_number}: {escape(p.message + hint)}")
    return "\n".join(lines)


def summary_section(name: str, deck: Deck, analysis: DeckAnalysis) -> RenderableType:
    fmt = deck.format
    kind = "Unknown-format" if fmt == DeckFormat.UNKNOWN else fmt.capitalize()
    parts = [f"{kind} deck", f"{deck.total_cards()} cards"]
    commanders = [escape(e.name) for e in deck.commanders()]
    if commanders:
        parts.append(f"commander: {', '.join(commanders)}")
    sideboard = deck.total_cards(Section.SIDEBOARD)
    if sideboard:
        how = "included" if analysis.include_sideboard else "not analysed; --with-sideboard"
        parts.append(f"sideboard {sideboard} ({how})")
    return Group(_heading(escape(name)), " · ".join(parts))


def curve_section(analysis: DeckAnalysis) -> RenderableType:
    spells = sum(analysis.curve.values())
    top = max(analysis.curve.values(), default=0) or 1
    table = _plain_table("MV", "", "Cards", right=("MV", "Cards"))
    for mv, n in analysis.curve.items():
        label = f"{mv}+" if mv == CURVE_TOP else str(mv)
        bar = "█" * round(n / top * BAR_WIDTH) if n else ""
        table.add_row(label, f"[blue]{bar}[/]", str(n) if n else "[dim]0[/]")
    subtitle = (
        f"{spells} nonland cards in the library, "
        f"average mana value {analysis.average_mana_value:.2f}"
    )
    return Group(_heading("Mana curve"), subtitle, table)


def lands_section(analysis: DeckAnalysis) -> RenderableType:
    lc = analysis.land_check
    have = f"{lc.lands} lands"
    if lc.mdfc_lands:
        have += f" + {lc.mdfc_lands} MDFCs (worth {lc.mdfc_land_value:.2f}) = {lc.effective:.1f}"
    lines = [have]
    if lc.recommended is None:
        lines.append("[dim]Too few cards to recommend a land count.[/]")
    else:
        difference = lc.effective - lc.recommended
        verdict = {
            LandStatus.OK: f"{OK} about right",
            LandStatus.TOO_FEW: f"{BAD} too few, by {-difference:.1f}",
            LandStatus.TOO_MANY: f"{BAD} too many, by {difference:.1f}",
        }[lc.status]
        lines.append(
            f"Recommended: {lc.recommended:.1f}  {verdict}\n"
            f"[dim]Karsten's formula: average mana value {analysis.average_mana_value:.2f}, "
            f"{lc.cheap_draw_or_ramp} cheap card draw/ramp spells. "
            "MDFCs count 0.38 of a land, 0.74 if mythic.[/]"
        )
    return Group(_heading("Lands"), *lines)


def colours_section(analysis: DeckAnalysis) -> RenderableType:
    parts: list[RenderableType] = [_heading("Colours")]
    if not analysis.pips:
        parts.append("No coloured mana symbols.")
        return Group(*parts)

    share = analysis.pip_share
    pips = _plain_table(
        "Colour", "Pips", "Share", "Land sources", right=("Pips", "Share", "Land sources")
    )
    for colour in colour_key(analysis.pips):  # only colours the deck uses
        pips.add_row(
            COLOUR_NAMES[colour],
            f"{analysis.pips[colour]:g}",
            f"{share[colour]:.0%}",
            f"{analysis.sources.get(colour, 0):g}",
        )
    parts.append(pips)

    if analysis.requirements:
        parts.append("")
        parts.append("Sources needed to cast each colour's hardest card on curve:")
        reqs = _plain_table(
            "Colours",
            "Hardest card",
            "Cost",
            "Turn",
            "Need",
            "Have",
            "",
            right=("Turn", "Need", "Have"),
        )
        for r in analysis.requirements:
            colours = " or ".join(COLOUR_NAMES[c] for c in colour_key(r.colours))
            status = f"{OK} ok" if r.met else f"{BAD} short by {r.shortfall:g}"
            reqs.add_row(
                colours,
                escape(r.card),
                escape(r.mana_cost),
                str(r.turn),
                str(r.required),
                f"{r.available:g}",
                status,
            )
        parts.append(reqs)
        parts.append(
            "[dim]Turn-1 cards count only untapped lands; mana dorks count ½ and rocks ¾ "
            "of a source.[/]"
        )
    return Group(*parts)


def hand_section(analysis: DeckAnalysis) -> RenderableType:
    hand = analysis.hand
    commander = analysis.format == DeckFormat.COMMANDER
    intro = f"{hand.lands} lands (MDFCs included) in a {hand.library_size}-card library."

    opening = _plain_table("Lands in opening 7", *map(str, range(len(hand.opening_lands))))
    opening.add_row("Chance", *(f"{p:.0%}" for p in hand.opening_lands))
    low, high = KEEPABLE_LANDS.start, KEEPABLE_LANDS.stop - 1
    keepable = f"Keepable ({low}–{high} lands): [bold]{hand.keepable:.0%}[/]"

    if commander:
        drops = _plain_table("Turn", "Land drop made", right=("Turn", "Land drop made"))
        for turn, chance, _ in hand.land_drops:
            drops.add_row(str(turn), f"{chance:.0%}")
        note = "[dim]Commander: everyone draws on turn 1, so play and draw are the same.[/]"
    else:
        drops = _plain_table(
            "Turn", "On the play", "On the draw", right=("Turn", "On the play", "On the draw")
        )
        for turn, play, draw in hand.land_drops:
            drops.add_row(str(turn), f"{play:.0%}", f"{draw:.0%}")
        note = "[dim]Chance of having played a land every turn so far. No mulligans.[/]"
    return Group(_heading("Opening hand"), intro, opening, keepable, "", drops, note)


def checks_section(notes: list[LegalityNote]) -> RenderableType:
    lines: list[str] = []
    if not notes:
        lines.append(f"{OK} Deck size and copy limits look fine.")
    for n in notes:
        lines.append(f"{BAD} {escape(n.message)}")
        if len(n.cards) > 1:
            lines.append(f"  [dim]{escape(', '.join(n.cards))}[/]")
    lines.append("[dim]Ban lists and set legality aren't checked.[/]")
    return Group(_heading("Deck checks"), *lines)


def cards_section(deck: Deck, resolved: list[ResolvedEntry]) -> RenderableType:
    """How each line was read: the old `parse` command's table."""
    matched = {r.entry.line_number: r.card.name for r in resolved}
    table = _plain_table("Line", "Section", "Qty", "Name", "Card", right=("Line", "Qty"))
    for e in deck.entries:
        card = matched.get(e.line_number, "[yellow]not found[/]")
        table.add_row(str(e.line_number), str(e.section), str(e.quantity), escape(e.name), card)
    return Group(_heading("Cards"), table)


def full_report(
    name: str,
    deck: Deck,
    resolved: list[ResolvedEntry],
    analysis: DeckAnalysis,
    notes: list[LegalityNote],
    problems: list[DeckProblem],
    *,
    show_cards: bool = False,
) -> list[RenderableType]:
    """Every section, in reading order, with a blank line between them."""
    sections: list[RenderableType] = []
    if problems:
        sections.append(problems_section(problems))
    sections.append(summary_section(name, deck, analysis))
    if show_cards:
        sections.append(cards_section(deck, resolved))
    sections += [
        curve_section(analysis),
        lands_section(analysis),
        colours_section(analysis),
        hand_section(analysis),
        checks_section(notes),
    ]
    spaced: list[RenderableType] = []
    for section in sections:
        spaced += [section, Text("")]
    return spaced
