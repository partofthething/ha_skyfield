"""
The watch face's payload parser, compiled here and fed what Python packs.

``ha_skyfield.pebble`` writes the bytes and ``pebble/src/c/sky_data.c`` reads
them. They are in different languages, in different directories, and only one of
them runs anywhere anybody can look at it, so this puts the two together.

Needs a C compiler, and skips itself without one.
"""

import datetime
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from zoneinfo import ZoneInfo

from ha_skyfield import bodies, pebble

HERE = pathlib.Path(__file__).parent
WATCHFACE = HERE.parent.parent / "pebble" / "src" / "c"

CC = shutil.which("cc") or shutil.which("gcc")

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"


def c_constant(name, header="sky_data.h"):
    """Read a #define out of the watch face's headers."""
    source = (WATCHFACE / header).read_text()
    found = re.search(rf"^#define {name} (\d+)", source, flags=re.MULTILINE)
    if found is None:
        raise AssertionError(f"{name} is no longer defined in {header}")
    return int(found.group(1))


class TestConstantsMatch(unittest.TestCase):
    """
    The numbers written down on both sides of the wire.

    These need no compiler, so they run everywhere and catch the mistake that is
    easiest to make: changing one side of a shared constant.
    """

    def test_the_format_version_agrees(self):
        self.assertEqual(c_constant("SKY_FORMAT_VERSION"), pebble.FORMAT_VERSION)

    def test_the_field_sizes_agree(self):
        self.assertEqual(c_constant("SKY_HEADER_SIZE"), pebble.HEADER.size)
        self.assertEqual(c_constant("SKY_BODY_SIZE"), pebble.BODY.size)
        self.assertEqual(c_constant("SKY_STAR_SIZE"), pebble.STAR.size)
        self.assertEqual(c_constant("SKY_LINE_SIZE"), pebble.LINE.size)

    def test_the_chunk_size_agrees(self):
        """A different one on each side puts every piece at the wrong offset."""
        self.assertEqual(c_constant("SKY_CHUNK_SIZE"), pebble.CHUNK_SIZE)

    def test_the_watch_has_room_for_the_usual_sky(self):
        sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        sky.load()
        self.assertLess(
            len(pebble.pack(sky.sky_model())), c_constant("SKY_MAX_PAYLOAD")
        )

    def test_the_body_table_is_the_same_length(self):
        self.assertEqual(c_constant("SKY_BODY_COUNT"), len(bodies.BODIES))

    def test_the_body_table_is_in_the_same_order(self):
        """
        The payload sends a body's position in the table instead of its name.

        A table in a different order would draw Neptune's colour on Mercury,
        which is wrong in a way nobody would spot.
        """
        source = (WATCHFACE / "sky_data.c").read_text()
        table = source[source.index("SKY_BODIES[") :]
        names = re.findall(r'\{"(\w+)",', table)
        self.assertEqual(names, [label for label, *_rest in bodies.BODIES])


@unittest.skipUnless(CC, "checking the watch face needs a C compiler")
class TestTheWatchReadsWhatPythonWrites(unittest.TestCase):
    """The parser, compiled and run."""

    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.mkdtemp(prefix="skyfield-parser-")
        cls.probe = pathlib.Path(cls.build) / "parse"
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
                str(HERE / "host_parse.c"),
                str(WATCHFACE / "sky_data.c"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if compiled.returncode != 0:
            raise AssertionError(f"the parser did not compile:\n{compiled.stderr}")

        cls.when = datetime.datetime(2026, 8, 2, 22, 30, tzinfo=ZoneInfo(PACIFIC))
        sky = bodies.Sky(SEATTLE, PACIFIC, show_constellations=True)
        sky.load()
        cls.model = sky.sky_model(cls.when)
        cls.payload = pebble.pack(cls.model)
        cls.read = cls._parse(cls.payload)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.build, ignore_errors=True)

    @classmethod
    def _parse(cls, payload):
        finished = subprocess.run(
            [str(cls.probe)], input=payload, capture_output=True, timeout=60, check=True
        )
        return finished.stdout.decode().strip().splitlines()

    def _rows(self, kind):
        return [
            [int(field) for field in line.split()[1:3]]
            for line in self.read
            if line.startswith(kind + " ")
        ]

    def test_it_accepted_the_payload(self):
        self.assertTrue(self.read[0].startswith("accepted"), self.read[0])

    def test_the_header_reads_the_same(self):
        _word, generated, latitude, longitude, count, stars, lines = self.read[
            0
        ].split()
        ours = pebble.unpack(self.payload)
        self.assertEqual(int(generated), int(self.when.timestamp()))
        self.assertEqual(int(latitude) / 100, ours["latitude"])
        self.assertEqual(int(longitude) / 100, ours["longitude"])
        self.assertEqual(int(count), len(ours["bodies"]))
        self.assertEqual(int(stars), len(ours["stars"]))
        self.assertEqual(int(lines), len(ours["lines"]))

    def test_every_body_reads_the_same(self):
        expected = [
            [pebble._ra(body["ra"]), pebble._dec(body["dec"])]
            for body in self.model["bodies"]
        ]
        self.assertEqual(self._rows("body"), expected)

    def test_the_bodies_come_out_with_the_right_names(self):
        """The wire sends a table position, so this is the table agreeing."""
        names = [line.split()[4] for line in self.read if line.startswith("body ")]
        self.assertEqual(names, [body["label"] for body in self.model["bodies"]])

    def test_every_star_reads_the_same(self):
        expected = [
            [pebble._ra(ra), pebble._dec(dec)]
            for constellation in self.model["constellations"]
            for ra, dec in constellation["stars"]
        ]
        self.assertEqual(self._rows("star"), expected)

    def test_every_join_reads_the_same(self):
        self.assertEqual(
            [tuple(row) for row in self._rows("line")],
            [tuple(line) for line in pebble.unpack(self.payload)["lines"]],
        )

    def test_a_truncated_payload_is_refused_rather_than_read_off_the_end(self):
        """
        The counts in the header have to account for exactly what arrived.

        A short payload trusted at its word would have the parser reading past
        the buffer, which on a watch is a crash at best.
        """
        self.assertEqual(self._parse(self.payload[:-4])[0], "rejected")

    def test_a_payload_claiming_more_than_it_carries_is_refused(self):
        lying = bytearray(self.payload)
        lying[13:15] = (9999).to_bytes(2, "little")  # the star count
        self.assertEqual(self._parse(bytes(lying))[0], "rejected")

    def test_a_join_pointing_at_no_star_is_refused(self):
        """A stick figure drawn from a wild index joins two arbitrary points."""
        ours = pebble.unpack(self.payload)
        # the joins are no longer at the end of the payload; the paths are
        at = (
            pebble.HEADER.size
            + len(ours["bodies"]) * pebble.BODY.size
            + len(ours["stars"]) * pebble.STAR.size
            + (len(ours["lines"]) - 1) * pebble.LINE.size
        )
        lying = bytearray(self.payload)
        lying[at : at + 2] = (9999).to_bytes(2, "little")
        self.assertEqual(self._parse(bytes(lying))[0], "rejected")

    def test_the_suns_paths_read_the_same(self):
        """
        The curves the chart is really for.

        These arrive as azimuth and altitude rather than sky coordinates, so the
        watch draws them without rotating anything -- which also means a mistake
        here shows up as a line in the wrong place rather than as nothing.
        """
        ours = pebble.unpack(self.payload)
        theirs = [
            [int(field) for field in line.split()[1:]]
            for line in self.read
            if line.startswith("path ")
        ]
        expected = []
        for index, path in enumerate(ours["paths"]):
            for azimuth, altitude in path["points"]:
                expected.append(
                    [
                        index,
                        pebble.PATH_KINDS[path["name"]],
                        pebble._ra(azimuth),
                        pebble._dec(altitude),
                    ]
                )
        self.assertEqual(theirs, expected)

    def test_there_is_a_path_for_each_of_the_suns_curves(self):
        kinds = sorted(
            {int(line.split()[2]) for line in self.read if line.startswith("path ")}
        )
        self.assertEqual(kinds, sorted(pebble.PATH_KINDS.values()))

    def test_a_payload_claiming_more_paths_than_it_carries_is_refused(self):
        lying = bytearray(self.payload)
        lying[17] = pebble.PATH_KINDS.__len__() + 1  # the path count
        self.assertEqual(self._parse(bytes(lying))[0], "rejected")

    def test_the_wrong_version_is_refused(self):
        wrong = bytearray(self.payload)
        wrong[3] = pebble.FORMAT_VERSION + 1
        self.assertEqual(self._parse(bytes(wrong))[0], "rejected")

    def test_something_else_entirely_is_refused(self):
        self.assertEqual(self._parse(b"hello, this is not a sky")[0], "rejected")

    def test_nothing_at_all_is_refused(self):
        self.assertEqual(self._parse(b"")[0], "rejected")


if __name__ == "__main__":
    unittest.main()
