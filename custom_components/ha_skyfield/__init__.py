"""
Polar charts of the Sun, Moon, planets and constellations.

This package wears two hats. It is a Home Assistant custom integration, which is
what the directory it lives in is for, and it is also an ordinary Python package
that will draw the same chart as an SVG file for a web page, serve it over HTTP,
or pack it up small enough to send to a watch. The same files do both, so that
there is one drawing to keep right rather than two.

The Home Assistant half needs Home Assistant, and the standalone half must not.
So the integration proper lives in ``integration.py`` and is only pulled in when
there is a Home Assistant to pull it in for; ``python -m ha_skyfield`` and
``import ha_skyfield.svg`` work on a machine that has never heard of it.
"""

from importlib.util import find_spec

# Home Assistant reads ``async_setup`` and ``CONFIG_SCHEMA`` off this module by
# name, so they have to be visible here even though they are defined next door.
# Asking whether Home Assistant is installed, rather than importing and catching
# the failure, keeps a genuine mistake inside integration.py loud instead of
# quietly turning the integration off.
if find_spec("homeassistant") is not None:  # pragma: no cover - needs a HA install
    from .integration import (  # noqa: F401
        CONFIG_SCHEMA,
        DOMAIN,
        async_setup,
    )
