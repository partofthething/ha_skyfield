"""Collect data about where celestial bodies are."""
import datetime
import math

from pytz import timezone
from skyfield.api import Loader
from skyfield.api import Topos

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from . import constellations

# use non-interactive backend to keep multiple instances on
# different threads from interacting
matplotlib.use("agg")

EARTH = "earth"
SUN = "sun"
SUN_LABEL = "Sun"

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
        image_type="png",
    ):
        lat, long = latlong
        self._latlong = Topos(latitude_degrees=lat, longitude_degrees=long)
        self._timezone = timezone(tzname)
        self._planets = None
        self._ts = None
        self._location = None
        self._winter_solstice = None
        self._summer_solstice = None
        self._today_sunpath = None
        self.sun_position = None
        self._constellations = []
        self._points = []
        self._show_constellations = show_constellations
        self._show_time = show_time
        self._show_legend = show_legend
        self._north_up = north_up
        self._horizontal_flip = horizontal_flip
        self._image_type = image_type

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
        today = datetime.datetime.today()
        self._winter_solstice = BodyPath(
            self._planets[SUN],
            datetime.datetime(today.year, 12, 21),
            self,
            fmt="--",
            color="blue",
            linewidth=1,
            alpha=0.8,
        )
        self._summer_solstice = BodyPath(
            self._planets[SUN],
            datetime.datetime(today.year, 6, 21),
            self,
            fmt="--",
            color="green",
            linewidth=1,
            alpha=0.8,
        )

    @property
    def get_image_type(self):
        """Return the image type attribute."""
        return self._image_type

    def to_time(self, obs_datetime):
        """
        Convert a local datetime, or a sequence of them, to a skyfield time.

        Skyfield handles a whole array of times in a single pass, which is much
        cheaper than looping in Python, so sequences are passed through intact.
        """
        if isinstance(obs_datetime, datetime.datetime):
            return self._ts.utc(self._timezone.localize(obs_datetime))
        return self._ts.utc([self._timezone.localize(when) for when in obs_datetime])

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
        rotation = self._latlong.rotation_at(obs_time)
        x, y, z = np.einsum("ij...,j...->i...", rotation, xyz)
        azi = np.arctan2(y, x) % (2 * math.pi)
        alt = 90 - np.degrees(np.arctan2(z, np.hypot(x, y)))
        return azi, alt

    def plot_sky(self, output=None, when=None):
        """
        Make a figure with the sky and various planets/sun/moon.

        This is a r, theta plot where r goes from 0 to 90 from the center
        and theta goes all the way around radially.

        r represents the altitude
        theta is the azimuth.

        Matplotlib takes these in (theta, r) coordinate pairs so it's (azimuth, altitude) for us.
        """
        if when is None:
            when = datetime.datetime.now()

        visible = [np.linspace(0, 2 * np.pi, 200), [90.0 for _i in range(200)]]

        # pylint: disable=invalid-name
        fig, ax = plt.subplots(
            1, 1, figsize=(6, 6.2), subplot_kw={"projection": "polar"}
        )
        ax.set_axisbelow(True)
        ax.set_theta_direction(1 if self._horizontal_flip else -1)
        ax.plot(*visible, "-", color="k", linewidth=3, alpha=1.0)  # border

        self._draw_objects(ax, when)

        if self._show_time:
            ax.annotate(
                str(when),
                xy=(0.09, 0.07),
                xycoords="figure fraction",
                horizontalalignment="left",
                verticalalignment="top",
                fontsize=8,
            )

        if self._show_legend:
            fig.legend(
                loc="lower right",
                bbox_transform=fig.transFigure,
                ncol=3,
                markerscale=0.6,
                columnspacing=1,
                mode=None,
                handletextpad=0.05,
            )

        ax.set_theta_zero_location("N" if self._north_up else "S", offset=0)
        ax.set_rmax(90)
        ax.set_rgrids(
            np.linspace(0, 90, 10), [f"{int(f)}˚" for f in np.linspace(90, 0, 10)]
        )
        ax.set_thetagrids(
            np.linspace(0, 360.0, 9), ["N", "NE", "E", "SE", "S", "SW", "W", "NW", "N"]
        )
        fig.tight_layout()

        if output is None:
            plt.show()
        else:
            # filename string or file-like object/buffer
            fig.savefig(output, format=self._image_type)
        plt.close()

    def _draw_objects(self, ax, when):
        """Add all celestial bodies to the plots"""
        obs_time = self.to_time(when)
        observer = self.observer_at(obs_time)

        for sunpath in [
            self._winter_solstice,
            self._summer_solstice,
            self._sunpath_for(when.date()),
        ]:
            sunpath.draw(ax)

        for point in self._points:
            position = point.draw(ax, observer)
            if point.label == SUN_LABEL:
                self.sun_position = position

        for constellation in self._constellations:
            constellation.draw(ax, obs_time)

    def _sunpath_for(self, date):
        """
        Get the Sun's path across the sky on a given date.

        The path only changes from one day to the next, so it is worth keeping
        rather than recomputing on every frame.
        """
        if self._today_sunpath is None or self._today_sunpath.date != date:
            self._today_sunpath = BodyPath(
                self._planets[SUN],
                # use today's midnight to hide discontinuities
                datetime.datetime.combine(date, datetime.time()),
                self,
                "-",
                color="k",
                linewidth=1,
                alpha=0.8,
            )
        return self._today_sunpath


class BodyPath(object):
    """A line that some Body will travel on on some given day"""

    def __init__(self, body, day, sky, fmt, color, linewidth=1, alpha=0.8):
        self._body = body
        self._day = day
        self._sky = sky
        self.path = None
        self.fmt = fmt
        self.color = color
        self.linewidth = linewidth
        self.alpha = alpha

        self._compute_daily_path()

    @property
    def date(self):
        """The date this path was computed for."""
        return self._day.date()

    def _compute_daily_path(self, delta=datetime.timedelta(minutes=20)):
        """Get all possible positions for a given day, in one pass."""
        times = [self._day + delta * interval for interval in range(24 * 3 + 1)]
        self.path = self._sky.compute_position(self._body, times)

    def draw(self, ax):
        """Draw this path on a matplotlib axis"""
        ax.plot(
            *self.path,
            self.fmt,
            color=self.color,
            linewidth=self.linewidth,
            alpha=self.alpha,
        )


class Point(object):
    """A point in the sky like a planet or the sun"""

    def __init__(self, label, body, color, size, sky):
        self.label = label
        self._body = body
        self._size = size
        self._color = color
        self._sky = sky

    def draw(self, ax, observer):
        """Draw this body as seen by an observer, and report where it is."""
        azi, alt = self._sky.observe(observer, self._body)
        ax.scatter(
            azi,
            alt,
            s=self._size,
            label=self.label,
            alpha=1.0,
            color=self._color,
            edgecolor="black",
        )
        return azi, alt
