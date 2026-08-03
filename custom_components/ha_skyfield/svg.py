"""
Write the sky out as an SVG document.

The shapes and where they go are :mod:`.scene`'s doing; this only writes them
down. What it adds is a stylesheet, built from the same table :mod:`.raster`
paints with, so that the two stay the same chart.

The card builds its drawing once and then only moves things about, because it
redraws every half minute for as long as a dashboard is open. Nothing here is
ever moved again, so everything arrives already in place. Beyond that the two
are meant to be read side by side: the elements and their classes are the card's.
"""

import datetime
from xml.sax.saxutils import escape, quoteattr

from . import scene, styles
from .projection import number
from .styles import PALETTES, STYLES  # noqa: F401 - PALETTES is part of this API

THEMES = ("auto", "light", "dark")

# groups the card wraps in a container element, so the structure reads the same
CONTAINERS = {
    "grid": "grid",
    "compass": "labels",
    "altitude": "labels",
    "legend": "legend",
}

# groups written as a single path, however many things are in them
PATHS = ("stars", "constellation-lines")


def render(
    model: dict,
    *,
    when: datetime.datetime | None = None,
    theme: str = "auto",
    palette: dict | None = None,
    title: str | None = None,
    background: str | None = None,
    element_id: str = "skyfield",
    north_up: bool | None = None,
    horizontal_flip: bool | None = None,
    show_legend: bool | None = None,
    show_time: bool | None = None,
    show_constellations: bool | None = None,
) -> str:
    """
    Draw a sky model as a complete, self-contained SVG document.

    The model is the dictionary from :meth:`bodies.Sky.sky_model`, and it carries
    its own idea of which way round the chart goes and what to show. Passing any
    of those explicitly overrides it, the way a card's configuration overrides
    what the integration sent.

    ``when`` decides where the bodies are placed. Left alone it is the moment the
    model was generated for, which is what makes the output reproducible; giving
    it something else turns the sky to that moment without recomputing anything,
    since the model holds sky coordinates rather than points on the chart.

    ``theme`` picks a set of colors, ``auto`` meaning the reader's own
    preference where that can be asked for. ``palette`` replaces any of them by
    name -- see :data:`styles.PALETTES` for the names.
    """
    if theme not in THEMES:
        raise ValueError(f"theme should be one of {THEMES}, not {theme!r}")

    drawing = scene.build(
        model,
        when=when,
        title=title,
        north_up=north_up,
        horizontal_flip=horizontal_flip,
        show_legend=show_legend,
        show_time=show_time,
        show_constellations=show_constellations,
    )

    clip = f"{element_id}-horizon"
    chart = _groups(drawing.chart, clip)
    if drawing.top:
        # the chart keeps the card's own coordinates and is moved down instead
        chart = f'<g transform="translate(0,{number(drawing.top)})">{chart}</g>'

    return "".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" class="skyfield"',
            f' viewBox="0 0 {number(drawing.width)} {number(drawing.height)}"',
            ' role="img" aria-label="Chart of the sky">',
            f"<style>{stylesheet(theme, palette)}</style>",
            _background(background, drawing),
            f'<defs><clipPath id="{clip}">{_shape(drawing.clip)}</clipPath></defs>',
            chart,
            _groups(drawing.page, clip),
            "</svg>",
        ]
    )


def _groups(groups: list, clip: str) -> str:
    """
    Write out groups, wrapping any run of clipped ones in the horizon.

    A run rather than one wrapper apiece, because the clipped groups sit next to
    each other and one clip path over the lot is what the card emits.
    """
    out = []
    clipping = False
    for group in groups:
        if group.clipped and not clipping:
            out.append(f'<g clip-path="url(#{clip})">')
        elif clipping and not group.clipped:
            out.append("</g>")
        clipping = group.clipped
        out.append(_group(group))
    if clipping:
        out.append("</g>")
    return "".join(out)


def _group(group) -> str:
    if group.style in PATHS or group.style.startswith("sun-path"):
        css = f"{group.style} dashed" if group.dashed else group.style
        return f'<path class="{css}" d="{_path(group.items)}"/>'

    drawn = "".join(
        _shape(item, getattr(item, "style", None) or group.style)
        for item in group.items
    )
    if group.style in CONTAINERS:
        return f'<g class="{CONTAINERS[group.style]}">{drawn}</g>'
    return drawn


def _path(items: list) -> str:
    parts = []
    for item in items:
        if isinstance(item, scene.Dot):
            # a line going nowhere, drawn with a round cap, is a dot
            parts.append(f"M{number(item.x)},{number(item.y)}l0.01,0")
        else:
            points = "L".join(f"{number(x)},{number(y)}" for x, y in item.points)
            parts.append(f"M{points}")
    return "".join(parts)


def _shape(item, css: str = "") -> str:
    attribute = f' class="{css}"' if css else ""
    if isinstance(item, scene.Circle):
        fill = f" fill={quoteattr(item.fill)}" if item.fill else ""
        circle = (
            f'<circle{attribute} cx="{number(item.x)}" cy="{number(item.y)}"'
            f' r="{number(item.radius)}"{fill}'
        )
        if item.label is None:
            return f"{circle}/>"
        # a title is what a screen reader says and what a pointer hovering over
        # it shows, so a body is not identified by its color alone
        return f"{circle}><title>{escape(item.label)}</title></circle>"
    if isinstance(item, scene.Line):
        return (
            f'<line{attribute} x1="{number(item.x1)}" y1="{number(item.y1)}"'
            f' x2="{number(item.x2)}" y2="{number(item.y2)}"/>'
        )
    if isinstance(item, scene.Label):
        return (
            f'<text{attribute} x="{number(item.x)}" y="{number(item.y)}">'
            f"{escape(item.text)}</text>"
        )
    raise TypeError(f"nothing here knows how to write out {item!r}")


def _background(background: str | None, drawing) -> str:
    if background is None:
        return ""
    return (
        f'<rect x="0" y="0" width="{number(drawing.width)}"'
        f' height="{number(drawing.height)}" fill={quoteattr(background)}/>'
    )


def stylesheet(theme: str, overrides: dict | None = None) -> str:
    """The whole stylesheet for a theme, colors and all."""
    if theme == "auto":
        # a browser follows the reader's preference; anything that does not
        # understand the media query is left with the light set, which is the
        # right answer for a rasteriser writing onto white
        return (
            _structure()
            + _colors(styles.palette("light", overrides))
            + "@media (prefers-color-scheme: dark) {"
            + _colors(styles.palette("dark", overrides))
            + "}"
        )
    return _structure() + _colors(styles.palette(theme, overrides))


def _structure() -> str:
    """Everything that is not a color, said once."""
    dashes = " ".join(str(step) for step in styles.DASHES)
    rules = [
        ".grid circle, .grid line, .horizon, .sun-path,"
        " .constellation-lines, .stars { fill: none; }",
        ".constellation-lines, .stars { stroke-linecap: round; }",
        f"text {{ font-family: {styles.FONT_FAMILY};"
        " text-anchor: middle; dominant-baseline: middle; }",
        f".sun-path.dashed {{ stroke-dasharray: {dashes}; }}",
    ]
    for style in STYLES.values():
        parts = []
        if style.stroke:
            parts.append(f"stroke-width: {style.width};")
        if style.opacity != 1:
            # on the group rather than each shape, so that crossing lines do not
            # darken where they overlap
            parts.append(f"opacity: {style.opacity};")
        if style.font_size:
            parts.append(f"font-size: {style.font_size}px;")
        if style.anchor != "middle":
            parts.append(f"text-anchor: {style.anchor};")
        if parts:
            rules.append(f"{style.selector} {{ {' '.join(parts)} }}")
    return "".join(rules)


def _colors(palette: dict) -> str:
    """
    The color half, for one set of colors.

    Emitted whole for each theme rather than as a handful of overrides, because
    a rule inside a media query only beats one outside it when the two selectors
    are equally specific: a dark ``text`` would lose to a light ``text.compass``.
    Identical selectors in both copies leaves source order to decide, which is
    what puts the dark set second.
    """
    rules = []
    for style in STYLES.values():
        parts = []
        if style.stroke:
            parts.append(f"stroke: {palette[style.stroke]};")
        if style.fill:
            parts.append(f"fill: {palette[style.fill]};")
        if parts:
            rules.append(f"{style.selector} {{ {' '.join(parts)} }}")
    return "".join(rules)
