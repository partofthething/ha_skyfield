"""
The payload a watch reads.

The reader at the other end is C on a microcontroller, which will believe
whatever bytes it is handed. So these check the layout rather than merely that
a round trip works, and they check that it stays small.
"""

import datetime
import unittest
from zoneinfo import ZoneInfo

from ha_skyfield import bodies, pebble

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"

# what the watch can rely on being able to receive in one message. The inbox is
# negotiated at runtime and can be a good deal larger, but this is the size the
# chunking is sized against.
APP_MESSAGE_BUDGET = 2048


class TestPacking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        cls.sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        cls.sky.load()
        cls.model = cls.sky.sky_model(cls.when)
        cls.payload = pebble.pack(cls.model)
        cls.read = pebble.unpack(cls.payload)

    def test_starts_with_a_magic_number_and_a_version(self):
        self.assertEqual(self.payload[:3], b"SKY")
        self.assertEqual(self.payload[3], pebble.FORMAT_VERSION)

    def test_the_length_is_exactly_what_the_header_promises(self):
        """A short read on the watch is a fault, not a smaller chart."""
        _magic, _epoch, _lat, _lon, bodies_, stars, lines = pebble.HEADER.unpack_from(
            self.payload
        )
        self.assertEqual(
            len(self.payload),
            pebble.HEADER.size
            + bodies_ * pebble.BODY.size
            + stars * pebble.STAR.size
            + lines * pebble.LINE.size,
        )

    def test_the_header_has_no_padding_in_it(self):
        """The C reads these by offset, so no compiler's padding may creep in."""
        self.assertEqual(pebble.HEADER.size, 4 + 4 + 2 + 2 + 1 + 2 + 2)
        self.assertEqual(pebble.BODY.size, 2 + 2 + 1)
        self.assertEqual(pebble.STAR.size, 2 + 2)
        self.assertEqual(pebble.LINE.size, 2 + 2)

    def test_everything_is_little_endian(self):
        self.assertTrue(
            all(
                fmt.format.startswith("<")
                for fmt in (pebble.HEADER, pebble.BODY, pebble.STAR, pebble.LINE)
            )
        )

    def test_the_observer_survives(self):
        """
        To a hundredth of a degree, which is the format's resolution.

        That is about a kilometre on the ground, and moving a kilometre moves
        nothing in this chart that could be drawn.
        """
        self.assertAlmostEqual(self.read["latitude"], SEATTLE[0], delta=0.01)
        self.assertAlmostEqual(self.read["longitude"], SEATTLE[1], delta=0.01)
        self.assertEqual(self.read["generated"], self.when)

    def test_every_body_survives_with_its_name(self):
        self.assertEqual(
            [body["label"] for body in self.read["bodies"]],
            [body["label"] for body in self.model["bodies"]],
        )

    def test_positions_are_kept_to_well_inside_a_pixel(self):
        """
        A chart is about a pixel per degree, so a hundredth of a degree is
        invisible and anything finer is wasted payload.
        """
        for sent, got in zip(self.model["bodies"], self.read["bodies"], strict=True):
            with self.subTest(body=sent["label"]):
                self.assertAlmostEqual(sent["ra"], got["ra"], delta=0.01)
                self.assertAlmostEqual(sent["dec"], got["dec"], delta=0.01)

    def test_right_ascension_wraps_rather_than_overflowing(self):
        """359.999 degrees is a shade under a full turn, not a negative number."""
        self.assertEqual(pebble._ra(0.0), 0)
        self.assertEqual(pebble._ra(360.0), 0)
        self.assertGreater(pebble._ra(359.99), 65000)
        self.assertLess(pebble._ra(0.01), 10)

    def test_declination_reaches_both_poles_without_overflowing(self):
        self.assertLess(pebble._dec(90.0), 32768)
        self.assertGreater(pebble._dec(-90.0), -32769)
        self.assertEqual(pebble._dec(0.0), 0)

    def test_the_stick_figures_are_strung_together_without_losing_a_join(self):
        """
        Each constellation numbers its stars from zero and they all end up in one
        list, so a line that was not renumbered would join the wrong two stars --
        which draws something plausible rather than something obviously wrong.
        """
        self.assertEqual(
            len(self.read["stars"]),
            sum(len(c["stars"]) for c in self.model["constellations"]),
        )
        self.assertEqual(
            len(self.read["lines"]),
            sum(len(c["lines"]) for c in self.model["constellations"]),
        )
        for start, end in self.read["lines"]:
            self.assertLess(start, len(self.read["stars"]))
            self.assertLess(end, len(self.read["stars"]))

    def test_the_joins_point_at_the_same_stars_they_did(self):
        first, second = self.model["constellations"][:2]
        offset = len(first["stars"])
        self.assertEqual(
            self.read["lines"][len(first["lines"])],
            tuple(index + offset for index in second["lines"][0]),
        )

    def test_a_bad_version_is_refused_rather_than_drawn(self):
        wrong = bytes([*self.payload[:3], pebble.FORMAT_VERSION + 1]) + self.payload[4:]
        with self.assertRaises(ValueError):
            pebble.unpack(wrong)

    def test_something_else_entirely_is_refused(self):
        with self.assertRaises(ValueError):
            pebble.unpack(b"PNG\x01" + self.payload[4:])


class TestSize(unittest.TestCase):
    """It has to fit on the radio, which is the expensive part of the whole thing."""

    def test_the_usual_sky_fits_in_one_inbox(self):
        sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        sky.load()
        self.assertLess(len(pebble.pack(sky.sky_model())), APP_MESSAGE_BUDGET)

    def test_a_few_constellations_are_far_smaller(self):
        sky = bodies.Sky(SEATTLE, PACIFIC, constellation_list=["Orion", "UrsaMajor"])
        sky.load()
        self.assertLess(len(pebble.pack(sky.sky_model())), 512)


class TestChunking(unittest.TestCase):
    """Splitting a payload up, for an inbox that will not take it whole."""

    payload = bytes(range(256)) * 5

    def test_every_piece_says_where_it_goes(self):
        pieces = pebble.chunks(self.payload, size=100)
        for index, piece in enumerate(pieces):
            self.assertEqual(piece[0], index)
            self.assertEqual(piece[1], len(pieces))

    def test_the_pieces_put_back_together_are_the_original(self):
        pieces = pebble.chunks(self.payload, size=100)
        rebuilt = b"".join(piece[2:] for piece in sorted(pieces, key=lambda p: p[0]))
        self.assertEqual(rebuilt, self.payload)

    def test_order_does_not_matter(self):
        """Bluetooth does not promise to deliver them the way they were sent."""
        pieces = pebble.chunks(self.payload, size=100)
        self.assertGreater(len(pieces), 1)
        rebuilt = b"".join(
            piece[2:] for piece in sorted(reversed(pieces), key=lambda p: p[0])
        )
        self.assertEqual(rebuilt, self.payload)

    def test_no_piece_is_bigger_than_asked_for(self):
        for piece in pebble.chunks(self.payload, size=100):
            self.assertLessEqual(len(piece) - 2, 100)

    def test_a_short_payload_is_one_piece(self):
        self.assertEqual(len(pebble.chunks(b"tiny", size=100)), 1)


if __name__ == "__main__":
    unittest.main()
