"""
The settings, as the UI offers them.

The form and the YAML schema describe the same sky, and there is nothing to stop
one of them growing an option the other has never heard of -- which shows up as a
setting somebody can no longer reach rather than as anything failing. So they are
compared here, along with the two things the form does that YAML did not have to:
fill itself in from wherever home is, and take an empty picker to mean "all of
them" rather than "none of them".

These need Home Assistant installed; it is in requirements_test.txt.
"""

import unittest
from unittest import mock

try:
    import voluptuous as vol
    from ha_skyfield import config_flow, integration
    from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE
except ImportError:  # pragma: no cover - depends on the install
    config_flow = None

SEATTLE = (47.608, -122.335)


def fake_hass(latitude=SEATTLE[0], longitude=SEATTLE[1], tzname="America/Los_Angeles"):
    """Just enough of Home Assistant to be asked where home is."""
    hass = mock.Mock()
    hass.config.latitude = latitude
    hass.config.longitude = longitude
    hass.config.time_zone = tzname
    return hass


def keys_of(schema):
    """The option names a voluptuous schema accepts."""
    return {str(key) for key in schema.schema}


# what the sky calls each option. Not the same words in one case, which is the
# sort of thing that gets wired up wrong and then silently ignored.
SKY_ARGUMENT = {
    "show_constellations": "show_constellations",
    "show_time": "show_time",
    "show_legend": "show_legend",
    "north_up": "north_up",
    "horizontal_flip": "horizontal_flip",
    "planet_list": "planet_list",
    "constellations_list": "constellation_list",
}


@unittest.skipUnless(config_flow, "the config flow needs Home Assistant installed")
class TestTheFormOffersEverythingThereIs(unittest.TestCase):
    """Whatever can be configured has to be configurable from the UI."""

    def setUp(self):
        self.schema = config_flow.options_schema(
            config_flow.default_options(fake_hass()),
            planets=["Sun", "Mars"],
            constellations=["Orion", "UrsaMajor"],
        )

    def test_it_offers_what_the_yaml_did(self):
        yaml_options = keys_of(integration.CONFIG_SCHEMA.schema[integration.DOMAIN])
        self.assertEqual(keys_of(self.schema), yaml_options)

    def test_nothing_it_offers_is_left_out_of_the_sky(self):
        """A field that reaches nothing is a setting somebody cannot change."""
        self.assertEqual(
            keys_of(self.schema), {*SKY_ARGUMENT, CONF_LATITUDE, CONF_LONGITUDE}
        )

    def test_what_is_picked_is_what_the_sky_is_built_from(self):
        from ha_skyfield import bodies

        settings = self.schema(
            {
                "show_time": False,
                "north_up": True,
                "planet_list": ["Mars"],
                "constellations_list": ["Orion"],
            }
        )
        with mock.patch.object(bodies, "Sky") as sky:
            integration._build_sky(settings, "UTC", ".")

        latlong, tzname = sky.call_args.args
        self.assertEqual(latlong, (settings[CONF_LATITUDE], settings[CONF_LONGITUDE]))
        self.assertEqual(tzname, "UTC")
        for option, argument in SKY_ARGUMENT.items():
            with self.subTest(option=option):
                self.assertEqual(
                    sky.call_args.kwargs[argument],
                    settings[option] if settings[option] != [] else None,
                )


@unittest.skipUnless(config_flow, "the config flow needs Home Assistant installed")
class TestTheFormFillsItselfIn(unittest.TestCase):
    """An empty form is a working sky, so that adding this asks nothing."""

    def test_the_location_starts_at_home(self):
        defaults = config_flow.default_options(fake_hass())
        self.assertEqual((defaults[CONF_LATITUDE], defaults[CONF_LONGITUDE]), SEATTLE)

    def test_submitting_it_untouched_gives_a_whole_configuration(self):
        schema = config_flow.options_schema(
            config_flow.default_options(fake_hass()), ["Sun"], ["Orion"]
        )
        settings = schema({})
        self.assertEqual(settings[CONF_LATITUDE], SEATTLE[0])
        self.assertIs(settings["show_constellations"], True)
        self.assertEqual(settings["planet_list"], [])

    def test_the_defaults_it_offers_build_a_sky(self):
        """
        The end of it: an untouched form, through to the real thing.

        This is where a renamed option or a list the wrong way round shows up,
        and it costs nothing, since building a Sky does not load an ephemeris.
        """
        from ha_skyfield.bodies import Sky

        schema = config_flow.options_schema(
            config_flow.default_options(fake_hass()), ["Sun"], ["Orion"]
        )
        with mock.patch.object(Sky, "load"):
            sky = integration._build_sky(schema({}), "UTC", ".")
        self.assertIsInstance(sky, Sky)

    def test_a_latitude_that_is_not_one_is_refused(self):
        schema = config_flow.options_schema(
            config_flow.default_options(fake_hass()), ["Sun"], ["Orion"]
        )
        with self.assertRaises(vol.Invalid):
            schema({CONF_LATITUDE: 91})


@unittest.skipUnless(config_flow, "the config flow needs Home Assistant installed")
class TestPickingNothing(unittest.TestCase):
    """
    An empty picker means the usual sky, not an empty one.

    Leaving `planet_list` out of YAML has always meant every planet, and a form
    cannot leave a field out, so the empty list has to mean the same thing.
    """

    def test_no_planets_picked_means_all_of_them(self):
        self.assertIsNone(integration._chosen([]))

    def test_the_ones_picked_are_the_ones_used(self):
        self.assertEqual(integration._chosen(["Mars"]), ["Mars"])


@unittest.skipUnless(config_flow, "the config flow needs Home Assistant installed")
class TestTakingOverAYamlConfiguration(unittest.TestCase):
    """
    A configuration that used to be read from a file has to survive the move.

    The import runs once, so getting this wrong quietly loses somebody's
    settings and there is no second chance at it.
    """

    def _imported(self, yaml):
        validated = integration.CONFIG_SCHEMA({integration.DOMAIN: yaml})[
            integration.DOMAIN
        ]
        return config_flow.options_from_yaml(fake_hass(), validated)

    def test_an_empty_block_lands_on_the_defaults(self):
        options = self._imported({})
        self.assertEqual(options, config_flow.default_options(fake_hass()))

    def test_what_was_written_down_is_what_comes_out(self):
        options = self._imported(
            {
                "show_constellations": False,
                "show_time": False,
                "north_up": True,
                "planet_list": ["Mars"],
                "constellations_list": ["Orion"],
                "latitude": 51.5,
                "longitude": -0.13,
            }
        )
        self.assertIs(options["show_constellations"], False)
        self.assertIs(options["north_up"], True)
        self.assertEqual(options["planet_list"], ["Mars"])
        self.assertEqual(options["constellations_list"], ["Orion"])
        self.assertEqual((options["latitude"], options["longitude"]), (51.5, -0.13))
        # not written down, so still the default rather than missing
        self.assertIs(options["show_legend"], True)

    def test_the_imported_options_are_a_form_the_ui_can_show(self):
        """Whatever came out of YAML has to be re-editable afterwards."""
        options = self._imported({"planet_list": ["Mars"], "north_up": True})
        schema = config_flow.options_schema(options, ["Sun", "Mars"], ["Orion"])
        self.assertEqual(schema({}), options)


@unittest.skipUnless(config_flow, "the config flow needs Home Assistant installed")
class TestWhatThereIsToPick(unittest.TestCase):
    """The pickers offer the real lists, not a copy of them written out again."""

    def test_the_planets_are_the_ones_that_get_drawn(self):
        from ha_skyfield.bodies import BODIES

        planets, _constellations = config_flow._read_choices()
        self.assertEqual(planets, [label for label, *_rest in BODIES])

    def test_the_constellations_are_the_ones_in_the_data_file(self):
        from ha_skyfield.constellations import DEFAULT_CONSTELLATIONS

        _planets, constellations = config_flow._read_choices()
        for name in DEFAULT_CONSTELLATIONS:
            with self.subTest(constellation=name):
                self.assertIn(name, constellations)


class TestTheTranslations(unittest.TestCase):
    """
    Nothing here needs Home Assistant; these read what is written down.

    Home Assistant reads translations/en.json at runtime and hassfest reads
    strings.json, so the two are kept identical, and a field with no label of its
    own is shown to somebody as `planet_list`.
    """

    def setUp(self):
        import json
        import pathlib

        import ha_skyfield

        package = pathlib.Path(ha_skyfield.__file__).parent
        self.strings = json.loads((package / "strings.json").read_text())
        self.english = json.loads((package / "translations" / "en.json").read_text())

    def test_the_two_files_say_the_same_thing(self):
        self.assertEqual(self.strings, self.english)

    def test_every_option_has_something_to_call_it(self):
        from ha_skyfield.const import DEFAULT_OPTIONS

        options = {*DEFAULT_OPTIONS, "latitude", "longitude"}
        for section, step in (("config", "user"), ("options", "init")):
            labelled = self.strings[section]["step"][step]["data"]
            with self.subTest(section=section):
                self.assertEqual(set(labelled), options)


if __name__ == "__main__":
    unittest.main()
