"""
Draw the sky from a command line.

    skyfield-sky svg --lat 47.6 --lon -122.3 --tz America/Los_Angeles -o sky.svg

Everything here works without Home Assistant. The first run downloads an
ephemeris of about seventeen megabytes and keeps it in a cache directory, so it
is only slow once.
"""

import argparse
import datetime
import json
import logging
import sys
import time

from . import pebble, raster, server, svg
from .bodies import Sky

_LOGGER = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300


def main(argv=None) -> int:
    """Run one command. Returns what the process should exit with."""
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    try:
        return args.run(args)
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as trouble:
        parser.exit(2, f"{parser.prog}: {trouble}\n")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skyfield-sky",
        description="Draw a polar chart of the Sun, Moon, planets and constellations.",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="say more")
    commands = parser.add_subparsers(dest="command", required=True)

    where = argparse.ArgumentParser(add_help=False)
    where.add_argument(
        "--lat", type=float, required=True, help="latitude, degrees north"
    )
    where.add_argument(
        "--lon", type=float, required=True, help="longitude, degrees east"
    )
    where.add_argument(
        "--tz",
        default="UTC",
        help="the observer's own time zone, such as America/Los_Angeles",
    )
    where.add_argument(
        "--data-dir",
        default=None,
        help=f"where to keep the ephemeris (default {server.data_directory()})",
    )
    where.add_argument(
        "--no-constellations", dest="constellations", action="store_false"
    )
    where.add_argument(
        "--constellations",
        dest="constellation_list",
        type=_names,
        help="comma-separated names, instead of the usual set",
    )
    where.add_argument(
        "--planets", type=_names, help="comma-separated names, instead of all of them"
    )
    where.add_argument("--north-up", action="store_true", help="put north at the top")
    where.add_argument(
        "--flip", action="store_true", help="mirror it, for a chart to hold up"
    )
    where.add_argument(
        "--when",
        type=_moment,
        help="a moment, in ISO format; the observer's zone if it says none",
    )

    drawing = argparse.ArgumentParser(add_help=False)
    drawing.add_argument("-o", "--output", help="a file to write, or stdout")
    drawing.add_argument(
        "--theme", choices=svg.THEMES, default="auto", help="which colours to use"
    )
    drawing.add_argument("--title", help="a heading above the chart")
    drawing.add_argument("--background", help="a colour to fill behind it")
    drawing.add_argument("--no-legend", dest="legend", action="store_false")
    drawing.add_argument("--no-time", dest="timestamp", action="store_false")

    draw = commands.add_parser(
        "svg", parents=[where, drawing], help="draw the sky as an SVG file"
    )
    draw.set_defaults(run=_svg)

    picture = commands.add_parser(
        "png", parents=[where, drawing], help="paint the sky as a picture"
    )
    picture.add_argument(
        "--width", type=int, default=raster.DEFAULT_WIDTH, help="in pixels"
    )
    picture.add_argument(
        "--format", dest="image_format", choices=("png", "jpeg"), default="png"
    )
    picture.set_defaults(run=_png)

    describe = commands.add_parser(
        "json", parents=[where], help="print the sky as data, the way the card gets it"
    )
    describe.add_argument("-o", "--output")
    describe.set_defaults(run=_json)

    watch = commands.add_parser(
        "pebble", parents=[where], help="pack the sky for a Pebble watch face"
    )
    watch.add_argument("-o", "--output")
    watch.add_argument(
        "--json", action="store_true", help="describe the payload instead of packing it"
    )
    watch.set_defaults(run=_pebble)

    serving = commands.add_parser(
        "serve", parents=[where], help="serve the sky over HTTP"
    )
    serving.add_argument("--host", default="127.0.0.1")
    serving.add_argument("--port", type=int, default=8099)
    serving.add_argument("--theme", choices=svg.THEMES, default="auto")
    serving.add_argument("--title")
    serving.set_defaults(run=_serve)

    keeping = commands.add_parser(
        "watch",
        parents=[where, drawing],
        help="redraw a file every so often, for a web server to hand out",
    )
    keeping.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL,
        help=f"seconds between redraws (default {DEFAULT_INTERVAL})",
    )
    keeping.set_defaults(run=_keep_drawing)

    return parser


def _names(raw: str) -> list:
    return [name.strip() for name in raw.split(",") if name.strip()]


def _moment(raw: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(raw)


def _sky(args) -> Sky:
    """Build and load the sky the arguments describe."""
    sky = Sky(
        (args.lat, args.lon),
        args.tz,
        show_constellations=args.constellations,
        show_time=getattr(args, "timestamp", True),
        show_legend=getattr(args, "legend", True),
        constellation_list=args.constellation_list,
        planet_list=args.planets,
        north_up=args.north_up,
        horizontal_flip=args.flip,
    )
    sky.load(args.data_dir or str(server.data_directory()))
    return sky


def _write(args, content, binary=False):
    """Write to the named file, or to stdout when there is none."""
    if args.output is None:
        if binary:
            sys.stdout.buffer.write(content)
        else:
            sys.stdout.write(content)
        return
    with open(args.output, "wb" if binary else "w") as out:
        out.write(content)


def _draw(sky: Sky, args) -> str:
    return svg.render(
        sky.sky_model(args.when),
        theme=args.theme,
        title=args.title,
        background=args.background,
    )


def _svg(args) -> int:
    _write(args, _draw(_sky(args), args))
    return 0


def _png(args) -> int:
    """
    Paint the sky rather than writing it out.

    A picture cannot ask the reader which colours they prefer, so `auto` is not
    one of the choices here; left alone it draws the light one.
    """
    theme = "light" if args.theme == "auto" else args.theme
    _write(
        args,
        raster.render(
            _sky(args).sky_model(args.when),
            width=args.width,
            theme=theme,
            title=args.title,
            background=args.background,
            image_format=args.image_format,
        ),
        binary=True,
    )
    return 0


def _json(args) -> int:
    _write(args, json.dumps(_sky(args).sky_model(args.when), indent=2) + "\n")
    return 0


def _pebble(args) -> int:
    model = _sky(args).sky_model(args.when)
    if args.json:
        payload = pebble.unpack(pebble.pack(model))
        payload["generated"] = payload["generated"].isoformat()
        _write(args, json.dumps(payload, indent=2, default=list) + "\n")
    else:
        _write(args, pebble.pack(model), binary=True)
    return 0


def _serve(args) -> int:
    httpd = server.serve(
        args.lat,
        args.lon,
        args.tz,
        host=args.host,
        port=args.port,
        directory=args.data_dir,
        show_constellations=args.constellations,
        constellations=args.constellation_list,
        planets=args.planets,
        north_up=args.north_up,
        horizontal_flip=args.flip,
        theme=args.theme,
        title=args.title,
    )
    host, port = httpd.server_address[:2]
    _LOGGER.info("Serving the sky on http://%s:%s/", host, port)
    with httpd:
        httpd.serve_forever()
    return 0


def _keep_drawing(args) -> int:
    """
    Redraw a file for as long as this runs.

    For a web page, this is usually a better answer than a server: the file is
    handed out by whatever already serves the site, and there is no Python in the
    way of a reader.
    """
    if args.output is None:
        raise ValueError("redrawing on a timer needs a file to write; pass -o")

    sky = _sky(args)
    while True:
        _write(args, _draw(sky, args))
        _LOGGER.debug("Drew %s", args.output)
        time.sleep(args.interval)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
