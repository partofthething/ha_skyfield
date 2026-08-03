"""
Draw the sky as an SVG document.

This takes the same description of the sky that the Lovelace card is given by
``bodies.Sky.sky_model`` and draws it the way the card does, so that a chart can
be had without a browser: written to a file for a web page, served by
``server``, or handed to Home Assistant's camera entity.

The card builds its drawing once and then only moves things about, because it
redraws every half minute for as long as a dashboard is open. Nothing here is
ever moved again, so everything arrives already in place. Beyond that the two
are meant to be read side by side: the functions below are named after the card's
own methods and emit the same elements in the same order.

There are three deliberate differences, all of them because there is no Home
Assistant around this one.

Time is the model's rather than the reader's clock, so the same model always
draws the same picture and can be compared against a stored one.

The legend and the timestamp are drawn as SVG in a band below the chart, where
the card emits HTML next to it. The chart itself still occupies 0 to 400 in both
directions, exactly as it does in the card, so the coordinates within it can be
compared directly.

The stylesheet travels inside the document. The card's colours come from Home
Assistant's theme, and those names are still asked for first here, so an SVG
inlined into a themed page picks them up; but each falls back to a colour of our
own, and ``theme`` decides whether the dark set is used, avoided, or left to the
reader's own preference.
"""

import datetime
import math
from xml.sax.saxutils import escape, quoteattr

from . import projection
from .projection import (
    CENTRE,
    COMPASS,
    HORIZON,
    HORIZON_RADIUS,
    RING_STEP,
    SIZE,
    number,
)

# how tall the bands above and below the chart are, in the same units
TITLE_HEIGHT = 30
TIME_HEIGHT = 22
LEGEND_ROW_HEIGHT = 17
LEGEND_COLUMNS = 3
LEGEND_PADDING = 6

# how far outside the horizon the compass letters sit, in degrees of altitude
COMPASS_OFFSET = -7

THEMES = ("auto", "light", "dark")


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

    ``theme`` picks a set of colours, ``auto`` meaning the reader's own
    preference where that can be asked for. ``palette`` replaces any of them by
    name -- see :data:`PALETTES` for the names -- for a chart that has to match
    the page it sits on.
    """
    if theme not in THEMES:
        raise ValueError(f"theme should be one of {THEMES}, not {theme!r}")

    settings = _settings(
        model,
        north_up=north_up,
        horizontal_flip=horizontal_flip,
        show_legend=show_legend,
        show_time=show_time,
        show_constellations=show_constellations,
    )
    if when is None:
        when = datetime.datetime.fromisoformat(model["generated"])

    project = projection.projector(
        north_up=settings["north_up"], horizontal_flip=settings["horizontal_flip"]
    )
    observer = projection.observer_at(model["latitude"], model["longitude"], when)

    bodies = model.get("bodies", [])
    constellations = (
        model.get("constellations", []) if settings["show_constellations"] else []
    )

    top = TITLE_HEIGHT if title else 0
    bands = []
    if settings["show_time"]:
        bands.append(_when(when, top + SIZE))
    if settings["show_legend"] and bodies:
        bands.append(
            _legend(bodies, top + SIZE + (TIME_HEIGHT if settings["show_time"] else 0))
        )

    height = top + SIZE + (TIME_HEIGHT if settings["show_time"] else 0)
    if settings["show_legend"] and bodies:
        height += _legend_height(bodies)

    clip = f"{element_id}-horizon"
    chart = "".join(
        [
            f'<g class="grid">{_grid(project)}</g>',
            f'<g clip-path="url(#{clip})">',
            "".join(_sun_path(path, project) for path in model.get("paths", [])),
            _constellations(constellations, observer, project),
            f'<g class="bodies">{_bodies(bodies, observer, project)}</g>',
            "</g>",
            f'<circle class="horizon" cx="{number(CENTRE)}" cy="{number(CENTRE)}"'
            f' r="{number(HORIZON_RADIUS)}"/>',
            f'<g class="labels">{_labels(project)}</g>',
        ]
    )

    return "".join(
        [
            '<svg xmlns="http://www.w3.org/2000/svg" class="skyfield"',
            f' viewBox="0 0 {number(SIZE)} {number(height)}"',
            ' role="img" aria-label="Chart of the sky">',
            f"<style>{_styles(theme, palette)}</style>",
            _background(background, height),
            _title(title) if title else "",
            f'<defs><clipPath id="{clip}">'
            f'<circle cx="{number(CENTRE)}" cy="{number(CENTRE)}"'
            f' r="{number(HORIZON_RADIUS)}"/></clipPath></defs>',
            f'<g transform="translate(0,{number(top)})">{chart}</g>' if top else chart,
            "".join(bands),
            "</svg>",
        ]
    )


def _settings(model: dict, **overrides) -> dict:
    """What the model asked for, with anything given explicitly winning."""
    settings = {
        "north_up": model.get("north_up", False),
        "horizontal_flip": model.get("horizontal_flip", False),
        "show_legend": model.get("show_legend", True),
        "show_time": model.get("show_time", True),
        # the model has no say in this one: it either sent constellations or it
        # did not, and asking to draw ones that were never sent draws nothing
        "show_constellations": True,
    }
    settings.update(
        {key: value for key, value in overrides.items() if value is not None}
    )
    return settings


def _grid(project) -> str:
    """Rings of equal altitude and spokes of equal azimuth."""
    rings = [
        f'<circle cx="{number(CENTRE)}" cy="{number(CENTRE)}"'
        f' r="{number(projection.radius_for(altitude))}"/>'
        for altitude in range(0, HORIZON, RING_STEP)
    ]
    spokes = []
    for index in range(len(COMPASS)):
        x, y = project(index * 360 / len(COMPASS), 0)
        spokes.append(
            f'<line x1="{number(CENTRE)}" y1="{number(CENTRE)}"'
            f' x2="{number(x)}" y2="{number(y)}"/>'
        )
    return "".join(rings) + "".join(spokes)


def _labels(project) -> str:
    """The compass points, and the altitude each ring stands for."""
    labels = []
    for index, name in enumerate(COMPASS):
        x, y = project(index * 360 / len(COMPASS), COMPASS_OFFSET)
        labels.append(
            f'<text class="compass" x="{number(x)}" y="{number(y)}">{name}</text>'
        )

    # the horizon is labelled by the compass points already, and putting a 0
    # there as well would sit on top of them
    for altitude in range(RING_STEP, HORIZON, RING_STEP):
        x, y = project(0, altitude)
        labels.append(
            f'<text class="altitude" x="{number(x)}" y="{number(y)}">{altitude}°</text>'
        )
    return "".join(labels)


def _sun_path(path: dict, project) -> str:
    """One of the Sun's daily paths, a fixed curve for the day."""
    points = []
    for azimuth, altitude in zip(path["azimuth"], path["altitude"], strict=True):
        x, y = project(azimuth, altitude)
        points.append(f"{number(x)},{number(y)}")
    dashed = " dashed" if path.get("dashed") else ""
    return f'<path class="sun-path {path["name"]}{dashed}" d="M{"L".join(points)}"/>'


def _bodies(bodies: list, observer, project) -> str:
    """A circle per body, already where it belongs."""
    drawn = []
    for body in bodies:
        azimuth, altitude = projection.alt_az(body["ra"], body["dec"], observer)
        x, y = project(azimuth, altitude)
        label = escape(body["label"])
        drawn.append(
            f'<circle class="body" fill={quoteattr(body["color"])}'
            f' cx="{number(x)}" cy="{number(y)}"'
            f' r="{number(projection.body_radius(body["size"]))}">'
            f"<title>{label}</title></circle>"
        )
    return "".join(drawn)


def _constellations(constellations: list, observer, project) -> str:
    """
    Every constellation as two paths: one of lines, one of stars.

    Two long paths rather than an element per star is what keeps a chart with a
    thousand stars in it a reasonable size, and it is how the card does it.
    """
    lines = []
    stars = []

    for constellation in constellations:
        placed = [
            projection.alt_az(ra, dec, observer) for ra, dec in constellation["stars"]
        ]

        for azimuth, altitude in placed:
            if altitude < 0:
                continue
            x, y = project(azimuth, altitude)
            # a line going nowhere, drawn with a round cap, is a dot
            stars.append(f"M{number(x)},{number(y)}l0.01,0")

        for start, end in constellation["lines"]:
            azi1, alt1 = placed[start]
            azi2, alt2 = placed[end]
            if alt1 < 0 and alt2 < 0:
                continue
            # go the short way round, rather than the wrong way across the chart
            azi2 -= math.floor((azi2 - azi1) / 360 + 0.5) * 360
            lines.append(_line(azi1, alt1, azi2, alt2, project))

    return (
        f'<path class="constellation-lines" d="{"".join(lines)}"/>'
        f'<path class="stars" d="{"".join(stars)}"/>'
    )


def _line(azi1: float, alt1: float, azi2: float, alt2: float, project) -> str:
    """A constellation line, bent to follow the projection."""
    points = []
    for step in range(projection.POINTS_PER_LINE):
        along = step / (projection.POINTS_PER_LINE - 1)
        x, y = project(azi1 + (azi2 - azi1) * along, alt1 + (alt2 - alt1) * along)
        points.append(f"{number(x)},{number(y)}")
    return f"M{'L'.join(points)}"


def _title(title: str) -> str:
    return (
        f'<text class="title" x="{number(CENTRE)}" y="{number(TITLE_HEIGHT / 2)}">'
        f"{escape(title)}</text>"
    )


def _when(when: datetime.datetime, top: float) -> str:
    """The moment drawn, naming its zone since the reader's is often not it."""
    stamp = escape(when.strftime("%Y-%m-%d %H:%M:%S %Z").strip())
    return (
        f'<text class="when" x="{number(CENTRE)}" y="{number(top + TIME_HEIGHT / 2)}">'
        f"{stamp}</text>"
    )


def _legend_height(bodies: list) -> float:
    rows = math.ceil(len(bodies) / LEGEND_COLUMNS)
    return rows * LEGEND_ROW_HEIGHT + 2 * LEGEND_PADDING


def _legend(bodies: list, top: float) -> str:
    """Names beside colours, so nothing is identified by its colour alone."""
    column_width = SIZE / LEGEND_COLUMNS
    entries = []
    for index, body in enumerate(bodies):
        column = index % LEGEND_COLUMNS
        row = index // LEGEND_COLUMNS
        x = column * column_width + LEGEND_PADDING * 2
        y = top + LEGEND_PADDING + row * LEGEND_ROW_HEIGHT + LEGEND_ROW_HEIGHT / 2
        entries.append(
            f'<circle class="swatch" cx="{number(x)}" cy="{number(y)}" r="5"'
            f" fill={quoteattr(body['color'])}/>"
            f'<text class="legend" x="{number(x + 10)}" y="{number(y)}">'
            f"{escape(body['label'])}</text>"
        )
    return f'<g class="legend">{"".join(entries)}</g>'


def _background(background: str | None, height: float) -> str:
    if background is None:
        return ""
    return (
        f'<rect x="0" y="0" width="{number(SIZE)}" height="{number(height)}"'
        f" fill={quoteattr(background)}/>"
    )


# Colours are written into the stylesheet literally rather than through CSS
# custom properties. The card can lean on `var(--primary-text-color, ...)`
# because it is inlined into a themed page, but a standalone chart is usually
# loaded through `<img>` or a rasteriser, and neither inherits anything: an
# `<img>` renders the SVG as its own isolated document, and librsvg -- which is
# what ImageMagick and most PDF pipelines reach for -- does not implement `var()`
# at all, so it drew everything with no stroke and produced a blank circle.
PALETTES = {
    "light": {
        "ink": "#212121",
        "muted": "#727272",
        "grid": "#e0e0e0",
        "winter": "#3f7fd0",
        "summer": "#3c8c40",
        "star": "#212121",
        "edge": "rgba(0, 0, 0, 0.55)",
    },
    "dark": {
        "ink": "#e3e3e3",
        "muted": "#9b9b9b",
        "grid": "#3a3a3a",
        "winter": "#6ba4e8",
        "summer": "#63b767",
        "star": "#f0f0f0",
        "edge": "rgba(0, 0, 0, 0.75)",
    },
}

# everything that is not a colour, said once
_STRUCTURE = """
  .grid circle, .grid line { fill: none; stroke-width: 1; }
  .horizon { fill: none; stroke-width: 2.5; }
  text {
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 11px;
    text-anchor: middle;
    dominant-baseline: middle;
  }
  text.compass { font-size: 12px; }
  text.title { font-size: 16px; }
  text.when { font-size: 12px; }
  text.legend { font-size: 12px; text-anchor: start; }
  .swatch, .body { stroke-width: 1; }
  .sun-path { fill: none; stroke-width: 1.5; }
  .sun-path.today { opacity: 0.85; }
  .sun-path.dashed { stroke-dasharray: 5 4; opacity: 0.9; }
  .constellation-lines, .stars { fill: none; stroke-linecap: round; }
  /* the joins are meant to be a hint, so they stay faint */
  .constellation-lines { stroke-width: 1; opacity: 0.28; }
  .stars { stroke-width: 2.6; opacity: 0.9; }
"""


def _colours(palette: dict) -> str:
    """
    The colour half of the stylesheet, for one set of colours.

    Emitted whole for each theme rather than as a handful of overrides, because
    a rule inside a media query only beats one outside it when the two selectors
    are equally specific: a dark `text` would lose to a light `text.compass`.
    Identical selectors in both copies leaves source order to decide, which is
    what puts the dark set second.
    """
    return f"""
  .grid circle, .grid line {{ stroke: {palette["grid"]}; }}
  .horizon {{ stroke: {palette["ink"]}; }}
  text {{ fill: {palette["muted"]}; }}
  text.compass {{ fill: {palette["ink"]}; }}
  text.title {{ fill: {palette["ink"]}; }}
  .swatch, .body {{ stroke: {palette["edge"]}; }}
  .sun-path.today {{ stroke: {palette["ink"]}; }}
  .sun-path.winter_solstice {{ stroke: {palette["winter"]}; }}
  .sun-path.summer_solstice {{ stroke: {palette["summer"]}; }}
  .constellation-lines {{ stroke: {palette["ink"]}; }}
  .stars {{ stroke: {palette["star"]}; }}
"""


def _styles(theme: str, overrides: dict | None) -> str:
    def palette(name):
        return {**PALETTES[name], **(overrides or {})}

    if theme == "auto":
        # a browser follows the reader's preference; anything that does not
        # understand the media query is left with the light set, which is the
        # right answer for a rasteriser writing onto white
        return (
            _STRUCTURE
            + _colours(palette("light"))
            + f"@media (prefers-color-scheme: dark) {{{_colours(palette('dark'))}}}"
        )
    return _STRUCTURE + _colours(palette(theme))
