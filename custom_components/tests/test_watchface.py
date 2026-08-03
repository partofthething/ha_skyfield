"""
The watch face's C, compiled on this machine and checked against the Python.

The watch is the third place this arithmetic is written down, and the one
hardest to look at while it is running. So it gets compiled here with libm
standing in for the Pebble SDK's lookup tables, fed the same sky as the Python,
and held to the same answers.

What this proves is that the formulae in ``pebble/src/c/projection.c`` are right
and that its integer arithmetic does not lose anything that matters. It does not
prove the SDK's own sine table is precise enough; that is good to about a part in
ten thousand, which on a 180 pixel watch face is a hundredth of a pixel.

Needs a C compiler, and skips itself without one.
"""

import datetime
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from ha_skyfield import pebble, projection

HERE = pathlib.Path(__file__).parent
WATCHFACE = HERE.parent.parent / "pebble" / "src" / "c"

CC = shutil.which("cc") or shutil.which("gcc")

# the same layout the card and the rendered SVG use, so the numbers are comparable
LAYOUT = {"centre": 200, "horizon_radius": 165}

WHEN = datetime.datetime(2026, 8, 3, 5, 30, tzinfo=datetime.UTC)

PLACES = [(47.608, -122.335), (51.5, -0.13), (-33.87, 151.21), (0.0, 0.0)]

SAMPLES = [
    (0.0, 0.0),
    (133.4, 17.5),
    (359.99, 12.0),
    (0.01, -12.0),
    (87.0, 45.2),
    (180.0, -60.0),
    (270.0, 85.0),
    (45.0, -85.0),
    (200.0, 30.0),
    (300.0, -45.0),
]

# how far the C may be from the Python. A step of the wire format is 360/65536 of
# a turn, so a couple of them is the rounding of the numbers themselves rather
# than anything the arithmetic did.
ANGLE_TOLERANCE = 4  # in TRIG_MAX_ANGLE units, about a fiftieth of a degree

# half a unit of four hundred, which is the most a whole number can be from the
# number it was rounded from. Rounding the radius to whole pixels before the
# trigonometry rather than after cost two units here, so this is tight enough to
# notice that coming back.
PIXEL_TOLERANCE = 0.5


@unittest.skipUnless(CC, "checking the watch face needs a C compiler")
class TestTheWatchAgreesWithThePython(unittest.TestCase):
    """The same sky, placed by the watch's integers and by Python's floats."""

    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.mkdtemp(prefix="skyfield-watchface-")
        cls.probe = pathlib.Path(cls.build) / "probe"
        compiled = subprocess.run(
            [
                CC,
                "-DSKY_HOST",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-o",
                str(cls.probe),
                str(HERE / "host_probe.c"),
                str(HERE / "host_trig.c"),
                str(WATCHFACE / "projection.c"),
                "-lm",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise AssertionError(f"the watch face did not compile:\n{compiled.stderr}")

        cls.cases = [(place, sample) for place in PLACES for sample in SAMPLES]
        cls.answers = cls._ask(cls.cases)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.build, ignore_errors=True)

    @classmethod
    def _ask(cls, cases):
        """Put every case through the compiled C in one go."""
        stamp = int(WHEN.timestamp())
        lines = [
            f"{stamp} {round(latitude * 100)} {round(longitude * 100)} "
            f"{pebble._ra(ra)} {pebble._dec(dec)}"
            for (latitude, longitude), (ra, dec) in cases
        ]
        finished = subprocess.run(
            [str(cls.probe)],
            input="\n".join(lines) + "\n",
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return [
            [int(field) for field in line.split()]
            for line in finished.stdout.strip().splitlines()
        ]

    @staticmethod
    def _degrees(units):
        return units * 360 / pebble.TRIG_MAX_ANGLE

    def test_every_case_was_answered(self):
        self.assertEqual(len(self.answers), len(self.cases))

    def test_sidereal_time(self):
        """
        The one part worked out from the clock rather than sent over.

        It is also the part most easily got wrong by a whole turn, so this is
        checked separately from where anything ends up.
        """
        seen = {}
        for ((latitude, longitude), _sample), answer in zip(
            self.cases, self.answers, strict=True
        ):
            seen[(latitude, longitude)] = answer[4]

        for (latitude, longitude), theirs in seen.items():
            with self.subTest(latitude=latitude, longitude=longitude):
                ours = projection.observer_at(latitude, longitude, WHEN).sidereal_time
                # the C keeps longitude to a hundredth of a degree, as the wire does
                rounded = round(longitude * 100) / 100
                expected = ours - longitude + rounded
                difference = (self._degrees(theirs) - expected + 180) % 360 - 180
                self.assertLess(abs(difference), self._degrees(ANGLE_TOLERANCE))

    def test_every_body_lands_in_the_same_place(self):
        for ((latitude, longitude), (ra, dec)), answer in zip(
            self.cases, self.answers, strict=True
        ):
            with self.subTest(latitude=latitude, ra=ra, dec=dec):
                observer = projection.observer_at(latitude, longitude, WHEN)
                azimuth, altitude = projection.alt_az(ra, dec, observer)

                theirs_azimuth = self._degrees(answer[0])
                theirs_altitude = self._degrees(answer[1])

                # azimuth means nothing at the very top of the sky, where every
                # direction is the same one, so only compare it lower down
                if abs(altitude) < 89:
                    apart = (theirs_azimuth - azimuth + 180) % 360 - 180
                    self.assertLess(
                        abs(apart), self._degrees(ANGLE_TOLERANCE), "azimuth"
                    )
                self.assertAlmostEqual(
                    theirs_altitude,
                    altitude,
                    delta=self._degrees(ANGLE_TOLERANCE),
                    msg="altitude",
                )

    def test_the_same_pixel_on_the_drawing(self):
        """
        All the way through, on the same 400-unit layout the SVG uses.

        This is the one that matters: it is what says the watch draws the chart
        the card and the SVG draw, rather than merely doing similar arithmetic.
        """
        project = projection.projector()
        for ((latitude, longitude), (ra, dec)), answer in zip(
            self.cases, self.answers, strict=True
        ):
            with self.subTest(latitude=latitude, ra=ra, dec=dec):
                observer = projection.observer_at(latitude, longitude, WHEN)
                x, y = project(*projection.alt_az(ra, dec, observer))
                self.assertAlmostEqual(answer[2], x, delta=PIXEL_TOLERANCE)
                self.assertAlmostEqual(answer[3], y, delta=PIXEL_TOLERANCE)

    def test_below_the_horizon_is_reported_as_below(self):
        """
        A negative altitude has to come back negative.

        atan2 returns a positive angle going the long way round, and a body that
        had set would otherwise be drawn as though it were high in the sky --
        which looks perfectly reasonable and is completely wrong.
        """
        below = [
            (place, sample)
            for place, sample in self.cases
            for observer in [projection.observer_at(place[0], place[1], WHEN)]
            if projection.alt_az(sample[0], sample[1], observer)[1] < -5
        ]
        self.assertGreater(len(below), 3, "no test case is below the horizon")

        for case in below:
            answer = self.answers[self.cases.index(case)]
            with self.subTest(case=case):
                self.assertLess(answer[1], 0)


@unittest.skipUnless(CC, "checking the watch face needs a C compiler")
class TestTheWireFormatIsTheWatchsOwnUnits(unittest.TestCase):
    """
    The angles sent are already the units the SDK's trigonometry takes.

    That is the point of the scaling in ha_skyfield.pebble: the C can hand what
    arrives straight to sin_lookup without converting it.
    """

    def test_a_full_turn_of_right_ascension_is_the_whole_range(self):
        self.assertEqual(pebble.TRIG_MAX_ANGLE, 0x10000)
        self.assertEqual(pebble._ra(90.0), pebble.TRIG_MAX_ANGLE // 4)
        self.assertEqual(pebble._ra(180.0), pebble.TRIG_MAX_ANGLE // 2)

    def test_a_quarter_turn_of_declination_is_a_quarter_of_the_range(self):
        self.assertEqual(pebble._dec(90.0), pebble.TRIG_MAX_ANGLE // 4)
        self.assertEqual(pebble._dec(-90.0), -(pebble.TRIG_MAX_ANGLE // 4))
        self.assertEqual(pebble._dec(45.0), pebble.TRIG_MAX_ANGLE // 8)


if __name__ == "__main__":
    unittest.main()
