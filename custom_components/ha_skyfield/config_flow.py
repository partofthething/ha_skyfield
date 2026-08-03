"""
Setting the sky up from the UI.

Everything lives in the entry's options rather than being split between data and
options, so that one schema describes the form the first time and every time
after it, and there is nothing that can only be changed by deleting the
integration and adding it again.

The lists of planets and constellations are the real ones, read from the
ephemeris table and the constellation data file rather than written out again
here, so a picker cannot offer something the chart would then ignore. Reading
them means a file and a heavy import, so it happens in an executor.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.helpers.typing import ConfigType

from .const import (
    CONF_CONSTELLATION_LIST,
    CONF_HORIZONTAL_FLIP,
    CONF_NORTH_UP,
    CONF_PLANET_LIST,
    CONF_SHOW_CONSTELLATIONS,
    CONF_SHOW_LEGEND,
    CONF_SHOW_TIME,
    DEFAULT_OPTIONS,
    DOMAIN,
)

TITLE = "Sky chart"


def default_options(hass: HomeAssistant) -> dict[str, Any]:
    """
    The settings to start from: the defaults, at home.

    Also what fills in anything an older entry does not carry, so that adding an
    option here does not need a migration.
    """
    return {
        CONF_LATITUDE: hass.config.latitude,
        CONF_LONGITUDE: hass.config.longitude,
        **DEFAULT_OPTIONS,
    }


def options_from_yaml(hass: HomeAssistant, conf: ConfigType) -> dict[str, Any]:
    """
    Turn a validated ``ha_skyfield:`` block into an entry's options.

    Anything the block leaves out keeps its default, and the lists come through
    as lists either way: YAML says "all of them" by omitting the option and the
    UI says it with an empty picker.
    """
    options = default_options(hass)
    options.update(
        {
            key: value
            for key, value in conf.items()
            if key in options and value is not None
        }
    )
    return options


def options_schema(
    defaults: dict[str, Any],
    planets: list[str],
    constellations: list[str],
) -> vol.Schema:
    """The form, filled in with whatever the settings are now."""
    return vol.Schema(
        {
            vol.Required(CONF_LATITUDE, default=defaults[CONF_LATITUDE]): _degrees(90),
            vol.Required(CONF_LONGITUDE, default=defaults[CONF_LONGITUDE]): _degrees(
                180
            ),
            vol.Required(
                CONF_SHOW_CONSTELLATIONS, default=defaults[CONF_SHOW_CONSTELLATIONS]
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SHOW_TIME, default=defaults[CONF_SHOW_TIME]
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_SHOW_LEGEND, default=defaults[CONF_SHOW_LEGEND]
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_NORTH_UP, default=defaults[CONF_NORTH_UP]
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_HORIZONTAL_FLIP, default=defaults[CONF_HORIZONTAL_FLIP]
            ): selector.BooleanSelector(),
            vol.Required(
                CONF_PLANET_LIST, default=defaults[CONF_PLANET_LIST]
            ): _pick_from(planets),
            vol.Required(
                CONF_CONSTELLATION_LIST, default=defaults[CONF_CONSTELLATION_LIST]
            ): _pick_from(constellations),
        }
    )


def _degrees(limit: float) -> selector.NumberSelector:
    """A latitude or longitude, typed in rather than dragged on a slider."""
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=-limit,
            max=limit,
            step="any",
            mode=selector.NumberSelectorMode.BOX,
        )
    )


def _pick_from(options: list[str]) -> selector.SelectSelector:
    """Any number of the given names, or none of them, meaning all of them."""
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options,
            multiple=True,
            mode=selector.SelectSelectorMode.DROPDOWN,
            sort=False,
        )
    )


def _read_choices() -> tuple[list[str], list[str]]:
    """What there is to choose from. Reads a file and imports skyfield."""
    from . import bodies, constellations

    return (
        [label for label, *_rest in bodies.BODIES],
        sorted(constellations.read_data()),
    )


class SkyfieldConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add the sky chart from Settings, or take over a YAML configuration."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the settings. Only one sky, so no unique ID to set."""
        if user_input is not None:
            return self.async_create_entry(title=TITLE, data={}, options=user_input)

        planets, constellations = await self.hass.async_add_executor_job(_read_choices)
        return self.async_show_form(
            step_id="user",
            data_schema=options_schema(
                default_options(self.hass), planets, constellations
            ),
        )

    async def async_step_import(self, import_data: ConfigType) -> ConfigFlowResult:
        """
        Take over an ``ha_skyfield:`` block from configuration.yaml.

        The manifest allows a single entry, so a second run of this aborts by
        itself and the YAML is read once, not on every restart.
        """
        return self.async_create_entry(
            title=TITLE,
            data={},
            options=options_from_yaml(self.hass, import_data),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Offer the same settings again, to change."""
        return SkyfieldOptionsFlow()


class SkyfieldOptionsFlow(OptionsFlow):
    """Change the settings of a sky that is already set up."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the settings as they are, and save whatever comes back."""
        if user_input is not None:
            # saving the options reloads the entry, which redraws the sky with
            # them; see the update listener in integration.py
            return self.async_create_entry(data=user_input)

        planets, constellations = await self.hass.async_add_executor_job(_read_choices)
        return self.async_show_form(
            step_id="init",
            data_schema=options_schema(
                {**default_options(self.hass), **self.config_entry.options},
                planets,
                constellations,
            ),
        )
