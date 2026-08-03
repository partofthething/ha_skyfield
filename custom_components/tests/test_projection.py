"""
The Python and the JavaScript have to lay the chart out the same way.

There are two copies of this drawing: the card draws it in a browser so that it
can turn the sky without asking the server anything, and :mod:`ha_skyfield.svg`
draws it in Python so that it can be had without a browser. Neither is going
away, so what matters is that they cannot drift apart quietly.

This checks the numbers. :mod:`test_svg_matches_card` checks the arithmetic, by
running the actual JavaScript.
"""

import pathlib
import re
import unittest

from ha_skyfield import projection

CARD = pathlib.Path(projection.__file__).parent / "frontend" / "skyfield-card.js"


def javascript_constants():
    """
    Pull the card's layout constants out of its source.

    Reading the JavaScript rather than keeping a second list here on purpose: a
    list would be one more thing to update, and updating it is exactly what
    somebody changing the card would forget to do.
    """
    source = CARD.read_text()
    numbers = dict(
        re.findall(r"^const ([A-Z_]+) = ([-\d.]+);", source, flags=re.MULTILINE)
    )
    compass = re.search(r"^const COMPASS = \[(.*?)\];", source, flags=re.MULTILINE)
    return numbers, tuple(re.findall(r'"(\w+)"', compass.group(1)))


class TestLayoutConstantsMatchTheCard(unittest.TestCase):
    """Every number that decides where something goes, in both languages."""

    @classmethod
    def setUpClass(cls):
        cls.numbers, cls.compass = javascript_constants()

    def test_the_card_was_actually_read(self):
        """Guard against a regex that quietly stops matching anything."""
        self.assertTrue(CARD.is_file(), f"{CARD} is missing")
        self.assertGreaterEqual(len(self.numbers), 6)

    def test_numbers(self):
        for name in (
            "SIZE",
            "HORIZON",
            "HORIZON_RADIUS",
            "MARKER_SCALE",
            "RING_STEP",
            "POINTS_PER_LINE",
        ):
            with self.subTest(constant=name):
                self.assertIn(name, self.numbers, f"{name} is no longer in the card")
                self.assertEqual(
                    float(self.numbers[name]),
                    float(getattr(projection, name)),
                    f"{name} differs between the card and projection.py",
                )

    def test_compass(self):
        self.assertEqual(self.compass, projection.COMPASS)

    def test_centre_is_the_middle_of_the_drawing(self):
        self.assertEqual(projection.CENTRE, projection.SIZE / 2)


class TestRounding(unittest.TestCase):
    """
    Coordinates are rounded the way JavaScript rounds them.

    Python breaks a tie to the nearest even number and JavaScript breaks it
    upwards, which would put the two a tenth of a unit apart on the rare
    coordinate that lands exactly on a half.
    """

    def test_halves_go_up(self):
        self.assertEqual(projection.round_unit(0.25), 0.3)
        self.assertEqual(projection.round_unit(0.35), 0.4)
        self.assertEqual(projection.round_unit(-0.25), -0.2)

    def test_whole_numbers_lose_their_decimal_point(self):
        self.assertEqual(projection.number(200.0), "200")
        self.assertEqual(projection.number(173.24), "173.2")
        self.assertEqual(projection.number(-0.02), "0")


class TestProjection(unittest.TestCase):
    """Where a point of sky lands on the drawing."""

    def test_straight_up_is_the_middle(self):
        project = projection.projector()
        self.assertAlmostEqual(projection.radius_for(90), 0)
        x, y = project(0, 90)
        self.assertAlmostEqual(x, projection.CENTRE)
        self.assertAlmostEqual(y, projection.CENTRE)

    def test_the_horizon_is_the_rim(self):
        self.assertAlmostEqual(projection.radius_for(0), projection.HORIZON_RADIUS)

    def test_south_is_at_the_bottom_by_default(self):
        """The chart reads as though you were lying on your back looking up."""
        x, y = projection.projector()(180, 0)
        self.assertAlmostEqual(x, projection.CENTRE)
        self.assertAlmostEqual(y, projection.CENTRE - projection.HORIZON_RADIUS)

    def test_north_up_turns_it_around(self):
        x, y = projection.projector(north_up=True)(0, 0)
        self.assertAlmostEqual(x, projection.CENTRE)
        self.assertAlmostEqual(y, projection.CENTRE - projection.HORIZON_RADIUS)

    def test_flipping_mirrors_east_and_west(self):
        plain = projection.projector()(90, 30)
        flipped = projection.projector(horizontal_flip=True)(90, 30)
        self.assertAlmostEqual(plain[0], projection.SIZE - flipped[0])
        self.assertAlmostEqual(plain[1], flipped[1])


class TestSiderealTimeNeedsAZone(unittest.TestCase):
    """
    A moment with no zone is refused rather than guessed at.

    The machine's clock is routinely somewhere other than the sky being drawn,
    and reading a naive moment as the machine's own would turn the sky by the
    difference -- seven hours, or a hundred and five degrees, for a Home
    Assistant container on UTC drawing a garden in Seattle.
    """

    def test_naive_is_refused(self):
        import datetime

        with self.assertRaises(ValueError):
            projection.greenwich_sidereal_time(datetime.datetime(2026, 8, 2, 22, 30))


if __name__ == "__main__":
    unittest.main()
