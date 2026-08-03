"""
What each part of the chart looks like.

One table, read by both people who draw it: :mod:`.svg` turns it into a
stylesheet and :mod:`.raster` into pen colours and widths. Keeping it here rather
than writing it out twice is what stops a chart drawn as a picture from slowly
diverging from the same chart drawn as an SVG.

Colours are named rather than given, and looked up in a palette, so that a
light and a dark chart differ only in the palette and not in the table.
"""

from typing import NamedTuple

# Written out literally rather than as CSS custom properties. The card can lean
# on `var(--primary-text-color, ...)` because it is inlined into a themed page,
# but a standalone chart is usually loaded through `<img>` or a rasteriser, and
# neither inherits anything: an `<img>` renders the SVG as its own isolated
# document, and librsvg -- which is what ImageMagick and most PDF pipelines reach
# for -- does not implement `var()` at all.
PALETTES = {
    "light": {
        "ink": "#212121",
        "muted": "#727272",
        "grid": "#e0e0e0",
        "winter": "#3f7fd0",
        "summer": "#3c8c40",
        "star": "#212121",
        "edge": "#0000008c",
        "paper": "#ffffff",
    },
    "dark": {
        "ink": "#e3e3e3",
        "muted": "#9b9b9b",
        "grid": "#3a3a3a",
        "winter": "#6ba4e8",
        "summer": "#63b767",
        "star": "#f0f0f0",
        "edge": "#000000bf",
        "paper": "#101318",
    },
}


class Style(NamedTuple):
    """How one kind of thing is drawn."""

    selector: str
    # names of palette entries, or None where the drawing supplies its own
    stroke: str | None = None
    fill: str | None = None
    width: float = 1.0
    # applied to a whole group at once, so that crossing lines do not darken
    # where they overlap
    opacity: float = 1.0
    font_size: float | None = None
    anchor: str = "middle"


# how a dashed path is dashed. Which paths are dashed is the model's to say --
# ``BodyPath.describe`` sends it -- not this table's.
DASHES = (5, 4)

STYLES = {
    "grid": Style(".grid circle, .grid line", stroke="grid", width=1),
    "horizon": Style(".horizon", stroke="ink", width=2.5),
    "sun-path today": Style(".sun-path.today", stroke="ink", width=1.5, opacity=0.85),
    "sun-path winter_solstice": Style(
        ".sun-path.winter_solstice", stroke="winter", width=1.5, opacity=0.9
    ),
    "sun-path summer_solstice": Style(
        ".sun-path.summer_solstice", stroke="summer", width=1.5, opacity=0.9
    ),
    # the joins are meant to be a hint, so they stay faint
    "constellation-lines": Style(
        ".constellation-lines", stroke="ink", width=1, opacity=0.28
    ),
    "stars": Style(".stars", stroke="star", width=2.6, opacity=0.9),
    "body": Style(".body", stroke="edge", width=1),
    "swatch": Style(".swatch", stroke="edge", width=1),
    "compass": Style("text.compass", fill="ink", font_size=12),
    "altitude": Style("text.altitude", fill="muted", font_size=11),
    "title": Style("text.title", fill="ink", font_size=16),
    "when": Style("text.when", fill="muted", font_size=12),
    "legend": Style("text.legend", fill="muted", font_size=12, anchor="start"),
}

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def palette(theme: str, overrides: dict | None = None) -> dict:
    """The colours for a theme, with any of them replaced by name."""
    return {**PALETTES[theme], **(overrides or {})}
