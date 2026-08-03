"""The little web server, exercised over a real socket."""

import json
import threading
import unittest
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from ha_skyfield import pebble, server

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"


class TestOptionsFromQuery(unittest.TestCase):
    """Reading a query string, which is the part somebody types by hand."""

    defaults = server.default_options(*SEATTLE, PACIFIC)

    def read(self, query):
        return server.options_from_query(query, self.defaults)

    def test_nothing_asked_for_leaves_everything_alone(self):
        self.assertEqual(self.read({}), self.defaults)

    def test_the_short_spellings_are_the_ones_from_the_command_line(self):
        options = self.read(
            {"lat": ["51.5"], "lon": ["-0.13"], "tz": ["Europe/London"]}
        )
        self.assertEqual(options["latitude"], 51.5)
        self.assertEqual(options["longitude"], -0.13)
        self.assertEqual(options["timezone"], "Europe/London")

    def test_the_long_spellings_work_too(self):
        self.assertEqual(self.read({"latitude": ["51.5"]})["latitude"], 51.5)

    def test_booleans_take_the_usual_words(self):
        for word in ("1", "true", "yes", "on"):
            self.assertIs(self.read({"north_up": [word]})["north_up"], True)
        for word in ("0", "false", "no", "off"):
            self.assertIs(self.read({"north_up": [word]})["north_up"], False)

    def test_lists_are_comma_separated(self):
        self.assertEqual(
            self.read({"constellations": ["Orion, UrsaMajor"]})["constellations"],
            ["Orion", "UrsaMajor"],
        )

    def test_a_misspelt_option_is_refused_rather_than_ignored(self):
        """A chart drawn for silently the wrong place looks entirely convincing."""
        with self.assertRaises(ValueError) as refused:
            self.read({"latitud": ["51.5"]})
        self.assertIn("latitud", str(refused.exception))

    def test_a_cache_buster_is_the_one_thing_ignored(self):
        self.assertEqual(self.read({"t": ["12345"]}), self.defaults)

    def test_something_that_is_not_a_number_is_refused(self):
        with self.assertRaises(ValueError):
            self.read({"lat": ["banana"]})

    def test_something_that_is_not_a_boolean_is_refused(self):
        with self.assertRaises(ValueError):
            self.read({"north_up": ["maybe"]})


class TestServing(unittest.TestCase):
    """A server on a real port, answering real requests."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = server.serve(*SEATTLE, PACIFIC, host="127.0.0.1", port=0)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.httpd.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=10)

    def get(self, path):
        url = f"http://127.0.0.1:{self.port}{path}"
        try:
            with urllib.request.urlopen(url, timeout=60) as answer:
                return answer.status, answer.headers, answer.read()
        except urllib.error.HTTPError as refused:
            return refused.code, refused.headers, refused.read()

    def test_the_chart(self):
        status, headers, body = self.get("/sky.svg")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("image/svg+xml"))
        self.assertEqual(ET.fromstring(body).tag, "{http://www.w3.org/2000/svg}svg")

    def test_the_data(self):
        status, headers, body = self.get("/sky.json")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("application/json"))
        self.assertIn("bodies", json.loads(body))

    def test_the_watch_payload(self):
        status, headers, body = self.get("/sky.pebble")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "application/octet-stream")
        self.assertEqual(len(pebble.unpack(body)["bodies"]), 9)

    def test_a_page_to_look_at_it_on(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        self.assertIn(b"/sky.svg", body)

    def test_the_query_string_moves_the_observer(self):
        _status, _headers, body = self.get(
            "/sky.json?lat=51.5&lon=-0.13&tz=Europe/London"
        )
        model = json.loads(body)
        self.assertAlmostEqual(model["latitude"], 51.5)
        self.assertIn("+01:00", model["generated"])

    def test_the_query_string_changes_the_drawing(self):
        _status, _headers, body = self.get("/sky.svg?theme=dark&title=Hello")
        self.assertIn(b">Hello<", body)

    def test_a_chart_is_allowed_onto_somebody_elses_page(self):
        _status, headers, _body = self.get("/sky.svg")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")

    def test_it_says_how_long_a_chart_stays_good_for(self):
        _status, headers, _body = self.get("/sky.svg")
        self.assertIn("max-age", headers["Cache-Control"])

    def test_nonsense_is_a_bad_request_rather_than_a_traceback(self):
        status, _headers, body = self.get("/sky.svg?north_up=banana")
        self.assertEqual(status, 400)
        self.assertIn(b"north_up", body)

    def test_somewhere_else_is_a_not_found(self):
        self.assertEqual(self.get("/elsewhere")[0], 404)

    def test_the_server_is_still_up_after_all_that(self):
        self.assertEqual(self.get("/sky.svg")[0], 200)


class TestCache(unittest.TestCase):
    """Setting a sky up is the slow part, so it happens once per set of options."""

    def test_the_same_options_reuse_the_same_sky(self):
        cache = SpyCache()
        options = server.default_options(*SEATTLE, PACIFIC)
        options.pop("theme")
        options.pop("title")
        cache.model(options)
        cache.model(options)
        self.assertEqual(cache.built, 1)

    def test_different_options_get_their_own(self):
        cache = SpyCache()
        options = server.default_options(*SEATTLE, PACIFIC)
        options.pop("theme")
        options.pop("title")
        cache.model(options)
        cache.model({**options, "north_up": True})
        self.assertEqual(cache.built, 2)

    def test_the_colours_never_reach_the_sky(self):
        """
        Changing a colour must not rebuild an ephemeris.

        The handler strips them before asking, so this is really a check that the
        list it strips still names all of them.
        """
        options = server.default_options(*SEATTLE, PACIFIC)
        for name in server.DRAWING_OPTIONS:
            self.assertIn(name, options)


class SpyCache(server.SkyCache):
    """A cache that counts how many skies it has had to set up."""

    built = 0

    def _sky(self, options):
        before = len(self._skies)
        sky = super()._sky(options)
        if len(self._skies) != before:
            self.built += 1
        return sky


if __name__ == "__main__":
    unittest.main()
