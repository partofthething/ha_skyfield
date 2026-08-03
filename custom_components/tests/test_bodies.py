import datetime
import json
import math
import os
import time
import unittest
from zoneinfo import ZoneInfo

from ha_skyfield import bodies, projection

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"


def zoneless(*when):
    """
    A moment with no zone attached to it.

    Several tests below are about what such a moment is taken to mean, so these
    are deliberately naive rather than an oversight.
    """
    return datetime.datetime(*when)


class TestSky(unittest.TestCase):
    def test_sky(self):
        # a real zone name rather than the "US/Pacific" style, which is a legacy
        # alias that modern tzdata packages leave out
        sky = bodies.Sky((50.0, 50.0), PACIFIC, constellation_list="CanisMajor")
        sky.load()
        self.assertGreater(len(sky._constellations), 0)


class TestSkyModel(unittest.TestCase):
    """The description of the sky handed to the card."""

    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        cls.sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        cls.sky.load()
        cls.model = cls.sky.sky_model(cls.when)

    def test_is_json(self):
        """Nothing numpy-shaped should survive into the model."""
        self.assertIsInstance(json.dumps(self.model), str)

    def test_reports_the_time_it_was_asked_for(self):
        """A naive time means the configured zone, as it does everywhere else."""
        self.assertEqual(self.model["generated"][:16], "2026-08-02T22:30")

    def test_observer(self):
        self.assertAlmostEqual(self.model["latitude"], SEATTLE[0])
        self.assertAlmostEqual(self.model["longitude"], SEATTLE[1])

    def test_sun_is_where_it_should_be(self):
        """On this evening the Sun sits at about 8h54m, 17 degrees north."""
        sun = next(b for b in self.model["bodies"] if b["label"] == "Sun")
        self.assertAlmostEqual(sun["ra"], 133.4, delta=0.5)
        self.assertAlmostEqual(sun["dec"], 17.5, delta=0.5)

    def test_paths_are_daily_curves(self):
        names = [path["name"] for path in self.model["paths"]]
        self.assertEqual(names, ["winter_solstice", "summer_solstice", "today"])
        for path in self.model["paths"]:
            self.assertEqual(len(path["azimuth"]), len(path["altitude"]))
            self.assertTrue(all(-90 <= alt <= 90 for alt in path["altitude"]))

    def test_summer_sun_climbs_higher_than_winter_sun(self):
        highest = {path["name"]: max(path["altitude"]) for path in self.model["paths"]}
        self.assertGreater(highest["summer_solstice"], highest["winter_solstice"])

    def test_constellation_lines_point_at_real_stars(self):
        for constellation in self.model["constellations"]:
            stars = constellation["stars"]
            self.assertGreater(len(stars), 0)
            for start, end in constellation["lines"]:
                self.assertLess(start, len(stars))
                self.assertLess(end, len(stars))

    def test_agrees_with_the_positions_skyfield_computes(self):
        """
        The model gives sky coordinates for a client to turn for itself.

        Turning them the way :mod:`ha_skyfield.projection` does -- which is the
        way the card does, checked in ``test_svg_matches_card`` -- should land
        where skyfield says the body actually is. That is what makes the shortcut
        the card and the renderer both take an honest one, rather than merely a
        consistent one.
        """
        observer = self.sky.observer_at(self.sky.to_time(self.when))
        turned = projection.observer_at(
            self.model["latitude"], self.model["longitude"], self.when
        )

        for described in self.model["bodies"]:
            body = next(
                point for point in self.sky._points if point.label == described["label"]
            )
            azimuth, zenith_angle = self.sky.observe(observer, body._body)
            expected = (math.degrees(azimuth), 90 - zenith_angle)

            got = projection.alt_az(described["ra"], described["dec"], turned)
            self.assertLess(
                _separation(expected, got),
                0.005,
                f"{described['label']} is in the wrong place",
            )

    def test_constellations_are_where_skyfield_puts_them_too(self):
        """The same check, for the stars, which arrive by a different route."""
        obs_time = self.sky.to_time(self.when)
        turned = projection.observer_at(
            self.model["latitude"], self.model["longitude"], self.when
        )

        for constellation, drawn in zip(
            self.sky._constellations, self.model["constellations"], strict=True
        ):
            azimuths, zeniths = self.sky.to_altaz(constellation._star_xyz, obs_time)
            for index, (ra, dec) in enumerate(drawn["stars"]):
                with self.subTest(constellation=drawn["name"], star=index):
                    expected = (math.degrees(azimuths[index]), 90 - zeniths[index])
                    got = projection.alt_az(ra, dec, turned)
                    self.assertLess(_separation(expected, got), 0.005)


class TestTimeZones(unittest.TestCase):
    """The configured location's zone decides everything; the machine's does not."""

    # zones to pretend the machine is set to, spread either side of the observer
    MACHINE_ZONES = ("UTC", "Australia/Sydney", "America/New_York")

    @classmethod
    def setUpClass(cls):
        cls.sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=False)
        cls.sky.load()

    def _pretend_the_machine_is_in(self, zone):
        """Move the machine's clock zone for the rest of one test."""
        if not hasattr(time, "tzset"):
            self.skipTest("changing the machine's zone needs a Unix tzset")
        original = os.environ.get("TZ")

        def restore():
            if original is None:
                del os.environ["TZ"]
            else:
                os.environ["TZ"] = original
            time.tzset()

        self.addCleanup(restore)
        os.environ["TZ"] = zone
        time.tzset()

    def test_now_is_aware_and_in_the_configured_zone(self):
        now = self.sky.local_time()
        self.assertEqual(now.tzinfo, ZoneInfo(PACIFIC))

    def test_a_moment_without_a_zone_means_the_configured_one(self):
        naive = zoneless(2026, 8, 2, 22, 30)
        self.assertEqual(
            self.sky.local_time(naive).isoformat(), "2026-08-02T22:30:00-07:00"
        )

    def test_a_moment_with_a_zone_is_moved_into_the_configured_one(self):
        elsewhere = datetime.datetime(2026, 8, 3, 5, 30, tzinfo=datetime.UTC)
        self.assertEqual(
            self.sky.local_time(elsewhere).isoformat(), "2026-08-02T22:30:00-07:00"
        )

    def test_one_moment_written_three_ways_draws_one_sky(self):
        in_utc = datetime.datetime(2026, 8, 3, 5, 30, tzinfo=datetime.UTC)
        ways = [
            zoneless(2026, 8, 2, 22, 30),
            in_utc,
            in_utc.astimezone(ZoneInfo("Australia/Sydney")),
        ]
        first, *rest = [self.sky.sky_model(way) for way in ways]
        for other in rest:
            self.assertEqual(first, other)

    def test_todays_path_follows_the_local_day_not_the_utc_one(self):
        """Half past ten at night in Seattle is already tomorrow at Greenwich."""

        def todays_path(when):
            model = self.sky.sky_model(when)
            return next(p for p in model["paths"] if p["name"] == "today")

        morning = zoneless(2026, 8, 2, 10, 0)  # still the 2nd, everywhere
        evening = zoneless(2026, 8, 2, 22, 30)  # the 3rd, at Greenwich
        self.assertEqual(todays_path(morning), todays_path(evening))

    def test_the_machines_zone_does_not_move_the_sky(self):
        """
        A Home Assistant container usually runs on UTC wherever the house is.

        Reading the machine's wall clock and calling it local turned the sky by
        the difference between the two, which for Seattle on UTC is seven hours,
        or a hundred and five degrees.
        """
        for zone in self.MACHINE_ZONES:
            with self.subTest(machine_zone=zone):
                self._pretend_the_machine_is_in(zone)
                elapsed = self.sky.local_time() - datetime.datetime.now(datetime.UTC)
                self.assertLess(abs(elapsed.total_seconds()), 5)

    def test_a_fixed_moment_reads_the_same_whatever_the_machine_says(self):
        fixed = zoneless(2026, 8, 2, 22, 30)
        drawn = set()
        for zone in self.MACHINE_ZONES:
            with self.subTest(machine_zone=zone):
                self._pretend_the_machine_is_in(zone)
                drawn.add(json.dumps(self.sky.sky_model(fixed), sort_keys=True))
        self.assertEqual(len(drawn), 1)


def _separation(first, second):
    """Angle between two directions in the sky, in degrees."""
    (azi1, alt1), (azi2, alt2) = first, second
    alt1, alt2 = math.radians(alt1), math.radians(alt2)
    delta = math.radians((azi1 - azi2 + 180) % 360 - 180)
    return math.degrees(
        math.acos(
            min(
                1.0,
                math.sin(alt1) * math.sin(alt2)
                + math.cos(alt1) * math.cos(alt2) * math.cos(delta),
            )
        )
    )
