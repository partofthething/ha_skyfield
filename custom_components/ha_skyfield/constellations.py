"""Handle plotting constellations on the sky field."""

import os
import math

import numpy as np

THIS_DIR = os.path.split(__file__)[0]
DATA_FILE = os.path.join(THIS_DIR, "constellations_by_RA_Dec.dat")

# how many points to draw along each line, so that it follows
# the curve of the polar projection instead of cutting across it
POINTS_PER_LINE = 10

# altitudes are measured down from straight up, so this is the horizon
HORIZON = 90.0

ZODIAC = [
    "Aries",
    "Taurus",
    "Gemini",
    "Cancer",
    "Leo",
    "Virgo",
    "Libra",
    "Scorpius",
    "Sagittarius",
    "Capricornus",
    "Aquarius",
    "Pisces",
]

DEFAULT_CONSTELLATIONS = ZODIAC + ["Cassiopeia", "Orion", "Pegasus", "UrsaMajor"]


class Constellation(object):
    """A single constellation."""

    def __init__(self, name, radec_pairs, sky):
        self.name = name
        self._sky = sky
        self._star_xyz, self._lines = _build_stick_figure(radec_pairs)

    def draw(self, ax, obs_time):
        """
        Draw on a matplotlib axis.

        Draw a representation of the constellation at a certain time
        projected onto the observation disk.

        This will look a bit strange with our given projection... they'll
        look kind of upside down.

        Stars are so far away that which way they lie does not depend on where
        in its orbit the Earth happens to be, only on which way the observer is
        facing. So the whole figure can be placed with a single rotation instead
        of a light-travel-time solution per star, and the lines can be drawn as
        one path instead of one at a time. Both are enormously cheaper, and the
        rotation is off by under a hundredth of a degree, or a fiftieth of a
        pixel at the size we draw.
        """
        azi, alt = self._sky.to_altaz(self._star_xyz, obs_time)

        above = alt <= HORIZON
        ax.scatter(
            azi[above],
            alt[above],
            s=10,
            alpha=0.1,
            color="black",
            edgecolor="black",
        )

        start, end = self._lines.T
        # skip lines with both ends below the horizon; they are not visible
        visible = above[start] | above[end]
        azi1, alt1 = azi[start[visible]], alt[start[visible]]
        azi2, alt2 = azi[end[visible]], alt[end[visible]]

        # take the short way around, rather than the wrong way across the plot
        azi2 = azi2 - np.round((azi2 - azi1) / (2 * math.pi)) * 2 * math.pi

        ax.plot(
            *_polyline(azi1, azi2, alt1, alt2),
            "-",
            color="k",
            linewidth=1,
            alpha=0.1,
        )

    def describe(self, obs_time):
        """
        Describe this figure as data, for a client that draws it itself.

        The stars are given in sky coordinates rather than as points on a plot,
        so a client can turn them itself as the night goes on, and the lines are
        given as pairs of indices into that list rather than as repeated
        coordinates, since most stars are shared between two lines or more.
        """
        ra, dec = self._sky.to_radec(self._star_xyz, obs_time)
        return {
            "name": self.name,
            "stars": np.transpose([ra, dec]).tolist(),
            "lines": self._lines.tolist(),
        }


def _build_stick_figure(radec_pairs):
    """
    Turn pairs of sky coordinates into stars and the lines joining them.

    Stars are shared between lines, so they get collected up into one list of
    unique positions, expressed as the unit vectors that skyfield works in, plus
    the pairs of indices into that list that make up each line.
    """
    stars = {}
    lines = []
    for point1, point2 in radec_pairs:
        lines.append(
            [stars.setdefault(point, len(stars)) for point in (point1, point2)]
        )

    ra_hours, dec_degrees = np.array(list(stars)).T
    ra = ra_hours * math.pi / 12
    dec = np.radians(dec_degrees)
    star_xyz = np.array(
        [np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)]
    )
    return star_xyz, np.array(lines)


def _polyline(azi1, azi2, alt1, alt2):
    """
    String a set of line segments together into a single path.

    Each segment gets drawn as several points so that it curves along with the
    polar projection, and the segments are separated by gaps, which matplotlib
    understands as a break in the line.
    """
    along = np.linspace(0, 1, POINTS_PER_LINE)
    gap = np.full((len(azi1), 1), np.nan)

    def interpolate(start, stop):
        points = start[:, None] + (stop - start)[:, None] * along
        return np.hstack([points, gap]).ravel()

    return interpolate(azi1, azi2), interpolate(alt1, alt2)


def read_data():
    """
    Read constellation lines.

    Data file can be generated from various places, such as:
    https://github.com/dcf21/constellation-stick-figures
    """

    constellations = {}
    with open(DATA_FILE) as datafile:
        for line in datafile:
            line = line.strip()
            if line.startswith("#") or not line:
                continue

            name, ra1, dec1, ra2, dec2 = line.split()
            constellation_data = constellations.get(name, [])
            constellation_data.append(
                (
                    (float(ra1) / 360 * 24, float(dec1)),
                    (float(ra2) / 360 * 24, float(dec2)),
                )
            )
            constellations[name] = constellation_data
    return constellations


def build_constellations(sky, whitelist=None):
    constellations = []
    data = read_data()
    for name, radec_pairs in data.items():
        if whitelist is None or name in whitelist:
            constellations.append(Constellation(name, radec_pairs, sky))
    return constellations
