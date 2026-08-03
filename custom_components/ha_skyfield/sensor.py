"""HASS component for skyfield."""

import logging
import os
from datetime import timedelta

from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.helpers.entity import Entity
from homeassistant.util import Throttle

_LOGGER = logging.getLogger(__name__)

DOMAIN = "skyfield"

ICON = "mdi:sun"
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)

# written into the configuration's www/, which Home Assistant serves at /local/.
# A picture rather than an SVG, since this ends up in an entity_picture and the
# frontend is happier with one.
IMAGE_FILENAME = "sun.png"


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the skyfield platform."""
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)
    tzname = str(hass.config.time_zone)
    configdir = hass.config.config_dir
    tmpdir = "/tmp/skyfield"
    _LOGGER.info("Setting up skyfield.")
    panel = SkyField(latitude, longitude, tzname, configdir, tmpdir)

    _LOGGER.info("Adding sunpanel entity")
    add_entities([panel], True)
    _LOGGER.info("Sunpanel init done")


class SkyField(Entity):
    """A hass-specific entity."""

    def __init__(self, latitude, longitude, tzname, configdir, tmpdir):
        from . import bodies

        self.sky = bodies.Sky((latitude, longitude), tzname)
        self._loaded = False
        self._configdir = configdir
        self._tmpdir = tmpdir
        self._sun_altitude = None

    @property
    def name(self):
        return "Skyfield"

    @property
    def icon(self):
        return ICON

    @property
    def state(self):
        """How high the Sun is above the horizon, in degrees."""
        return self._sun_altitude

    @property
    def entity_picture(self):
        """Where the chart written by :meth:`update` can be fetched from."""
        return f"/local/{IMAGE_FILENAME}"

    @Throttle(MIN_TIME_BETWEEN_UPDATES)
    def update(self):
        """Work out where the Sun is, and redraw the chart beside it."""
        if not self._loaded:
            _LOGGER.debug("Loading skyfield data")
            self.sky.load(self._tmpdir)
            self._loaded = True
        _LOGGER.debug("Drawing the skyfield chart")

        from . import raster

        self._sun_altitude = self.sky.sun_altitude()

        # www/ is what Home Assistant serves at /local/, and it is not
        # necessarily there on a fresh installation
        www = os.path.join(self._configdir, "www")
        os.makedirs(www, exist_ok=True)
        with open(os.path.join(www, IMAGE_FILENAME), "wb") as chart:
            chart.write(raster.render(self.sky.sky_model()))
