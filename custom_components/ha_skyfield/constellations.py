"""Handle plotting constellations on the sky field."""

import math
import os

import numpy as np

THIS_DIR = os.path.split(__file__)[0]
DATA_FILE = os.path.join(THIS_DIR, "constellations_by_RA_Dec.dat")

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

DEFAULT_CONSTELLATIONS = [*ZODIAC, "Cassiopeia", "Orion", "Pegasus", "UrsaMajor"]


class Constellation:
    """A single constellation."""

    def __init__(self, name, radec_pairs, sky):
        self.name = name
        self._sky = sky
        self._star_xyz, self._lines = _build_stick_figure(radec_pairs)

    def describe(self, obs_time):
        """
        Describe this figure as data, for a client that draws it itself.

        The stars are given in sky coordinates rather than as points on a plot,
        so a client can turn them itself as the night goes on, and the lines are
        given as pairs of indices into that list rather than as repeated
        coordinates, since most stars are shared between two lines or more.

        Stars are so far away that which way they lie does not depend on where
        in its orbit the Earth happens to be, only on which way the observer is
        facing. So the whole figure is placed with a single rotation rather than
        a light-travel-time solution per star, which is enormously cheaper and
        off by under a hundredth of a degree -- a fiftieth of a pixel at the size
        this gets drawn.
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
