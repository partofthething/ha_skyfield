"""
HASS camera component for skyfield.

Maybe a camera is better than a sensor for live updates.

This serves a picture of the chart. It used to be drawn by matplotlib, which was
a heavy thing to make every installation build for one image; it is now painted
by :mod:`.raster` from the same description of the chart the card draws, using
Pillow, which Home Assistant installs anyway.

The picture is a raster one because a camera entity has to be. Serving the SVG
directly and saying so in ``content_type`` looks as though it ought to work and
does not: the dashboard will not show it, and the snapshot button hands back the
bytes under a .jpg name whatever they are. ``image_type: svg`` is still there
for anyone fetching from the entity themselves, but it is not the default.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.camera import Camera
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.helpers.config_validation import PLATFORM_SCHEMA

_LOGGER = logging.getLogger(__name__)

DOMAIN = "skyfield"

CONF_SHOW_TIME = "show_time"
CONF_SHOW_LEGEND = "show_legend"
CONF_SHOW_CONSTELLATIONS = "show_constellations"
CONF_PLANET_LIST = "planet_list"
CONF_CONSTELLATION_LIST = "constellations_list"
# could detect north to be up if location is in souther hemisphere
# but for no we just make it an option
CONF_NORTH_UP = "north_up"
CONF_HORIZONTAL_FLIP = "horizontal_flip"
CONF_IMAGE_TYPE = "image_type"
CONF_THEME = "theme"
CONF_WIDTH = "width"

ICON = "mdi:sun"
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)

CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "svg": "image/svg+xml",
}

# a picture is painted once and cannot ask the person looking at it what they
# prefer, so unlike the card it has to be told
THEMES = ("light", "dark")

DEFAULT_IMAGE_TYPE = "png"
DEFAULT_THEME = "light"
DEFAULT_WIDTH = 800

# Validation of the user's configuration
PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Optional(CONF_SHOW_CONSTELLATIONS, default=False): cv.boolean,
        vol.Optional(CONF_SHOW_TIME, default=True): cv.boolean,
        vol.Optional(CONF_SHOW_LEGEND, default=True): cv.boolean,
        vol.Optional(CONF_CONSTELLATION_LIST): cv.ensure_list,
        vol.Optional(CONF_PLANET_LIST): cv.ensure_list,
        vol.Optional(CONF_NORTH_UP): cv.boolean,
        vol.Optional(CONF_HORIZONTAL_FLIP): cv.boolean,
        vol.Optional(CONF_IMAGE_TYPE, default=DEFAULT_IMAGE_TYPE): vol.In(
            sorted(CONTENT_TYPES)
        ),
        vol.Optional(CONF_THEME, default=DEFAULT_THEME): vol.In(THEMES),
        vol.Optional(CONF_WIDTH, default=DEFAULT_WIDTH): vol.All(
            vol.Coerce(int), vol.Range(min=100, max=4000)
        ),
    }
)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the skyfield platform."""
    latitude = config.get(CONF_LATITUDE, hass.config.latitude)
    longitude = config.get(CONF_LONGITUDE, hass.config.longitude)
    tzname = str(hass.config.time_zone)
    show_constellations = config.get(CONF_SHOW_CONSTELLATIONS)
    show_time = config.get(CONF_SHOW_TIME)
    show_legend = config.get(CONF_SHOW_LEGEND)
    constellation_list = config.get(CONF_CONSTELLATION_LIST)
    planet_list = config.get(CONF_PLANET_LIST)
    north_up = config.get(CONF_NORTH_UP)
    horizontal_flip = config.get(CONF_HORIZONTAL_FLIP)
    image_type = config.get(CONF_IMAGE_TYPE)
    theme = config.get(CONF_THEME)
    width = config.get(CONF_WIDTH)
    configdir = hass.config.config_dir
    tmpdir = "/tmp/skyfield"
    _LOGGER.debug("Setting up skyfield.")
    panel = SkyFieldCam(
        latitude,
        longitude,
        tzname,
        configdir,
        tmpdir,
        show_constellations,
        show_time,
        show_legend,
        constellation_list,
        planet_list,
        north_up,
        horizontal_flip,
        image_type,
        theme,
        width,
    )

    _LOGGER.debug("Adding skyfield cam")
    add_entities([panel], True)


class SkyFieldCam(Camera):
    """A hass-specific entity."""

    def __init__(
        self,
        latitude,
        longitude,
        tzname,
        configdir,
        tmpdir,
        show_constellations,
        show_time,
        show_legend,
        constellations,
        planets,
        north_up,
        horizontal_flip,
        image_type=DEFAULT_IMAGE_TYPE,
        theme=DEFAULT_THEME,
        width=DEFAULT_WIDTH,
    ):
        Camera.__init__(self)
        from . import bodies

        self.sky = bodies.Sky(
            (latitude, longitude),
            tzname,
            show_constellations,
            show_time,
            show_legend,
            constellations,
            planets,
            north_up,
            horizontal_flip,
        )
        self._loaded = False
        self._configdir = configdir
        self._tmpdir = tmpdir
        self._image_type = (image_type or DEFAULT_IMAGE_TYPE).lower()
        self._theme = theme or DEFAULT_THEME
        self._width = width or DEFAULT_WIDTH

    @property
    def content_type(self):
        """
        What the picture is.

        Overridden as a property rather than set as an attribute so that it wins
        however the Camera base class happens to declare it.
        """
        return CONTENT_TYPES[self._image_type]

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

    def camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """
        Draw the sky as it is now.

        A requested width is honoured where it can be -- the chart is drawn from
        scratch, so it is drawn at that size rather than resized afterwards --
        and the height follows from it, since the chart has a shape of its own.
        """
        # don't use throttle because extra calls return Nones
        if not self._loaded:
            _LOGGER.debug("Loading skyfield data")
            self.sky.load(self._tmpdir)
            self._loaded = True
        _LOGGER.debug("Drawing the skyfield chart")

        model = self.sky.sky_model()
        if self._image_type == "svg":
            from . import svg

            return svg.render(model).encode()

        from . import raster

        return raster.render(
            model,
            width=width or self._width,
            theme=self._theme,
            image_format=self._image_type,
        )
