"""
The painted chart.

Home Assistant's camera entity will not show an SVG, so there has to be a
picture as well. What matters most here is that it is the *same* chart: it is
painted from the same :mod:`ha_skyfield.scene`, and these check that what comes
out lands where the scene said it would.
"""

import datetime
import io
import math
import unittest
from zoneinfo import ZoneInfo

from ha_skyfield import bodies, raster, scene, styles, svg

try:
    from PIL import Image
except ImportError:  # pragma: no cover - depends on the install
    Image = None

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"


def open_png(data):
    return Image.open(io.BytesIO(data))


def rgb(value):
    return tuple(int(value[at : at + 2], 16) for at in (1, 3, 5))


@unittest.skipUnless(Image, "painting the chart needs Pillow")
class TestPainting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        cls.sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        cls.sky.load()
        cls.model = cls.sky.sky_model(cls.when)
        cls.png = raster.render(cls.model)
        cls.picture = open_png(cls.png)

    def test_it_is_a_png(self):
        self.assertEqual(self.png[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.picture.format, "PNG")

    def test_it_is_the_width_asked_for(self):
        self.assertEqual(self.picture.width, raster.DEFAULT_WIDTH)

    def test_it_keeps_the_charts_shape(self):
        """The height follows the width; the chart is not squashed to fit."""
        drawing = scene.build(self.model)
        self.assertAlmostEqual(
            self.picture.height / self.picture.width,
            drawing.height / drawing.width,
            places=2,
        )

    def test_the_same_model_always_paints_the_same_picture(self):
        self.assertEqual(raster.render(self.model), raster.render(self.model))

    def test_a_later_moment_turns_the_sky(self):
        later = self.when + datetime.timedelta(hours=6)
        self.assertNotEqual(self.png, raster.render(self.model, when=later))

    def test_a_narrower_picture_is_narrower(self):
        self.assertEqual(open_png(raster.render(self.model, width=320)).width, 320)

    def test_it_is_not_transparent(self):
        """
        A see-through chart lands on a background that may be any color at all.

        Dark ink on a dark dashboard is exactly where this would end up, so the
        picture brings its own paper.
        """
        corners = self.picture.convert("RGBA")
        self.assertEqual(corners.getpixel((0, 0))[3], 255)

    def test_jpeg_if_asked_for_by_name(self):
        data = raster.render(self.model, image_format="jpeg")
        self.assertEqual(open_png(data).format, "JPEG")

    def test_nothing_else(self):
        with self.assertRaises(ValueError):
            raster.render(self.model, image_format="gif")

    def test_a_picture_cannot_follow_a_preference_it_cannot_ask_about(self):
        """There is no `auto` for something painted once and looked at later."""
        with self.assertRaises(ValueError) as refused:
            raster.render(self.model, theme="auto")
        self.assertIn("light", str(refused.exception))

    def test_the_themes_really_differ(self):
        light = open_png(raster.render(self.model, theme="light"))
        dark = open_png(raster.render(self.model, theme="dark"))
        self.assertEqual(
            light.convert("RGB").getpixel((0, 0)),
            rgb(styles.PALETTES["light"]["paper"]),
        )
        self.assertEqual(
            dark.convert("RGB").getpixel((0, 0)), rgb(styles.PALETTES["dark"]["paper"])
        )

    def test_a_palette_replaces_colors_by_name(self):
        odd = raster.render(self.model, palette={"paper": "#ff00ff"})
        self.assertEqual(open_png(odd).convert("RGB").getpixel((0, 0)), (255, 0, 255))


@unittest.skipUnless(Image, "painting the chart needs Pillow")
class TestItIsTheSameChart(unittest.TestCase):
    """
    The picture and the SVG are two renderings of one scene.

    Not two drawings that resemble each other: :mod:`ha_skyfield.scene` decides
    where everything goes and both are handed the result, so these check that
    what was painted is where the scene put it.
    """

    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        sky.load()
        cls.model = sky.sky_model(cls.when)
        cls.drawing = scene.build(cls.model)
        cls.width = 800
        cls.scale = cls.width / cls.drawing.width
        cls.picture = open_png(
            raster.render(cls.model, width=cls.width, theme="light")
        ).convert("RGB")

    def _body(self, label):
        for group in self.drawing.chart:
            if group.style == "body":
                for item in group.items:
                    if item.label == label:
                        return item
        raise AssertionError(f"{label} is not in the scene")

    def test_a_body_is_painted_where_the_scene_put_it(self):
        """
        Looked for at the spot rather than hunted for by color.

        Hunting turns up the legend swatch of the same body and every
        antialiased pixel that happens to land on the same value, neither of
        which says anything about where the body went.
        """
        moon = self._body("Moon")
        wanted = rgb("#d3d3d3")  # lightgrey, as bodies.BODIES has it

        painted = self.picture.getpixel(
            (round(moon.x * self.scale), round(moon.y * self.scale))
        )
        apart = sum(abs(a - b) for a, b in zip(painted, wanted, strict=True))
        self.assertLess(apart, 30, f"the Moon's own spot is {painted}, not {wanted}")

    def test_a_body_is_not_painted_where_it_is_not(self):
        """The check above would pass on a chart painted entirely grey."""
        moon = self._body("Moon")
        wanted = rgb("#d3d3d3")
        # straight across the chart from it, which is empty sky at this moment
        opposite = self.picture.getpixel(
            (
                round((2 * self.drawing.clip.x - moon.x) * self.scale),
                round(moon.y * self.scale),
            )
        )
        apart = sum(abs(a - b) for a, b in zip(opposite, wanted, strict=True))
        self.assertGreater(apart, 30)

    def test_nothing_clipped_escapes_the_horizon(self):
        """
        The Sun's paths run well outside the chart and must be cut off.

        Painting has no clip path of its own, so this is the one thing most
        likely to differ from the SVG, where the browser does it.
        """
        self.assertEqual(self._solstice_pixels(outside=True), 0)

    def test_the_solstice_paths_were_actually_painted(self):
        """Otherwise the test above passes by painting nothing at all."""
        self.assertGreater(self._solstice_pixels(outside=False), 200)

    def _solstice_pixels(self, outside: bool) -> int:
        """
        Count pixels of either solstice color, inside or outside the horizon.

        Only within the chart's own square: the legend below it carries a swatch
        for Neptune, whose royalblue is near enough to the winter color to be
        counted, and it sits outside the horizon quite legitimately.
        """
        cx = self.drawing.clip.x * self.scale
        cy = self.drawing.clip.y * self.scale
        radius = self.drawing.clip.radius * self.scale
        chart_bottom = round((self.drawing.top + self.drawing.width) * self.scale)

        wanted = [rgb(styles.PALETTES["light"][name]) for name in ("winter", "summer")]
        found = 0
        for y in range(min(chart_bottom, self.picture.height)):
            for x in range(self.picture.width):
                beyond = math.hypot(x - cx, y - cy) > radius + 2
                if beyond != outside:
                    continue
                pixel = self.picture.getpixel((x, y))
                if any(
                    sum(abs(a - b) for a, b in zip(pixel, color, strict=True)) < 40
                    for color in wanted
                ):
                    found += 1
        return found

    def test_both_are_drawn_from_one_scene(self):
        """
        The two agree because they are given the same shapes, not by luck.

        If either grew its own idea of the layout this would still pass, so it
        is really the tests above that check the drawing; this checks the shape
        of the arrangement, which is what keeps them from drifting.
        """
        drawn = svg.render(self.model)
        for body in self.drawing.chart:
            if body.style != "body":
                continue
            for item in body.items:
                from ha_skyfield.projection import number

                self.assertIn(f'cx="{number(item.x)}" cy="{number(item.y)}"', drawn)


@unittest.skipUnless(Image, "painting the chart needs Pillow")
class TestDashes(unittest.TestCase):
    """Pillow draws only solid lines, so the dashes are cut by hand."""

    def test_a_straight_line_becomes_the_expected_run_of_dashes(self):
        runs = raster._dashed([(0, 0), (27, 0)], (5, 4))
        self.assertEqual(len(runs), 3)
        for run in runs:
            self.assertAlmostEqual(math.dist(run[0], run[-1]), 5, delta=0.001)

    def test_the_gaps_are_the_right_size(self):
        runs = raster._dashed([(0, 0), (27, 0)], (5, 4))
        self.assertAlmostEqual(runs[1][0][0] - runs[0][-1][0], 4, delta=0.001)

    def test_a_line_shorter_than_one_dash_stays_whole(self):
        self.assertEqual(raster._dashed([(0, 0), (3, 0)], (5, 4)), [[(0, 0), (3, 0)]])

    def test_dashes_follow_a_bend(self):
        """The pattern is measured along the line, not along the axis."""
        runs = raster._dashed([(0, 0), (10, 0), (10, 10)], (5, 4))
        self.assertGreater(len(runs), 1)
        for run in runs:
            self.assertGreaterEqual(len(run), 2)


if __name__ == "__main__":
    unittest.main()
