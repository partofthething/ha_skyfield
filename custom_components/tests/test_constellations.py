import unittest

from ha_skyfield import constellations


class TestConstellations(unittest.TestCase):
    def test_load(self):
        cs = constellations.build_constellations()
        names = [c.name for c in cs]
        self.assertIn("Andromeda", names)
