"""Draw resources/images/menu_icon.png, the 25x25 icon the launcher shows.

Pixel art, drawn at final size with no antialiasing: a 25 pixel circle
downsampled from a larger one is a grey smudge once the watch has it in one
bit. White on transparent, which is what the launcher and the phone expect.

    python3 tools/make_menu_icon.py
"""

import pathlib

from PIL import Image, ImageDraw

SIZE = 25
WHITE = (255, 255, 255, 255)
HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "resources" / "images" / "menu_icon.png"


def cross(draw, x, y):
    """A star bright enough to have points, which one pixel cannot show."""
    draw.point([(x, y), (x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)], fill=WHITE)


def main():
    image = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # the horizon, a circle inscribed in the square with a pixel of margin
    draw.ellipse([1, 1, SIZE - 2, SIZE - 2], outline=WHITE, width=1)

    # the Sun, low in the west
    draw.ellipse([5, 12, 10, 17], fill=WHITE)

    cross(draw, 15, 7)
    cross(draw, 14, 16)
    for x, y in [(9, 6), (18, 11), (12, 11), (19, 15), (11, 19), (7, 9), (17, 19)]:
        draw.point((x, y), fill=WHITE)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
