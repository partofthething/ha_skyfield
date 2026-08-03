"""
Where a point of sky lands on the drawing.

This is the same arithmetic the Lovelace card does in JavaScript, kept here in
Python so that the chart can be drawn without a browser: for a web page, for a
file on disk, or for anything else that wants the picture rather than the data.

Two things are worth knowing about it.

The first is that this deliberately does not go through skyfield. Given right
ascension and declination, which change only slowly, everything that moves
minute to minute is the Earth turning underneath them, and that much can be had
from a clock and a longitude. That is what lets the card redraw itself without
asking the server anything, and it is why the same shortcut lives here: the two
have to place a body in the same spot or they are drawing different skies.
``tests/test_svg_matches_card.py`` runs the JavaScript and checks that they do,
and ``tests/test_bodies.py`` checks this against skyfield's own answer.

The second is that the layout constants below have to match the card's. The
chart is laid out in these units and scaled to fit by the viewBox, so a number
that disagrees moves things relative to each other rather than merely resizing
them. ``tests/test_projection.py`` reads them out of the JavaScript and fails if
they have drifted apart.
"""

import datetime
import math
from typing import NamedTuple

# the drawing is laid out in these units and scaled to fit by the viewBox
SIZE = 400
CENTRE = SIZE / 2
HORIZON_RADIUS = 165

# a circle of sky 90 degrees from overhead is the horizon
HORIZON = 90

# the marker sizes in ``bodies.BODIES`` are areas in square points, as matplotlib
# wanted them; this brings those numbers over to a radius in our units
MARKER_SCALE = 0.048

COMPASS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")

# how far apart to place the rings, in degrees of altitude
RING_STEP = 10

# points to draw along each constellation line, so it curves with the projection
# instead of cutting straight across it
POINTS_PER_LINE = 10

# the Unix epoch, and the start of J2000, as Julian dates
JULIAN_UNIX_EPOCH = 2440587.5
J2000 = 2451545.0
SECONDS_PER_DAY = 86400.0


class Observer(NamedTuple):
    """
    The parts of the rotation that every body in one frame shares.

    Worked out once per frame rather than once per body, since a chart with the
    default constellations turned on places something over a hundred of them.
    """

    sin_latitude: float
    cos_latitude: float
    # local, not Greenwich: the observer's longitude is already in it
    sidereal_time: float


def greenwich_sidereal_time(when: datetime.datetime) -> float:
    """
    Greenwich mean sidereal time, in degrees.

    This is the angle the Earth has turned to, reckoned against the stars rather
    than against the Sun. Treating UTC as UT1 leaves it under a second out, which
    comes to a hundredth of a pixel here.

    The moment has to carry a zone. A naive datetime would be read as the
    machine's own zone, and the machine is routinely somewhere other than the sky
    being drawn -- a Home Assistant container on UTC drawing a garden in Seattle
    would turn the sky by seven hours, or a hundred and five degrees. Rather than
    guess, refuse; ``bodies.Sky.local_time`` hands out aware moments for this.
    """
    if when.tzinfo is None:
        raise ValueError(
            "a moment to draw the sky for has to say what zone it is in; "
            "bodies.Sky.local_time() will attach the configured one"
        )

    julian_day = when.timestamp() / SECONDS_PER_DAY + JULIAN_UNIX_EPOCH
    since_2000 = julian_day - J2000
    centuries = since_2000 / 36525
    degrees = (
        280.46061837
        + 360.98564736629 * since_2000
        + 0.000387933 * centuries**2
        - centuries**3 / 38710000
    )
    # Python's modulo already comes back positive for a negative left-hand side,
    # so this needs none of the folding the JavaScript does
    return degrees % 360


def observer_at(latitude: float, longitude: float, when: datetime.datetime) -> Observer:
    """Pre-compute the parts of the rotation that every body shares."""
    return Observer(
        sin_latitude=math.sin(math.radians(latitude)),
        cos_latitude=math.cos(math.radians(latitude)),
        sidereal_time=greenwich_sidereal_time(when) + longitude,
    )


def alt_az(ra: float, dec: float, observer: Observer) -> tuple[float, float]:
    """
    Turn right ascension and declination into azimuth and altitude.

    Azimuth comes back in degrees east of north and altitude in degrees above the
    horizon, in that order -- which is the order the card returns them in, and the
    opposite of the way its name reads.

    Note that altitude here is degrees up from the horizon, where ``bodies``
    works in degrees down from straight overhead. ``Point.describe`` and
    ``BodyPath.describe`` have already converted by the time anything reaches
    this module.
    """
    hour_angle = math.radians(observer.sidereal_time - ra)
    sin_dec = math.sin(math.radians(dec))
    cos_dec = math.cos(math.radians(dec))
    sin_hour = math.sin(hour_angle)
    cos_hour = math.cos(hour_angle)

    altitude = math.asin(
        sin_dec * observer.sin_latitude + cos_dec * observer.cos_latitude * cos_hour
    )
    azimuth = math.atan2(
        -cos_dec * sin_hour,
        sin_dec * observer.cos_latitude - cos_dec * observer.sin_latitude * cos_hour,
    )
    return math.degrees(azimuth) % 360, math.degrees(altitude)


def radius_for(altitude: float) -> float:
    """
    How far from the middle a given altitude sits.

    Straight overhead is the middle and the horizon is the rim, so this is the
    same whichever way round the chart has been turned.
    """
    return HORIZON_RADIUS * (HORIZON - altitude) / HORIZON


def body_radius(size: float) -> float:
    """
    How big to draw a body, from the marker size in ``bodies.BODIES``.

    Those are areas in square points, so the square root is what makes the Sun
    look like it does rather than swamping the chart.
    """
    return math.sqrt(size) * MARKER_SCALE * HORIZON_RADIUS / 10


def projector(north_up: bool = False, horizontal_flip: bool = False):
    """
    Build a function placing a point of sky on the drawing.

    The chart reads as though you were lying on your back looking up, which puts
    east to the left of north: the way round a sky chart goes, and the opposite
    of a map.
    """
    zero = math.pi / 2 if north_up else -math.pi / 2
    direction = 1 if horizontal_flip else -1

    def project(azimuth: float, altitude: float) -> tuple[float, float]:
        radius = radius_for(altitude)
        angle = zero + direction * math.radians(azimuth)
        # y is subtracted because SVG counts downwards
        return CENTRE + radius * math.cos(angle), CENTRE - radius * math.sin(angle)

    return project


def round_unit(value: float) -> float:
    """
    Round to a tenth of a unit; SVG needs no more and the strings get long.

    Deliberately floor-of-a-half rather than :func:`round`, which would break
    ties to the nearest even number where JavaScript's ``Math.round`` breaks them
    upwards. It almost never matters -- these are the results of trigonometry, so
    landing exactly on a half is vanishingly rare -- but matching the card
    exactly costs nothing here and saves wondering later.
    """
    return math.floor(value * 10 + 0.5) / 10


def number(value: float) -> str:
    """
    Format a coordinate the way JavaScript would, for a compact drawing.

    A whole number loses its ``.0``, which over several thousand star positions
    is worth a good deal of the file.
    """
    rounded = round_unit(value)
    whole = int(rounded)
    return str(whole) if rounded == whole else str(rounded)
