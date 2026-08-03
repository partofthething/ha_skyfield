"""
Everything the integration can be told, named in one place.

This module is deliberately empty of imports. The config flow, the integration
proper and the camera platform all need these names, and the config flow in
particular is imported on the event loop the moment somebody opens the "add
integration" dialog, so it must not be the thing that drags skyfield and numpy
in with it.
"""

DOMAIN = "ha_skyfield"

CONF_SHOW_TIME = "show_time"
CONF_SHOW_LEGEND = "show_legend"
CONF_SHOW_CONSTELLATIONS = "show_constellations"
CONF_PLANET_LIST = "planet_list"
# spelled with the s where it has always been spelled, since people have this
# in their configuration.yaml
CONF_CONSTELLATION_LIST = "constellations_list"
# could detect north to be up if the location is in the southern hemisphere,
# but for now it is just an option
CONF_NORTH_UP = "north_up"
CONF_HORIZONTAL_FLIP = "horizontal_flip"

# What the integration does with no opinion expressed. The location is not here
# because its default is wherever Home Assistant has been told home is.
#
# An empty list means "everything", not "nothing": that is what leaving the
# option out of YAML has always meant, and a form full of empty pickers is a
# much friendlier way to say "the usual" than one that has to be filled in
# before anything appears in the sky.
DEFAULT_OPTIONS = {
    CONF_SHOW_CONSTELLATIONS: True,
    CONF_SHOW_TIME: True,
    CONF_SHOW_LEGEND: True,
    CONF_NORTH_UP: False,
    CONF_HORIZONTAL_FLIP: False,
    CONF_PLANET_LIST: [],
    CONF_CONSTELLATION_LIST: [],
}
