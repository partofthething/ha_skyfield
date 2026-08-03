"""Collect data about where celestial bodies are."""

import datetime
import math
from zoneinfo import ZoneInfo

import numpy as np
from skyfield.api import Loader, Topos
from skyfield.framelib import mean_equator_and_equinox_of_date

from . import constellations

EARTH = "earth"
SUN = "sun"
SUN_LABEL = "Sun"

# how precisely to report positions: a thousandth of a degree is
# a three-hundredth of a pixel, so anything beyond this is just payload
DEGREE_PLACES = 3

BODIES = [
    (SUN_LABEL, SUN, "gold", 500),
    ("Mercury", "mercury", "pink", 40),
    ("Venus", "venus", "rosybrown", 60),
    ("Moon", "moon", "lightgrey", 300),
    ("Mars", "mars", "red", 60),
    ("Jupiter", "jupiter barycenter", "chocolate", 100),
    ("Saturn", "saturn barycenter", "khaki", 90),
    ("Uranus", "uranus barycenter", "lightsteelblue", 40),
    ("Neptune", "neptune barycenter", "royalblue", 30),
]


def _rotate(rotation, xyz):
    """Apply a rotation matrix to one x, y, z vector or a whole array of them."""
    return np.einsum("ij...,j...->i...", rotation, xyz)


class Sky:  # pylint: disable=too-many-instance-attributes
    """The Sky and its bodies."""

    def __init__(
        self,
        latlong,
        tzname,
        show_constellations=True,
        show_time=True,
        show_legend=True,
        constellation_list=None,
        planet_list=None,
        north_up=False,
        horizontal_flip=False,
    ):
        lat, long = latlong
        self._lat, self._long = lat, long
        self._latlong = Topos(latitude_degrees=lat, longitude_degrees=long)
        self._timezone = ZoneInfo(tzname)
        self._planets = None
        self._ts = None
        self._location = None
        self._winter_solstice = None
        self._summer_solstice = None
        self._today_sunpath = None
        self._constellations = []
        self._points = []
        self._show_constellations = show_constellations
        self._show_time = show_time
        self._show_legend = show_legend
        self._north_up = north_up
        self._horizontal_flip = horizontal_flip

        if constellation_list is None:
            self._constellation_names = constellations.DEFAULT_CONSTELLATIONS
        else:
            self._constellation_names = constellation_list
        self._planet_list = planet_list

    def load(self, tmpdir="."):
        """Perform long-running init steps."""
        if self._planets is None:
            # Interestingly, if you have multiple GUIs running you can sometimes
            # get the load method being called more than once with the same
            # instance variables, so we put this in a guard.
            self._load_sky_data(tmpdir)
            self._run_initial_computations()

    def _load_sky_data(self, tmpdir):
        """
        Load the primary input data for skyfield.

        This requires a download for the first one, or
        the inclusion of the data files.
        """
        load = Loader(tmpdir)
        self._planets = load("de421.bsp")
        self._ts = load.timescale()

    def _run_initial_computations(self):
        self._location = self._planets[EARTH] + self._latlong
        self._compute_solstice_paths()
        self._load_points()
        if self._show_constellations:
            self._constellations = constellations.build_constellations(
                self, self._constellation_names
            )

    def _load_points(self):
        """Initialize the objects representing the Sun, moon, and planets."""
        # somewhat surprising, sometimes points were getting double-added
        self._points.clear()
        for name, planet_label, color, size in BODIES:
            if self._planet_list is not None and name not in self._planet_list:
                # planet not requested. skip it.
                continue
            self._points.append(
                Point(name, self._planets[planet_label], color, size, self)
            )

    def _compute_solstice_paths(self):
        """Compute solar paths at winter and summer solstices."""
        this_year = self.local_time().year
        self._winter_solstice = BodyPath(
            "winter_solstice",
            self._planets[SUN],
            self._midnight(datetime.date(this_year, 12, 21)),
            self,
            dashed=True,
        )
        self._summer_solstice = BodyPath(
            "summer_solstice",
            self._planets[SUN],
            self._midnight(datetime.date(this_year, 6, 21)),
            self,
            dashed=True,
        )

    def _midnight(self, date):
        """The start of a given day where the observer is standing."""
        return datetime.datetime.combine(date, datetime.time(), tzinfo=self._timezone)

    def local_time(self, when=None):
        """
        The configured location's own idea of a moment in time.

        Asked for nothing, this gives now. Given a moment that carries no zone,
        it takes the configured one to have been meant, and given one that does,
        it moves it to the configured zone.

        Everything here goes through this, because the machine's clock and the
        configured location often disagree: a Home Assistant container commonly
        runs on UTC while the sky it is drawing is somebody's back garden on the
        other side of the world. Reading the machine's wall clock and calling it
        local would turn the sky by the difference between them, and taking
        `today` off a UTC clock would sometimes draw tomorrow's Sun.
        """
        if when is None:
            return datetime.datetime.now(self._timezone)
        if when.tzinfo is None:
            return when.replace(tzinfo=self._timezone)
        return when.astimezone(self._timezone)

    def to_time(self, obs_datetime):
        """
        Convert a moment, or a sequence of them, to a skyfield time.

        Skyfield handles a whole array of times in a single pass, which is much
        cheaper than looping in Python, so sequences are passed through intact.
        """
        if isinstance(obs_datetime, datetime.datetime):
            return self._ts.utc(self.local_time(obs_datetime))
        return self._ts.utc([self.local_time(when) for when in obs_datetime])

    def observer_at(self, obs_time):
        """
        Locate the observer, ready to observe bodies at the given time(s).

        Everything in one frame is seen from the same place at the same time, so
        this only has to be worked out once per frame rather than once per body.
        """
        return self._location.at(obs_time)

    def compute_position(self, body, obs_datetime):
        """Compute azimuth and altitude of a body at a time (or times)."""
        obs_time = self.to_time(obs_datetime)
        return self.observe(self.observer_at(obs_time), body)

    def observe(self, observer, body):
        """
        Compute azimuth and altitude of a body as seen by an observer.

        This deliberately skips skyfield's ``apparent()`` correction, which
        spends most of its time computing how much the Sun and giant planets
        bend the incoming light. That amounts to a couple of arcseconds; a whole
        degree is only about three pixels here, so it is invisible.
        """
        return self.to_altaz(observer.observe(body).xyz.au, observer.t)

    def to_altaz(self, xyz, obs_time):
        """
        Rotate positions given as x, y, z vectors into azimuth and altitude.

        Remap the altitude to be degrees away from straight up
        rather than from the horizon, since this is how
        the plot axes are in theta,r coordinates.
        """
        x, y, z = _rotate(self._latlong.rotation_at(obs_time), xyz)
        azi = np.arctan2(y, x) % (2 * math.pi)
        alt = 90 - np.degrees(np.arctan2(z, np.hypot(x, y)))
        return azi, alt

    def to_radec(self, xyz, obs_time):
        """
        Rotate x, y, z vectors into right ascension and declination of date.

        These are the coordinates to hand to a client that wants to place things
        in the sky itself. They still turn with the seasons, but the Earth's spin
        has been taken out of them, and spin is the one part of this that is
        cheap to work out from nothing but a clock and a longitude.

        Angles come back rounded to the precision a drawing can actually show,
        since this is only ever used to describe the sky to somebody else.
        """
        x, y, z = _rotate(mean_equator_and_equinox_of_date.rotation_at(obs_time), xyz)
        ra = np.degrees(np.arctan2(y, x)) % 360
        dec = np.degrees(np.arctan2(z, np.hypot(x, y)))
        return np.round(ra, DEGREE_PLACES), np.round(dec, DEGREE_PLACES)

    def sky_model(self, when=None):
        """
        Describe the whole sky as plain data, for a client that draws it itself.

        Positions of the Sun, Moon and planets are given as right ascension and
        declination rather than as points on the plot, so that a client can turn
        the sky for itself as the minutes pass without asking again. The Sun's
        daily paths, on the other hand, are already fixed curves for the day, so
        they are given as the altitudes and azimuths they will keep.
        """
        when = self.local_time(when)
        obs_time = self.to_time(when)
        observer = self.observer_at(obs_time)

        return {
            # taken from the converted time rather than the argument, so it says
            # what was actually computed and lands in the configured zone
            "generated": obs_time.astimezone(self._timezone).isoformat(),
            "latitude": self._lat,
            "longitude": self._long,
            "north_up": self._north_up,
            "horizontal_flip": self._horizontal_flip,
            "show_legend": self._show_legend,
            "show_time": self._show_time,
            "bodies": [point.describe(observer) for point in self._points],
            "paths": [
                path.describe()
                for path in (
                    self._winter_solstice,
                    self._summer_solstice,
                    self._sunpath_for(when.date()),
                )
            ],
            "constellations": [
                constellation.describe(obs_time)
                for constellation in self._constellations
            ],
        }

    def _sunpath_for(self, date):
        """
        Get the Sun's path across the sky on a given date.

        The path only changes from one day to the next, so it is worth keeping
        rather than recomputing on every frame.
        """
        if self._today_sunpath is None or self._today_sunpath.date != date:
            self._today_sunpath = BodyPath(
                "today",
                self._planets[SUN],
                # start at midnight to hide discontinuities
                self._midnight(date),
                self,
                dashed=False,
            )
        return self._today_sunpath

    def sun_altitude(self, when=None):
        """
        How high the Sun is above the horizon, in degrees.

        Negative once it has set. This is the one number the sensor entity wants
        out of the whole sky, and it is cheap enough to work out on its own that
        it is not worth drawing a chart to find it.
        """
        _azimuth, zenith_angle = self.compute_position(
            self._planets[SUN], self.local_time(when)
        )
        return float(90 - zenith_angle)


class BodyPath:
    """A line that some Body will travel on on some given day"""

    def __init__(self, name, body, day, sky, dashed=False):
        self.name = name
        self._body = body
        self._day = day
        self._sky = sky
        self.path = None
        self.dashed = dashed

        self._compute_daily_path()

    @property
    def date(self):
        """The date this path was computed for."""
        return self._day.date()

    def _compute_daily_path(self, delta=datetime.timedelta(minutes=20)):
        """Get all possible positions for a given day, in one pass."""
        times = [self._day + delta * interval for interval in range(24 * 3 + 1)]
        self.path = self._sky.compute_position(self._body, times)

    def describe(self):
        """
        Describe this path as data: the fixed curve it traces out over the day.

        A client is left to colour it however suits its theme, so only the name
        and whether it is a dashed line go along with the shape.
        """
        azi, alt = self.path
        return {
            "name": self.name,
            "dashed": self.dashed,
            "azimuth": np.round(np.degrees(azi), DEGREE_PLACES).tolist(),
            "altitude": np.round(90 - alt, DEGREE_PLACES).tolist(),
        }


class Point:
    """A point in the sky like a planet or the sun"""

    def __init__(self, label, body, color, size, sky):
        self.label = label
        self.color = color
        self.size = size
        self._body = body
        self._sky = sky

    def describe(self, observer):
        """
        Describe where this body is, as data.

        The colours are CSS colour names, which is what both the card and the
        rendered SVG want, and which say which planet you are looking at rather
        than merely being pretty.
        """
        ra, dec = self._sky.to_radec(observer.observe(self._body).xyz.au, observer.t)
        return {
            "label": self.label,
            "color": self.color,
            "size": self.size,
            "ra": float(ra),
            "dec": float(dec),
        }
