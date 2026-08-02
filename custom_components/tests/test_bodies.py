import datetime
import json
import math
import unittest

from ha_skyfield import bodies

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"


class TestSky(unittest.TestCase):
    def test_sky(self):
        sky = bodies.Sky((50.0, 50.0), "US/Pacific", constellation_list="CanisMajor")
        sky.load()
        self.assertGreater(len(sky._constellations), 0)


class TestSkyModel(unittest.TestCase):
    """The description of the sky handed to the card."""

    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30)
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

    def test_agrees_with_the_positions_used_for_plotting(self):
        """
        The model gives sky coordinates for a client to turn for itself.

        Turning them the way the card does should land where the plotting code
        puts the same body, which is what keeps the card and the image agreeing.
        """
        obs_time = self.sky.to_time(self.when)
        observer = self.sky.observer_at(obs_time)
        sidereal = _greenwich_sidereal_time(obs_time.ut1) + self.model["longitude"]

        for described in self.model["bodies"]:
            body = next(
                point for point in self.sky._points if point.label == described["label"]
            )
            azimuth, zenith_angle = self.sky.observe(observer, body._body)
            expected = (math.degrees(azimuth), 90 - zenith_angle)

            got = _alt_az(
                described["ra"], described["dec"], sidereal, self.model["latitude"]
            )
            self.assertLess(
                _separation(expected, got),
                0.005,
                f"{described['label']} is in the wrong place",
            )


def _greenwich_sidereal_time(julian_date):
    """The same formula the card uses, to check the card's approach here."""
    days = julian_date - 2451545.0
    centuries = days / 36525
    return (
        280.46061837
        + 360.98564736629 * days
        + 0.000387933 * centuries**2
        - centuries**3 / 38710000
    ) % 360


def _alt_az(ra, dec, sidereal_time, latitude):
    """Hour angle trigonometry, as the card does it."""
    hour_angle = math.radians(sidereal_time - ra)
    dec, lat = math.radians(dec), math.radians(latitude)
    altitude = math.asin(
        math.sin(dec) * math.sin(lat)
        + math.cos(dec) * math.cos(lat) * math.cos(hour_angle)
    )
    azimuth = math.atan2(
        -math.cos(dec) * math.sin(hour_angle),
        math.sin(dec) * math.cos(lat)
        - math.cos(dec) * math.sin(lat) * math.cos(hour_angle),
    )
    return math.degrees(azimuth) % 360, math.degrees(altitude)


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
