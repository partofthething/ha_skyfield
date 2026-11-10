"""HASS component for skyfield."""

import logging
import os
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, DEGREE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import Throttle

from .const import DOMAIN as INTEGRATION_DOMAIN
from .const import POSITION_KINDS
from .integration import DATA_SKY

_LOGGER = logging.getLogger(__name__)

DOMAIN = "skyfield"

ICON = "mdi:sun"
MIN_TIME_BETWEEN_UPDATES = timedelta(minutes=1)

# The Sun moves a quarter of a degree a minute, so asking more often than this
# changes nothing a dashboard could show.
POSITION_UPDATE_INTERVAL = timedelta(minutes=1)

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """
    Add an altitude and an azimuth sensor for each body the entry draws.

    Which bodies those are follows the entry's planet list, so the sensors and
    the chart never disagree. Changing the list reloads the entry, which builds
    these again.
    """

    async def _positions():
        sky = hass.data.get(INTEGRATION_DOMAIN, {}).get(DATA_SKY)
        if sky is None:
            raise UpdateFailed("the sky is not set up")
        return await hass.async_add_executor_job(sky.body_positions)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=INTEGRATION_DOMAIN,
        update_method=_positions,
        update_interval=POSITION_UPDATE_INTERVAL,
    )
    await coordinator.async_config_entry_first_refresh()

    sensors = [
        BodyPositionSensor(coordinator, entry, label, kind)
        for label in coordinator.data
        for kind in POSITION_KINDS
    ]

    # A body dropped from the planet list would otherwise stay in the registry
    # as an entity that is unavailable forever.
    wanted = {sensor.unique_id for sensor in sensors}
    registry = er.async_get(hass)
    for stale in er.async_entries_for_config_entry(registry, entry.entry_id):
        if stale.domain == "sensor" and stale.unique_id not in wanted:
            registry.async_remove(stale.entity_id)

    async_add_entities(sensors)


class BodyPositionSensor(CoordinatorEntity, SensorEntity):
    """Where one body is in the observer's sky: its altitude or its azimuth."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = DEGREE
    _attr_suggested_display_precision = 1

    def __init__(self, coordinator, entry, label, kind):
        super().__init__(coordinator)
        self._label = label
        self._kind = kind
        self._attr_translation_key = kind
        self._attr_translation_placeholders = {"body": label}
        self._attr_unique_id = f"{entry.entry_id}_{label.lower()}_{kind}"
        self._attr_device_info = DeviceInfo(
            identifiers={(entry.domain, entry.entry_id)},
            name="HA Skyfield",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self):
        """Degrees above the horizon (negative once set), or clockwise from north."""
        return self.coordinator.data[self._label][self._kind]
