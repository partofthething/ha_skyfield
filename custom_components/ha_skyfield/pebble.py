"""
Pack the sky small enough to send to a watch.

A Pebble is a small battery on a wrist, and the expensive thing on it by a long
way is the radio. Working out where a hundred-odd objects are costs a few
milliseconds of a 64 MHz processor once a minute -- a twenty-thousandth of the
time, and nothing at all next to keeping Bluetooth awake for a second.

So this sends sky coordinates rather than points on the watch's screen. Screen
coordinates would be a little smaller and would save the watch some arithmetic,
but they go stale: the chart is about a pixel per degree of altitude and the sky
turns fifteen degrees an hour, so they would have to be fetched again every few
minutes, all day. Right ascension and declination do not go stale. The watch can
fetch twice a day, work the rest out from its own clock, and go on being right
while the phone is in another room.

The format is deliberately dull -- fixed-width little-endian fields, no floats,
no strings -- because the other end of it is C on a microcontroller. See
``pebble/src/c/sky.c`` for the reader.
"""

import datetime
import struct

from .bodies import BODIES

# bumped if the layout below changes, so an old watch app can say so rather than
# drawing nonsense
FORMAT_VERSION = 1
MAGIC = b"SKY" + bytes([FORMAT_VERSION])

# "<" throughout: little-endian, and no padding inserted between fields
HEADER = struct.Struct("<4sIhhBHH")
BODY = struct.Struct("<HhB")
STAR = struct.Struct("<Hh")
LINE = struct.Struct("<HH")

# Angles are sent as the watch's own. A Pebble measures a full turn in 65536
# steps -- ``TRIG_MAX_ANGLE`` -- and its sin_lookup and cos_lookup take angles in
# those units, so scaling to them here means the C can feed what arrives on the
# wire straight into the trigonometry without converting anything. Right
# ascension goes all the way round and uses the whole unsigned range;
# declination reaches a quarter turn either way, which is 16384 of them.
TRIG_MAX_ANGLE = 65536
RA_SCALE = TRIG_MAX_ANGLE / 360
DEC_SCALE = TRIG_MAX_ANGLE / 4 / 90
DEGREE_SCALE = 100

# a step of either is 360/65536 of a turn, about a two-hundredth of a degree,
# which is a fiftieth of a pixel on a watch


# How much to put in one AppMessage. Modern firmware will accept a good deal
# more, but the inbox is negotiated at runtime and there is no way to know from
# here what the watch on the other end agreed to, so this stays conservative and
# the reassembly costs the watch one buffer.
CHUNK_SIZE = 512


def pack(model: dict, *, when: datetime.datetime | None = None) -> bytes:
    """
    Pack a sky model into the bytes a watch face reads.

    Bodies are sent as their position in :data:`bodies.BODIES` rather than with a
    colour and a size, since the watch has its own opinion about both -- it is
    drawing on a screen a fifth of the size, in as few colours as sixteen -- and
    a byte is cheaper than either.
    """
    if when is None:
        when = datetime.datetime.fromisoformat(model["generated"])

    order = {label: index for index, (label, *_rest) in enumerate(BODIES)}

    bodies = b"".join(
        BODY.pack(_ra(body["ra"]), _dec(body["dec"]), order[body["label"]])
        for body in model.get("bodies", [])
        if body["label"] in order
    )

    stars, lines = _stick_figures(model.get("constellations", []))

    header = HEADER.pack(
        MAGIC,
        int(when.timestamp()),
        round(model["latitude"] * DEGREE_SCALE),
        round(model["longitude"] * DEGREE_SCALE),
        len(bodies) // BODY.size,
        len(stars) // STAR.size,
        len(lines) // LINE.size,
    )
    return header + bodies + stars + lines


def _stick_figures(constellations: list) -> tuple[bytes, bytes]:
    """
    Flatten every constellation into one run of stars and one of lines.

    Each constellation numbers its own stars from zero, so the joins have to be
    renumbered as the figures are strung together. The watch neither knows nor
    cares which figure a star belonged to; it draws the lot.
    """
    stars = []
    lines = []
    first = 0

    for constellation in constellations:
        positions = constellation["stars"]
        for ra, dec in positions:
            stars.append(STAR.pack(_ra(ra), _dec(dec)))
        for start, end in constellation["lines"]:
            lines.append(LINE.pack(first + start, first + end))
        first += len(positions)

    return b"".join(stars), b"".join(lines)


def _ra(degrees: float) -> int:
    """Right ascension, as the watch's own angle."""
    return round(degrees % 360 * RA_SCALE) % TRIG_MAX_ANGLE


def _dec(degrees: float) -> int:
    """Declination, as the watch's own angle. A quarter turn either way."""
    quarter = TRIG_MAX_ANGLE // 4
    return max(-quarter, min(quarter, round(degrees * DEC_SCALE)))


def chunks(payload: bytes, size: int = CHUNK_SIZE) -> list[bytes]:
    """
    Cut a payload into pieces small enough to send, each saying where it goes.

    Two bytes go in front of every piece: which one it is, and how many there
    are. That is enough for the watch to lay them back out in a buffer without
    caring what order they turn up in.
    """
    body = [payload[at : at + size] for at in range(0, len(payload), size)]
    total = len(body)
    return [bytes([index, total]) + piece for index, piece in enumerate(body)]


def unpack(payload: bytes) -> dict:
    """
    Read a payload back. This exists so the tests can check the packing.

    Nothing in Home Assistant calls this; the real reader is the C on the watch,
    and keeping an independent one here is what makes it possible to prove the
    two agree about where the fields are.
    """
    magic, epoch, latitude, longitude, body_count, star_count, line_count = (
        HEADER.unpack_from(payload)
    )
    if magic[:3] != MAGIC[:3]:
        raise ValueError(f"not a sky payload: {magic!r}")
    if magic[3] != FORMAT_VERSION:
        raise ValueError(f"sky payload version {magic[3]}, expected {FORMAT_VERSION}")

    at = HEADER.size
    bodies = []
    for _ in range(body_count):
        ra, dec, index = BODY.unpack_from(payload, at)
        at += BODY.size
        bodies.append(
            {"label": BODIES[index][0], "ra": ra / RA_SCALE, "dec": dec / DEC_SCALE}
        )

    stars = []
    for _ in range(star_count):
        ra, dec = STAR.unpack_from(payload, at)
        at += STAR.size
        stars.append((ra / RA_SCALE, dec / DEC_SCALE))

    lines = []
    for _ in range(line_count):
        lines.append(LINE.unpack_from(payload, at))
        at += LINE.size

    return {
        "generated": datetime.datetime.fromtimestamp(epoch, datetime.UTC),
        "latitude": latitude / DEGREE_SCALE,
        "longitude": longitude / DEGREE_SCALE,
        "bodies": bodies,
        "stars": stars,
        "lines": lines,
    }
