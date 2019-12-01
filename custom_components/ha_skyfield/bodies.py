"""Collect data about where celestial bodies are."""
import datetime
import math

from pytz import timezone
from skyfield.api import Loader
from skyfield.api import Topos

from . import plots

EARTH = "earth"
MOON = "moon"
SUN = "sun"
MARS = "mars"
JUPITER = "jupiter barycenter"
SATURN = "saturn barycenter"
VENUS = "venus"


class Sky:  # pylint: disable=too-many-instance-attributes
    """The Sky and its bodies."""

    def __init__(self, latlong, tzname):
        lat, long = latlong
        self._latlong = Topos(latitude_degrees=lat, longitude_degrees=long)
        self._timezone = timezone(tzname)
        self._planets = None
        self._ts = None
        self._location = None
        self._winter_data = None
        self._summer_data = None
        self.sun_position = None

    def load(self, tmpdir="."):
        """Perform long-running init steps."""
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

    def _compute_solstice_paths(self):
        """Compute solar paths at winter and summer solstices."""

        # interestingly, these cached paths tend to disappear
        # with time in a homeassistant run.
        today = datetime.datetime.today()
        winter = datetime.datetime(today.year, 12, 21)
        summer = datetime.datetime(today.year, 6, 21)
        self._winter_data = self._compute_daily_path(self._planets[SUN], winter)
        self._summer_data = self._compute_daily_path(self._planets[SUN], summer)

    def _compute_position(self, body, obs_datetime):
        """Compute azimuth and altitude of a body at a time."""
        obs_time = self._ts.utc(self._timezone.localize(obs_datetime))
        astrometric = self._location.at(obs_time).observe(body)
        alt, azi, _d = astrometric.apparent().altaz()
        alt = 90 - alt.radians * 180 / math.pi
        azi = azi.radians
        return azi, alt

    def _compute_daily_path(self, body, day, delta=datetime.timedelta(minutes=20)):
        """Get all possible positions for a given day."""
        data = []
        for interval in range(24 * 3 + 1):
            now = day + delta * interval
            azi, alt = self._compute_position(body, now)
            data.append((azi, alt))
        return list(zip(*data))

    def plot_sky(self, output=None, when=None):
        """Try sun plot with skyfield lib instead."""
        if when is None:
            when = datetime.datetime.now()
        self.sun_position = self._compute_position(self._planets[SUN], when)
        points = [self.sun_position]
        for body in [MOON, VENUS, MARS, JUPITER, SATURN]:
            points.append(self._compute_position(self._planets[body], when))

        # data for lines
        today = datetime.datetime.today()
        today_sunpath = self._compute_daily_path(self._planets[SUN], today)

        plots.plot_sky(
            today_sunpath, self._winter_data, self._summer_data, points, output, str(when)
        )
