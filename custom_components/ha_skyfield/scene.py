"""
The chart worked out as shapes, before anything decides what to draw them with.

There are two people who draw this: :mod:`.svg` writes it out as a document, and
:mod:`.raster` paints it into a picture. Both want the same rings in the same
places, so the arithmetic that decides where things go lives here and is done
once.

Everything in :attr:`Scene.chart` is in the four-hundred-unit square the card
lays itself out in, so those coordinates can be compared against the card's
directly. Anything above or below the chart -- a title, the time, the legend --
is in :attr:`Scene.page`, already offset.
"""

import datetime
import math
from dataclasses import dataclass, field

from . import projection
from .projection import CENTRE, COMPASS, HORIZON, HORIZON_RADIUS, RING_STEP, SIZE

# how tall the bands above and below the chart are, in the same units
TITLE_HEIGHT = 30
TIME_HEIGHT = 22
LEGEND_ROW_HEIGHT = 17
LEGEND_COLUMNS = 3
LEGEND_PADDING = 6

# how far outside the horizon the compass letters sit, in degrees of altitude
COMPASS_OFFSET = -7

# how big a legend swatch is
SWATCH_RADIUS = 5


@dataclass
class Circle:
    x: float
    y: float
    radius: float
    fill: str | None = None
    # what this is, for a reader who cannot tell the colours apart
    label: str | None = None
    # where a group holds more than one kind of thing, as the legend does
    style: str | None = None


@dataclass
class Line:
    x1: float
    y1: float
    x2: float
    y2: float


@dataclass
class Polyline:
    points: list


@dataclass
class Dot:
    x: float
    y: float


@dataclass
class Label:
    x: float
    y: float
    text: str
    style: str | None = None


@dataclass
class Group:
    """
    Things drawn alike, and drawn together.

    Together matters: the constellation joins are drawn faintly, and a group
    faded as one keeps them from darkening where they cross, which is what the
    SVG gets from putting them in a single element.
    """

    style: str
    items: list = field(default_factory=list)
    clipped: bool = False
    # the model says which of the Sun's paths are dashed, not the style table
    dashed: bool = False


@dataclass
class Scene:
    width: float
    height: float
    # how far down the page the chart's own square starts
    top: float
    chart: list
    page: list
    clip: Circle


def build(
    model: dict,
    *,
    when: datetime.datetime | None = None,
    title: str | None = None,
    north_up: bool | None = None,
    horizontal_flip: bool | None = None,
    show_legend: bool | None = None,
    show_time: bool | None = None,
    show_constellations: bool | None = None,
) -> Scene:
    """Work out where everything in a sky model goes."""
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

    chart = [_grid(project)]
    for path in model.get("paths", []):
        chart.append(_sun_path(path, project))
    chart.extend(_stick_figures(constellations, observer, project))
    chart.append(_bodies(bodies, observer, project))
    chart.append(Group("horizon", [Circle(CENTRE, CENTRE, HORIZON_RADIUS)]))
    chart.extend(_labels(project))

    top = TITLE_HEIGHT if title else 0
    page = []
    if title:
        page.append(Group("title", [Label(CENTRE, TITLE_HEIGHT / 2, title)]))

    below = top + SIZE
    if settings["show_time"]:
        page.append(
            Group("when", [Label(CENTRE, below + TIME_HEIGHT / 2, _when(when))])
        )
        below += TIME_HEIGHT

    height = below
    if settings["show_legend"] and bodies:
        page.append(_legend(bodies, below))
        height = below + legend_height(bodies)

    return Scene(
        width=SIZE,
        height=height,
        top=top,
        chart=chart,
        page=page,
        clip=Circle(CENTRE, CENTRE, HORIZON_RADIUS),
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


def _grid(project) -> Group:
    """Rings of equal altitude and spokes of equal azimuth."""
    items = [
        Circle(CENTRE, CENTRE, projection.radius_for(altitude))
        for altitude in range(0, HORIZON, RING_STEP)
    ]
    for index in range(len(COMPASS)):
        x, y = project(index * 360 / len(COMPASS), 0)
        items.append(Line(CENTRE, CENTRE, x, y))
    return Group("grid", items)


def _labels(project) -> list:
    """The compass points, and the altitude each ring stands for."""
    compass = []
    for index, name in enumerate(COMPASS):
        x, y = project(index * 360 / len(COMPASS), COMPASS_OFFSET)
        compass.append(Label(x, y, name))

    # the horizon is labelled by the compass points already, and putting a 0
    # there as well would sit on top of them
    altitudes = []
    for altitude in range(RING_STEP, HORIZON, RING_STEP):
        x, y = project(0, altitude)
        altitudes.append(Label(x, y, f"{altitude}\N{DEGREE SIGN}"))

    return [Group("compass", compass), Group("altitude", altitudes)]


def _sun_path(path: dict, project) -> Group:
    """One of the Sun's daily paths, a fixed curve for the day."""
    points = [
        project(azimuth, altitude)
        for azimuth, altitude in zip(path["azimuth"], path["altitude"], strict=True)
    ]
    return Group(
        f"sun-path {path['name']}",
        [Polyline(points)],
        clipped=True,
        dashed=bool(path.get("dashed")),
    )


def _bodies(bodies: list, observer, project) -> Group:
    """A circle per body, already where it belongs."""
    drawn = []
    for body in bodies:
        azimuth, altitude = projection.alt_az(body["ra"], body["dec"], observer)
        x, y = project(azimuth, altitude)
        drawn.append(
            Circle(
                x,
                y,
                projection.body_radius(body["size"]),
                fill=body["color"],
                label=body["label"],
            )
        )
    return Group("body", drawn, clipped=True)


def _stick_figures(constellations: list, observer, project) -> list:
    """
    The constellations, as joins and as stars.

    Two groups rather than an element apiece: it is what keeps a chart with a
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
            stars.append(Dot(*project(azimuth, altitude)))

        for start, end in constellation["lines"]:
            azi1, alt1 = placed[start]
            azi2, alt2 = placed[end]
            if alt1 < 0 and alt2 < 0:
                continue
            # go the short way round, rather than the wrong way across the chart
            azi2 -= math.floor((azi2 - azi1) / 360 + 0.5) * 360
            lines.append(Polyline(_bend(azi1, alt1, azi2, alt2, project)))

    return [
        Group("constellation-lines", lines, clipped=True),
        Group("stars", stars, clipped=True),
    ]


def _bend(azi1: float, alt1: float, azi2: float, alt2: float, project) -> list:
    """A constellation line, bent to follow the projection."""
    points = []
    for step in range(projection.POINTS_PER_LINE):
        along = step / (projection.POINTS_PER_LINE - 1)
        points.append(
            project(azi1 + (azi2 - azi1) * along, alt1 + (alt2 - alt1) * along)
        )
    return points


def _when(when: datetime.datetime) -> str:
    """The moment drawn, naming its zone since the reader's is often not it."""
    return when.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def legend_height(bodies: list) -> float:
    rows = math.ceil(len(bodies) / LEGEND_COLUMNS)
    return rows * LEGEND_ROW_HEIGHT + 2 * LEGEND_PADDING


def _legend(bodies: list, top: float) -> Group:
    """
    Names beside colours, so nothing is identified by its colour alone.

    One group holding both the swatches and the names, since they belong
    together, with each item saying how it is drawn.
    """
    column_width = SIZE / LEGEND_COLUMNS
    items = []
    for index, body in enumerate(bodies):
        column = index % LEGEND_COLUMNS
        row = index // LEGEND_COLUMNS
        x = column * column_width + LEGEND_PADDING * 2
        y = top + LEGEND_PADDING + row * LEGEND_ROW_HEIGHT + LEGEND_ROW_HEIGHT / 2
        items.append(Circle(x, y, SWATCH_RADIUS, fill=body["color"], style="swatch"))
        items.append(Label(x + 10, y, body["label"], style="legend"))
    return Group("legend", items)
