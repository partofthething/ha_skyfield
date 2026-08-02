"""
Live sky charts for Home Assistant.

Setting up this integration serves two things to the frontend: the sky itself,
as data, and a Lovelace card that knows how to draw it. The card is registered
automatically, so all that is needed in a dashboard is:

    type: custom:skyfield-card

The older matplotlib camera is still available as `camera: platform: ha_skyfield`
and does not need any of this.
"""

import logging
import pathlib

import voluptuous as vol
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

_LOGGER = logging.getLogger(__name__)

DOMAIN = "ha_skyfield"

CONF_SHOW_TIME = "show_time"
CONF_SHOW_LEGEND = "show_legend"
CONF_SHOW_CONSTELLATIONS = "show_constellations"
CONF_PLANET_LIST = "planet_list"
CONF_CONSTELLATION_LIST = "constellations_list"
CONF_NORTH_UP = "north_up"
CONF_HORIZONTAL_FLIP = "horizontal_flip"

CARD_FILENAME = "skyfield-card.js"
CARD_PATH = pathlib.Path(__file__).parent / "frontend" / CARD_FILENAME
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"
SKY_URL = f"/api/{DOMAIN}/sky"

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_LATITUDE): cv.latitude,
                vol.Optional(CONF_LONGITUDE): cv.longitude,
                vol.Optional(CONF_SHOW_CONSTELLATIONS, default=True): cv.boolean,
                vol.Optional(CONF_SHOW_TIME, default=True): cv.boolean,
                vol.Optional(CONF_SHOW_LEGEND, default=True): cv.boolean,
                vol.Optional(CONF_CONSTELLATION_LIST): cv.ensure_list,
                vol.Optional(CONF_PLANET_LIST): cv.ensure_list,
                vol.Optional(CONF_NORTH_UP, default=False): cv.boolean,
                vol.Optional(CONF_HORIZONTAL_FLIP, default=False): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the sky data endpoint and register the card that draws it."""
    conf = config.get(DOMAIN)
    if conf is None:
        # Nothing addressed to us by name, so something else pulled us in: the
        # camera or sensor platform, most likely. Serve the card anyway, on
        # default settings, rather than leave somebody who adds it to a dashboard
        # staring at "no such card exists" with nothing to say why.
        conf = CONFIG_SCHEMA({DOMAIN: {}})[DOMAIN]

    sky = _build_sky(hass, conf)
    # loading pulls in an ephemeris, downloading it the first time, so it cannot
    # happen on the event loop
    await hass.async_add_executor_job(sky.load, hass.config.path(DOMAIN))

    hass.data[DOMAIN] = sky
    hass.http.register_view(SkyView(hass, sky))
    await _register_card(hass)

    # at info, so that there is something positive to look for in the log when a
    # dashboard says the card does not exist
    _LOGGER.info(
        "Skyfield is serving the sky at %s and the card at %s", SKY_URL, CARD_URL
    )
    return True


def _build_sky(hass: HomeAssistant, conf: ConfigType):
    """Build the Sky described by the configuration."""
    from .bodies import Sky

    return Sky(
        (
            conf.get(CONF_LATITUDE, hass.config.latitude),
            conf.get(CONF_LONGITUDE, hass.config.longitude),
        ),
        str(hass.config.time_zone),
        show_constellations=conf[CONF_SHOW_CONSTELLATIONS],
        show_time=conf[CONF_SHOW_TIME],
        show_legend=conf[CONF_SHOW_LEGEND],
        constellation_list=conf.get(CONF_CONSTELLATION_LIST),
        planet_list=conf.get(CONF_PLANET_LIST),
        north_up=conf[CONF_NORTH_UP],
        horizontal_flip=conf[CONF_HORIZONTAL_FLIP],
    )


async def _register_card(hass: HomeAssistant) -> None:
    """
    Serve the card and tell the frontend to load it.

    Registering the URL as an extra module saves everyone a trip to the Lovelace
    resources page, and works the same whether dashboards are stored in the UI or
    written in YAML. The version is tacked on so that upgrading actually gets the
    new card rather than whatever the browser cached last time.
    """
    # Home Assistant will happily register a route to a file that is not there
    # and then answer 404 when the browser asks for it, which shows up in a
    # dashboard as the card not existing and says nothing about why. So check.
    if not await hass.async_add_executor_job(CARD_PATH.is_file):
        _LOGGER.error(
            "Cannot serve the Lovelace card: %s is missing. The frontend "
            "directory has to be installed next to the Python files, so check "
            "that whatever copied this integration into place brought it along. "
            "The camera platform works without it.",
            CARD_PATH,
        )
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(CARD_PATH), True)]
    )

    integration = await async_get_integration(hass, DOMAIN)
    frontend.add_extra_js_url(hass, f"{CARD_URL}?v={integration.version}")


class SkyView(HomeAssistantView):
    """Serves where everything in the sky is, for the card to draw."""

    url = SKY_URL
    name = f"api:{DOMAIN}:sky"
    requires_auth = True

    def __init__(self, hass: HomeAssistant, sky) -> None:
        self._hass = hass
        self._sky = sky

    async def get(self, request):
        """Describe the sky as it is right now."""
        model = await self._hass.async_add_executor_job(self._sky.sky_model)
        return self.json(model)
