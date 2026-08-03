"""
Run the card's own JavaScript and check the Python agrees with it.

This is the test the whole arrangement rests on. There are two renderers, and
they are only two views of one chart for as long as they put a body in the same
place given the same sky. Everything else -- the shared constants, the mirrored
function names -- is there to make that likely; this is what makes it checked.

Needs node, and skips itself without one.
"""

import json
import pathlib
import shutil
import subprocess
import textwrap
import unittest
from datetime import UTC, datetime

from ha_skyfield import projection

CARD = pathlib.Path(projection.__file__).parent / "frontend" / "skyfield-card.js"

NODE = shutil.which("node")

# a scattering of sky: the pole, the equator, either side of where right
# ascension wraps round, and a couple of ordinary places
SAMPLES = [
    (0.0, 0.0),
    (133.4, 17.5),
    (359.99, 12.0),
    (0.01, -12.0),
    (87.0, 45.2),
    (180.0, -60.0),
    (270.0, 89.9),
    (45.0, -89.9),
]

PLACES = [
    (47.608, -122.335),  # Seattle, and the observer the rest of the suite uses
    (51.5, -0.13),  # north, and barely off the meridian
    (-33.87, 151.21),  # the other hemisphere, and the far side of the world
    (0.0, 0.0),
]

WHEN = datetime(2026, 8, 3, 5, 30, tzinfo=UTC)

# the card is written for a browser and registers itself as a custom element as
# soon as it loads, so stand in for the few globals it touches on the way past
PROBE = """
globalThis.HTMLElement = class {};
globalThis.customElements = { get: () => true, define: () => {} };
globalThis.window = globalThis;

const card = await import(%(card)s);
const when = new Date(%(when)s);
const places = %(places)s;
const samples = %(samples)s;

console.log(JSON.stringify(places.map(([latitude, longitude]) => {
  const observer = card.observerAt(latitude, longitude, when);
  return {
    sidereal: observer.siderealTime,
    positions: samples.map(([ra, dec]) => card.altAz(ra, dec, observer)),
  };
})));
"""


@unittest.skipUnless(NODE, "comparing against the card needs node")
class TestTheCardAndThePythonAgree(unittest.TestCase):
    """The same sky, placed by both, to within nothing that could be drawn."""

    @classmethod
    def setUpClass(cls):
        script = PROBE % {
            "card": json.dumps(str(CARD)),
            "when": json.dumps(WHEN.isoformat().replace("+00:00", "Z")),
            "places": json.dumps(PLACES),
            "samples": json.dumps(SAMPLES),
        }
        finished = subprocess.run(
            [NODE, "--input-type=module", "-e", textwrap.dedent(script)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if finished.returncode != 0:
            raise AssertionError(f"could not run the card:\n{finished.stderr}")
        cls.from_card = json.loads(finished.stdout)

    def test_sidereal_time(self):
        for (latitude, longitude), card in zip(PLACES, self.from_card, strict=True):
            with self.subTest(latitude=latitude, longitude=longitude):
                observer = projection.observer_at(latitude, longitude, WHEN)
                self.assertAlmostEqual(
                    observer.sidereal_time, card["sidereal"], places=9
                )

    def test_every_body_lands_in_the_same_place(self):
        for (latitude, longitude), card in zip(PLACES, self.from_card, strict=True):
            observer = projection.observer_at(latitude, longitude, WHEN)
            for (ra, dec), expected in zip(SAMPLES, card["positions"], strict=True):
                with self.subTest(latitude=latitude, ra=ra, dec=dec):
                    azimuth, altitude = projection.alt_az(ra, dec, observer)
                    self.assertAlmostEqual(azimuth, expected[0], places=9)
                    self.assertAlmostEqual(altitude, expected[1], places=9)

    def test_the_same_place_on_the_drawing(self):
        """
        The whole way through: sky coordinates to a point on the chart.

        A tenth of a unit is the precision the coordinates are written out with,
        so agreeing well inside that is agreeing exactly as far as the drawing
        can tell.
        """
        project = projection.projector()
        for (latitude, longitude), card in zip(PLACES, self.from_card, strict=True):
            observer = projection.observer_at(latitude, longitude, WHEN)
            for (ra, dec), expected in zip(SAMPLES, card["positions"], strict=True):
                with self.subTest(latitude=latitude, ra=ra, dec=dec):
                    ours = project(*projection.alt_az(ra, dec, observer))
                    theirs = project(*expected)
                    self.assertAlmostEqual(ours[0], theirs[0], places=6)
                    self.assertAlmostEqual(ours[1], theirs[1], places=6)


if __name__ == "__main__":
    unittest.main()
