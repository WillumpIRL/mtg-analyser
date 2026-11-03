"""Save an analysis as a PNG chart: the mana curve, and sources against what each
colour's hardest card needs.

Uses matplotlib's object-oriented Figure API (no pyplot), so nothing opens a window
and no global state is touched.

Style: one series colour; text in ink colours, never the data colour; thin bars
and solid hairline gridlines. Bars are not coloured by Magic colour: white would
vanish on the background and red/green can't be told apart by colour-blind
readers, so colours are named in the labels instead.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib import rc_context
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from mtg_analyser.analysis import CURVE_TOP, DeckAnalysis, Requirement
from mtg_analyser.mana import COLOUR_NAMES, colour_key

SURFACE = "#fcfcfb"
SERIES = "#2a78d6"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

DPI = 150
FONTS = ["Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]
MAX_LABEL = 30
MIN_ROWS = 4  # the sources panel always has room for at least this many rows


def _style(ax: Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(AXIS)
    ax.tick_params(colors=INK_MUTED, length=0, labelsize=9)
    ax.set_axisbelow(True)


def _title(ax: Axes, title: str, subtitle: str) -> None:
    ax.set_title(title, loc="left", color=INK, fontsize=12, fontweight="semibold", pad=22)
    ax.text(0, 1.02, subtitle, transform=ax.transAxes, color=INK_SECONDARY, fontsize=9, va="bottom")


def _draw_curve(ax: Axes, analysis: DeckAnalysis) -> None:
    labels = [f"{mv}+" if mv == CURVE_TOP else str(mv) for mv in analysis.curve]
    counts = list(analysis.curve.values())
    x = range(len(counts))
    ax.bar(x, counts, width=0.3, color=SERIES)
    ax.set_xticks(list(x), labels)
    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True))  # card counts are whole
    ax.tick_params(axis="y", labelleft=True)
    ax.set_xlabel("Mana value", color=INK_MUTED, fontsize=9)
    top = max(counts, default=0)
    ax.set_ylim(0, max(top * 1.15, 1))
    for xi, n in zip(x, counts, strict=True):
        if n:
            ax.text(xi, n, f"{n}", ha="center", va="bottom", color=INK_SECONDARY, fontsize=9)
    spells = sum(counts)
    _title(
        ax,
        "Mana curve",
        f"{spells} nonland cards, average mana value {analysis.average_mana_value:.2f}",
    )


def _requirement_label(req: Requirement) -> str:
    names = " or ".join(COLOUR_NAMES[c] for c in colour_key(req.colours))
    card = req.card.split(" // ")[0]
    if len(card) > MAX_LABEL:
        card = card[: MAX_LABEL - 1] + "…"
    return f"{names}: {card}"


def _draw_sources(ax: Axes, analysis: DeckAnalysis) -> None:
    reqs = analysis.requirements
    _title(
        ax,
        "Can each colour cast its hardest card on curve?",
        "Bar: sources you have. Tick: sources needed (Karsten 2022).",
    )
    if not reqs:
        ax.set_axis_off()
        ax.text(0, 0.5, "No coloured mana requirements to check.", color=INK_SECONDARY)
        return

    # Rows have a fixed height (save_chart sizes the figure from the row count), and
    # a short list fills from the top rather than stretching its bars.
    slots = max(len(reqs), MIN_ROWS)
    y = [slots - 1 - i for i in range(len(reqs))]
    have = [r.available for r in reqs]
    need = [r.required for r in reqs]
    ax.barh(y, have, height=0.28, color=SERIES)
    ax.scatter(need, y, marker="|", s=260, linewidths=2, color=INK, zorder=3)
    ax.set_yticks(y, [_requirement_label(r) for r in reqs])
    ax.tick_params(axis="y", labelcolor=INK_SECONDARY)
    ax.xaxis.grid(True, color=GRID, linewidth=1)
    ax.spines["bottom"].set_visible(False)
    ax.spines["left"].set_visible(True)
    ax.spines["left"].set_color(AXIS)
    right = max(max(have), max(need)) * 1.55  # room for the text after each bar
    ax.set_xlim(0, right)
    ax.set_ylim(-0.6, slots - 0.4)
    for yi, r in zip(y, reqs, strict=True):
        status = "ok" if r.met else f"short by {r.shortfall:g}"
        ax.text(
            max(r.available, r.required) + right * 0.02,
            yi,
            f"have {r.available:g}, need {r.required} by turn {r.turn} · {status}",
            va="center",
            color=INK if not r.met else INK_SECONDARY,
            fontsize=8.5,
            fontweight="semibold" if not r.met else "normal",
        )


def save_chart(analysis: DeckAnalysis, path: Path, title: str) -> Path:
    """Draw the chart and save it as a PNG at `path` (folders are created)."""
    rows = max(len(analysis.requirements), MIN_ROWS)
    height = 1.6 + 0.42 * rows
    with rc_context({"font.family": "sans-serif", "font.sans-serif": FONTS}):
        fig = Figure(figsize=(13, height), dpi=DPI, facecolor=SURFACE, layout="constrained")
        fig.suptitle(title, x=0.01, ha="left", color=INK, fontsize=14, fontweight="semibold")
        curve_ax, sources_ax = fig.subplots(1, 2, width_ratios=[1, 1.5])
        for ax in (curve_ax, sources_ax):
            _style(ax)
        _draw_curve(curve_ax, analysis)
        _draw_sources(sources_ax, analysis)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, facecolor=SURFACE)
    return path
