"""
Paint the sky into a picture.

The chart is drawn as SVG everywhere it can be, because it stays sharp at any
size and weighs almost nothing. A picture is for the places that will not take
one: Home Assistant's camera entity, whose snapshot service writes the bytes
under whatever name it was asked for and whose consumers expect to be able to
resize what they are given, and anything else that wants pixels.

This is not a second drawing. :mod:`.scene` works out where everything goes and
:mod:`.styles` says what it looks like, both shared with :mod:`.svg`; all that
happens here is that the same shapes are painted rather than written down.

Pillow is the one thing this needs beyond the rest. Home Assistant already
installs it, so on the system this exists for it costs nothing, and it is a
plain wheel everywhere else -- which matplotlib, the reason any of this was
rewritten, was not. It is still only imported when a picture is actually asked
for, so drawing SVGs does not pay for it.
"""

import datetime
import io
import itertools
import math

from . import scene, styles
from .styles import STYLES

MISSING_PILLOW = (
    "drawing the chart as a picture needs Pillow, which is not installed. "
    "Either install it -- `pip install 'ha-skyfield[raster]'` -- or ask for the "
    "chart as SVG instead, which needs nothing extra."
)


def _pillow():
    """Pillow, or a complaint that says what to do about it."""
    try:
        import PIL.Image
        import PIL.ImageChops
        import PIL.ImageColor
        import PIL.ImageDraw
        import PIL.ImageFont
    except ImportError as missing:  # pragma: no cover - depends on the install
        raise RuntimeError(MISSING_PILLOW) from missing
    return PIL


# how many times over to draw before shrinking back down. Pillow draws no
# smoothing of its own, so the edges come from having more of them: a chart
# drawn at twice the size and halved has the stair steps averaged away. Beyond
# two the difference stops being visible and the memory does not.
SUPERSAMPLE = 2

# a sensible size for a dashboard card, and what the width defaults to
DEFAULT_WIDTH = 800

# Pillow ships a scalable font of its own, which saves hunting for one on a
# system that may have none at all -- a Home Assistant container often does not.
_FONTS: dict = {}


def render(
    model: dict,
    *,
    when: datetime.datetime | None = None,
    width: int = DEFAULT_WIDTH,
    theme: str = "light",
    palette: dict | None = None,
    background: str | None = None,
    title: str | None = None,
    image_format: str = "png",
    supersample: int = SUPERSAMPLE,
    north_up: bool | None = None,
    horizontal_flip: bool | None = None,
    show_legend: bool | None = None,
    show_time: bool | None = None,
    show_constellations: bool | None = None,
) -> bytes:
    """
    Draw a sky model as a picture, and return the encoded bytes.

    ``theme`` is ``light`` or ``dark`` -- there is no ``auto``, because a picture
    is painted once and cannot ask the person looking at it what they prefer.
    ``background`` defaults to the theme's own paper rather than to nothing:
    a transparent picture of a dark chart is unreadable on a dark page, which is
    exactly where it would end up.
    """
    if theme not in styles.PALETTES:
        raise ValueError(
            f"a picture needs a definite theme, one of "
            f"{tuple(styles.PALETTES)}, not {theme!r}"
        )

    colours = styles.palette(theme, palette)
    drawing = scene.build(
        model,
        when=when,
        title=title,
        north_up=north_up,
        horizontal_flip=horizontal_flip,
        show_legend=show_legend,
        show_time=show_time,
        show_constellations=show_constellations,
    )

    picture = _paint(
        drawing,
        colours,
        scale=width / drawing.width * supersample,
        background=background if background is not None else colours["paper"],
    )
    height = round(width * drawing.height / drawing.width)
    picture = picture.resize((width, height), _resample())

    return _encode(picture, image_format)


def _resample():
    return _pillow().Image.LANCZOS


def _paint(drawing, colours: dict, scale: float, background: str):
    PIL = _pillow()
    Image, ImageChops, ImageDraw = PIL.Image, PIL.ImageChops, PIL.ImageDraw

    size = (
        max(1, round(drawing.width * scale)),
        max(1, round(drawing.height * scale)),
    )
    base = Image.new("RGBA", size, _colour(background))

    # everything inside the horizon is drawn together and cut to it once, the
    # same way the SVG puts one clip path around the lot
    clipped = Image.new("RGBA", size, (0, 0, 0, 0))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).ellipse(
        _box(drawing.clip.x, drawing.clip.y + drawing.top, drawing.clip.radius, scale),
        fill=255,
    )

    for group in drawing.chart:
        _group(clipped if group.clipped else base, group, colours, scale, drawing.top)
    for group in drawing.page:
        _group(base, group, colours, scale, 0)

    clipped.putalpha(ImageChops.multiply(clipped.getchannel("A"), mask))
    base.alpha_composite(clipped)
    return base


def _group(target, group, colours: dict, scale: float, offset: float):
    """
    Paint one group, faded as a whole if it is meant to be.

    As a whole matters: the constellation joins are faint, and fading each line
    on its own would darken every place two of them cross. So a group that is
    not fully opaque is painted solid onto a layer of its own and that layer is
    faded, which is what the SVG gets for free by putting them in one element.
    """
    Image = _pillow().Image

    style = STYLES[group.style]
    if style.opacity < 1:
        layer = Image.new("RGBA", target.size, (0, 0, 0, 0))
        _items(layer, group, colours, scale, offset)
        alpha = layer.getchannel("A").point(lambda value: round(value * style.opacity))
        layer.putalpha(alpha)
        target.alpha_composite(layer)
    else:
        _items(target, group, colours, scale, offset)


def _items(target, group, colours: dict, scale: float, offset: float):
    draw = _pillow().ImageDraw.Draw(target)
    for item in group.items:
        style = STYLES[getattr(item, "style", None) or group.style]
        if isinstance(item, scene.Circle):
            _circle(draw, item, style, colours, scale, offset)
        elif isinstance(item, scene.Line):
            draw.line(
                _points([(item.x1, item.y1), (item.x2, item.y2)], scale, offset),
                fill=_colour(colours[style.stroke]),
                width=_width(style.width, scale),
            )
        elif isinstance(item, scene.Polyline):
            _polyline(draw, item, group, style, colours, scale, offset)
        elif isinstance(item, scene.Dot):
            # a zero-length line with a round cap is a dot, so the width the SVG
            # strokes it with is a diameter here
            radius = style.width / 2
            draw.ellipse(
                _box(item.x, item.y + offset, radius, scale),
                fill=_colour(colours[style.stroke]),
            )
        elif isinstance(item, scene.Label):
            draw.text(
                ((item.x) * scale, (item.y + offset) * scale),
                item.text,
                font=_font(style.font_size * scale),
                fill=_colour(colours[style.fill]),
                anchor="lm" if style.anchor == "start" else "mm",
            )
        else:
            raise TypeError(f"nothing here knows how to paint {item!r}")


def _circle(draw, item, style, colours: dict, scale: float, offset: float):
    box = _box(item.x, item.y + offset, item.radius, scale)
    outline = _colour(colours[style.stroke]) if style.stroke else None
    draw.ellipse(
        box,
        fill=_colour(item.fill) if item.fill else None,
        outline=outline,
        width=_width(style.width, scale),
    )


def _polyline(draw, item, group, style, colours: dict, scale: float, offset: float):
    runs = (
        _dashed(item.points, styles.DASHES)
        if getattr(group, "dashed", False)
        else [item.points]
    )
    for run in runs:
        if len(run) < 2:
            continue
        draw.line(
            _points(run, scale, offset),
            fill=_colour(colours[style.stroke]),
            width=_width(style.width, scale),
            joint="curve",
        )


def _dashed(points: list, pattern: tuple) -> list:
    """
    Cut a line into dashes, since Pillow draws only solid ones.

    Walks the line keeping track of how far along it is, and switches between
    drawing and not at the lengths the pattern gives -- which is what a
    stroke-dasharray means, so the SVG and the picture break in the same places.
    """
    on, off = pattern
    runs = []
    run = [points[0]]
    drawing = True
    left = on

    for start, end in itertools.pairwise(points):
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        travelled = 0.0
        while length - travelled > left:
            travelled += left
            along = travelled / length
            at = (
                start[0] + (end[0] - start[0]) * along,
                start[1] + (end[1] - start[1]) * along,
            )
            if drawing:
                run.append(at)
                runs.append(run)
                run = []
            else:
                run = [at]
            drawing = not drawing
            left = on if drawing else off
        left -= length - travelled
        if drawing:
            run.append(end)

    if drawing and len(run) > 1:
        runs.append(run)
    return runs


def _points(points, scale: float, offset: float) -> list:
    return [(x * scale, (y + offset) * scale) for x, y in points]


def _box(x: float, y: float, radius: float, scale: float) -> list:
    return [
        (x - radius) * scale,
        (y - radius) * scale,
        (x + radius) * scale,
        (y + radius) * scale,
    ]


def _width(width: float, scale: float) -> int:
    """A stroke is at least a pixel; below that Pillow draws nothing at all."""
    return max(1, round(width * scale))


def _colour(value: str):
    return _pillow().ImageColor.getrgb(value)


def _font(size: float):
    rounded = max(1, round(size))
    if rounded not in _FONTS:
        _FONTS[rounded] = _pillow().ImageFont.load_default(size=rounded)
    return _FONTS[rounded]


def _encode(picture, image_format: str) -> bytes:
    image_format = image_format.lower()
    if image_format in ("jpg", "jpeg"):
        # a chart is fine lines on flat colour, which is the worst thing to hand
        # a discrete cosine transform, so this exists only for somebody who has
        # asked for it by name
        picture = picture.convert("RGB")
        out = io.BytesIO()
        picture.save(out, format="JPEG", quality=92, subsampling=0)
        return out.getvalue()
    if image_format != "png":
        raise ValueError(f"a picture can be png or jpeg, not {image_format!r}")

    out = io.BytesIO()
    picture.save(out, format="PNG", optimize=True)
    return out.getvalue()
