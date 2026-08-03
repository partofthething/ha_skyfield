"""
Live sky charts for Home Assistant.

Setting up this integration serves two things to the frontend: the sky itself,
as data, and a Lovelace card that knows how to draw it. The card is registered
automatically, so all that is needed in a dashboard is:

    type: custom:skyfield-card

The chart is also served ready-drawn at `/api/ha_skyfield/sky.svg`, for anything
that would rather be handed a picture than draw one, and packed small at
`/api/ha_skyfield/sky.pebble` for a watch. The older camera entity is still
available as `camera: platform: ha_skyfield` and does not need any of this.
"""

import logging
import pathlib
from functools import partial

import voluptuous as vol
from aiohttp import web
from homeassistant.components import frontend
from homeassistant.components.http import HomeAssistantView, StaticPathConfig
from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN
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
SKY_SVG_URL = f"{SKY_URL}.svg"
SKY_PNG_URL = f"{SKY_URL}.png"
SKY_PEBBLE_URL = f"{SKY_URL}.pebble"

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
    hass.http.register_view(SkySvgView(hass, sky))
    hass.http.register_view(SkyPngView(hass, sky))
    hass.http.register_view(SkyPebbleView(hass, sky))
    await _register_card(hass)

    # at info, so that there is something positive to look for in the log when a
    # dashboard says the card does not exist
    _LOGGER.info(
        "Skyfield is serving the sky at %s, drawn at %s and %s, packed at %s, "
        "and the card at %s",
        SKY_URL,
        SKY_SVG_URL,
        SKY_PNG_URL,
        SKY_PEBBLE_URL,
        CARD_URL,
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
    Serve the card and get the frontend to load it.

    The version is tacked on to the URL so that upgrading actually fetches the
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
    url = f"{CARD_URL}?v={integration.version}"

    if await _add_dashboard_resource(hass, url):
        return

    # Dashboards written in YAML keep their own resource list, which cannot be
    # added to from here, so fall back to loading the card on every frontend page.
    frontend.add_extra_js_url(hass, url)
    _LOGGER.warning(
        "Your dashboard resources are managed in YAML, so the card could not be "
        "registered automatically. It is being loaded as an extra module instead, "
        "which occasionally loses a race with the dashboard and is then reported "
        "as 'Custom element doesn't exist: skyfield-card'. To make it reliable, "
        "add this to your lovelace resources: {url: %s, type: module}",
        url,
    )


async def _add_dashboard_resource(hass: HomeAssistant, url: str) -> bool:
    """
    Put the card in the dashboard's resource list. Says whether that worked.

    This is worth the trouble because a dashboard waits for its resources before
    it draws any cards, which it does not do for an extra module URL: a card
    loaded that way can lose the race and be reported as not existing at all,
    however well the file itself is being served.
    """
    lovelace = hass.data.get(LOVELACE_DOMAIN)
    if lovelace is None or lovelace.resource_mode != "storage":
        return False

    resources = lovelace.resources
    if not resources.loaded:
        await resources.async_load()
        resources.loaded = True

    for resource in resources.async_items():
        if resource["url"].partition("?")[0] != CARD_URL:
            continue
        if resource["url"] != url:
            # a different version of the same card: point the entry that is
            # already there at the new one rather than leaving both behind
            await resources.async_update_item(resource["id"], {"url": url})
        return True

    await resources.async_create_item({"res_type": "module", "url": url})
    return True


class _SkyViewBase(HomeAssistantView):
    """
    Something served from the one sky the integration set up.

    Describing the sky means asking skyfield where a hundred-odd things are, so
    it goes to an executor rather than holding up the event loop.
    """

    requires_auth = True

    def __init__(self, hass: HomeAssistant, sky) -> None:
        self._hass = hass
        self._sky = sky

    async def _model(self) -> dict:
        return await self._hass.async_add_executor_job(self._sky.sky_model)


class SkyView(_SkyViewBase):
    """Serves where everything in the sky is, for the card to draw."""

    url = SKY_URL
    name = f"api:{DOMAIN}:sky"

    async def get(self, request):
        """Describe the sky as it is right now."""
        return self.json(await self._model())


class SkySvgView(_SkyViewBase):
    """
    Serves the chart ready-drawn, for anything that will not draw it itself.

    The card does its own drawing and does not come here; this is for a browser
    pointed straight at it, a dashboard picture, or something outside Home
    Assistant altogether.
    """

    url = SKY_SVG_URL
    name = f"api:{DOMAIN}:sky:svg"

    async def get(self, request):
        """Draw the sky as it is right now."""
        from . import svg

        theme = request.query.get("theme", "auto")
        if theme not in svg.THEMES:
            return web.Response(status=400, text=f"no such theme: {theme}\n")

        drawing = svg.render(
            await self._model(), theme=theme, title=request.query.get("title")
        )
        return web.Response(text=drawing, content_type="image/svg+xml")


class SkyPngView(_SkyViewBase):
    """
    Serves the chart as a picture, for anything that will not take an SVG.

    Which turns out to be a good deal of Home Assistant: the camera entity is
    the obvious case, but anything that expects to be able to resize what it is
    given is another.
    """

    url = SKY_PNG_URL
    name = f"api:{DOMAIN}:sky:png"

    async def get(self, request):
        """Paint the sky as it is right now."""
        from . import raster

        theme = request.query.get("theme", "light")
        if theme not in raster.styles.PALETTES:
            return web.Response(status=400, text=f"no such theme: {theme}\n")
        try:
            width = int(request.query.get("width", raster.DEFAULT_WIDTH))
        except ValueError:
            return web.Response(status=400, text="width should be a whole number\n")

        picture = await self._hass.async_add_executor_job(
            partial(
                raster.render,
                await self._model(),
                theme=theme,
                width=width,
                title=request.query.get("title"),
            )
        )
        return web.Response(body=picture, content_type="image/png")


class SkyPebbleView(_SkyViewBase):
    """
    Serves the sky packed small, for a watch face.

    A Pebble reaches this through the phone in its owner's pocket, so it needs a
    long-lived access token in an Authorization header the same as anything else
    talking to Home Assistant from outside.
    """

    url = SKY_PEBBLE_URL
    name = f"api:{DOMAIN}:sky:pebble"

    async def get(self, request):
        """Pack the sky as it is right now."""
        from . import pebble

        return web.Response(
            body=pebble.pack(await self._model()),
            content_type="application/octet-stream",
        )
