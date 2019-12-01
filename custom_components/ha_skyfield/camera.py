"""
HASS camera component for skyfield.

Maybe a camera is better than a sensor for live updates."""
import logging
from datetime import timedelta
import os
import io

from homeassistant.components.camera import Camera
from homeassistant.util import Throttle
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE

_LOGGER = logging.getLogger(__name__)

DOMAIN = "skyfield"

ICON = "mdi:sun"
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the skyfield platform."""
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)
    tzname = str(hass.config.time_zone)
    configdir = hass.config.config_dir
    tmpdir = "/tmp/skyfield"
    _LOGGER.debug("Setting up skyfield.")
    panel = SkyFieldCam(latitude, longitude, tzname, configdir, tmpdir)

    _LOGGER.debug("Adding skyfield cam")
    add_entities([panel], True)


class SkyFieldCam(Camera):
    """A hass-specific entity."""

    def __init__(self, latitude, longitude, tzname, configdir, tmpdir):
        Camera.__init__(self)
        from . import bodies

        self.sky = bodies.Sky((latitude, longitude), tzname)
        self._loaded = False
        self._configdir = configdir
        self._tmpdir = tmpdir

    @property
    def frame_interval(self):
        # this is how often the image will update in the background. 
        # When the GUI panel is up, it is always updated every 
        # 10 seconds, which is too much. Must figure out how to 
        # reduce...
        return 60

    @property
    def name(self):
        return "SkyField"

    @property
    def brand(self):
        return "SkyField"

    @property
    def model(self):
        return "Sky"

    @property
    def icon(self):
        return ICON

    def camera_image(self):
        """Load image bytes in memory"""
        # don't use throttle because extra calls return Nones
        if not self._loaded:
            _LOGGER.debug("Loading skyfield data")
            self.sky.load(self._tmpdir)
            self._loaded = True
        _LOGGER.debug("Updating skyfield plot")
        buf = io.BytesIO()
        self.sky.plot_sky(buf)
        buf.seek(0)
        return buf.getvalue()
