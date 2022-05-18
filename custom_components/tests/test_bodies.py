import unittest

from ha_skyfield import bodies


class TestSky(unittest.TestCase):
    def test_sky(self):
        sky = bodies.Sky((50.0, 50.0), "US/Pacific", constellation_list="CanisMajor")
        sky.load()
        self.assertGreater(len(sky._constellations), 0)
