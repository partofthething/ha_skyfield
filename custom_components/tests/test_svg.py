"""The drawing itself: valid, complete, and the same every time."""

import datetime
import re
import unittest
import xml.etree.ElementTree as ET
from zoneinfo import ZoneInfo

from ha_skyfield import bodies, projection, svg

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"
SVG = "{http://www.w3.org/2000/svg}"

# anything that got as far as the drawing without being a number
NOT_A_NUMBER = re.compile(r"\b(nan|NaN|inf|Infinity|None|undefined)\b")


class TestRendering(unittest.TestCase):
    """One sky, drawn."""

    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        cls.sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        cls.sky.load()
        cls.model = cls.sky.sky_model(cls.when)
        cls.drawing = svg.render(cls.model)
        cls.root = ET.fromstring(cls.drawing)

    def find(self, css_class, tag="*"):
        return [
            element
            for element in self.root.iter()
            if element.get("class") == css_class
            and (tag == "*" or element.tag == f"{SVG}{tag}")
        ]

    def test_is_well_formed_svg(self):
        self.assertEqual(self.root.tag, f"{SVG}svg")

    def test_says_what_it_is(self):
        """A chart nobody can see should still say what it shows."""
        self.assertEqual(self.root.get("role"), "img")
        self.assertTrue(self.root.get("aria-label"))

    def test_nothing_failed_to_be_a_number(self):
        found = NOT_A_NUMBER.search(self.drawing)
        self.assertIsNone(
            found, f"{found.group(0) if found else ''} reached the drawing"
        )

    def test_one_circle_per_body(self):
        self.assertEqual(len(self.find("body")), len(self.model["bodies"]))

    def test_bodies_are_named_for_a_reader_who_cannot_see_color(self):
        titles = [circle.find(f"{SVG}title").text for circle in self.find("body")]
        self.assertEqual(titles, [body["label"] for body in self.model["bodies"]])

    def test_a_ring_every_ten_degrees_and_a_spoke_every_compass_point(self):
        grid = self.find("grid")[0]
        rings = grid.findall(f"{SVG}circle")
        spokes = grid.findall(f"{SVG}line")
        self.assertEqual(len(rings), projection.HORIZON // projection.RING_STEP)
        self.assertEqual(len(spokes), len(projection.COMPASS))

    def test_a_path_for_each_of_the_suns_curves(self):
        names = [
            path.get("class").split()[1]
            for path in self.root.iter(f"{SVG}path")
            if path.get("class", "").startswith("sun-path")
        ]
        self.assertEqual(names, ["winter_solstice", "summer_solstice", "today"])

    def test_the_solstice_paths_are_dashed_and_todays_is_not(self):
        classes = [
            path.get("class")
            for path in self.root.iter(f"{SVG}path")
            if path.get("class", "").startswith("sun-path")
        ]
        self.assertIn("dashed", classes[0])
        self.assertIn("dashed", classes[1])
        self.assertNotIn("dashed", classes[2])

    def test_stars_are_drawn_as_one_path(self):
        """An element per star would be thousands; a dot is a zero-length line."""
        stars = self.find("stars")
        self.assertEqual(len(stars), 1)
        self.assertGreater(stars[0].get("d").count("M"), 50)

    def test_only_stars_above_the_horizon_are_drawn(self):
        """Below the horizon is behind you, and the clip would cut them anyway."""
        observer = projection.observer_at(
            self.model["latitude"], self.model["longitude"], self.when
        )
        visible = sum(
            1
            for constellation in self.model["constellations"]
            for ra, dec in constellation["stars"]
            if projection.alt_az(ra, dec, observer)[1] >= 0
        )
        self.assertEqual(self.find("stars")[0].get("d").count("M"), visible)

    def test_everything_inside_the_horizon_is_clipped_to_it(self):
        clip = self.root.find(f"{SVG}defs/{SVG}clipPath")
        self.assertIsNotNone(clip)
        clipped = [
            group
            for group in self.root.iter(f"{SVG}g")
            if group.get("clip-path") == f"url(#{clip.get('id')})"
        ]
        self.assertEqual(len(clipped), 1)

    def test_the_time_names_its_zone(self):
        """The reader's clock is routinely not the one the sky was drawn for."""
        self.assertIn("2026-08-02 22:30:00", self.find("when")[0].text)

    def test_a_legend_entry_per_body(self):
        legend = self.find("legend", tag="g")[0]
        self.assertEqual(len(legend.findall(f"{SVG}circle")), len(self.model["bodies"]))
        self.assertEqual(len(legend.findall(f"{SVG}text")), len(self.model["bodies"]))


class TestOptions(unittest.TestCase):
    """What the caller can change about it."""

    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        cls.sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        cls.sky.load()
        cls.model = cls.sky.sky_model(cls.when)

    def test_the_same_model_always_draws_the_same_picture(self):
        """Time comes from the model, not the clock, or nothing could be compared."""
        self.assertEqual(svg.render(self.model), svg.render(self.model))

    def test_a_later_moment_turns_the_sky(self):
        later = self.when + datetime.timedelta(hours=6)
        self.assertNotEqual(svg.render(self.model), svg.render(self.model, when=later))

    def test_turning_things_off_leaves_them_out(self):
        bare = svg.render(
            self.model, show_legend=False, show_time=False, show_constellations=False
        )
        self.assertNotIn('class="legend"', bare)
        self.assertNotIn('class="when"', bare)
        self.assertIn('class="stars" d=""', bare)

    def test_leaving_things_out_makes_it_shorter(self):
        full = ET.fromstring(svg.render(self.model)).get("viewBox")
        bare = ET.fromstring(
            svg.render(self.model, show_legend=False, show_time=False)
        ).get("viewBox")
        self.assertEqual(full.split()[2], bare.split()[2])
        self.assertGreater(float(full.split()[3]), float(bare.split()[3]))

    def test_a_title_makes_room_for_itself_above_the_chart(self):
        titled = svg.render(self.model, title="Seattle")
        self.assertIn(">Seattle<", titled)
        # the chart keeps its own coordinates and is moved down instead
        self.assertIn('transform="translate(0,', titled)

    def test_a_title_cannot_smuggle_in_markup(self):
        self.assertIn("&lt;script&gt;", svg.render(self.model, title="<script>"))

    def test_themes_choose_different_colors(self):
        light = svg.render(self.model, theme="light")
        dark = svg.render(self.model, theme="dark")
        self.assertIn(svg.PALETTES["light"]["ink"], light)
        self.assertIn(svg.PALETTES["dark"]["ink"], dark)
        self.assertNotIn("prefers-color-scheme", light)

    def test_auto_carries_both_and_lets_the_reader_decide(self):
        drawing = svg.render(self.model, theme="auto")
        self.assertIn("prefers-color-scheme: dark", drawing)
        self.assertIn(svg.PALETTES["light"]["ink"], drawing)
        self.assertIn(svg.PALETTES["dark"]["ink"], drawing)

    def test_the_dark_rules_come_second_so_they_win(self):
        """
        Identical selectors in both sets, or specificity decides instead of order.

        A dark ``text`` inside a media query would lose to a light ``text.compass``
        outside one, and the compass would stay black on a dark page.
        """
        drawing = svg.render(self.model, theme="auto")
        media = drawing.index("prefers-color-scheme")
        self.assertLess(drawing.index(svg.PALETTES["light"]["ink"]), media)
        self.assertGreater(drawing.index(svg.PALETTES["dark"]["ink"]), media)

    def test_a_palette_replaces_colors_by_name(self):
        self.assertIn("#abcdef", svg.render(self.model, palette={"ink": "#abcdef"}))

    def test_an_unknown_theme_is_refused(self):
        with self.assertRaises(ValueError):
            svg.render(self.model, theme="sepia")

    def test_no_colors_are_reached_for_through_a_variable(self):
        """
        librsvg does not implement ``var()``, and it is what most things rasterise
        with. An SVG that only works in a browser is half an SVG.
        """
        self.assertNotIn("var(", svg.render(self.model))

    def test_a_background_can_be_filled_in(self):
        self.assertIn("<rect", svg.render(self.model, background="#101318"))
        self.assertNotIn("<rect", svg.render(self.model))

    def test_two_charts_on_one_page_do_not_share_a_clip_path(self):
        one = svg.render(self.model, element_id="one")
        self.assertIn('id="one-horizon"', one)
        self.assertNotIn("skyfield-horizon", one)


class TestWithoutConstellations(unittest.TestCase):
    """A sky that was never asked to have any."""

    def test_draws_without_them(self):
        sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=False)
        sky.load()
        drawing = svg.render(sky.sky_model())
        self.assertIn('class="stars" d=""', drawing)
        self.assertEqual(ET.fromstring(drawing).tag, f"{SVG}svg")


if __name__ == "__main__":
    unittest.main()
