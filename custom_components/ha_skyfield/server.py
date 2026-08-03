"""
A small web server that draws the sky.

Enough to put a live chart on a web page or to feed a watch face, and no more:
the standard library's own HTTP server, no framework, no dependencies beyond
what drawing the chart already needs.

The work worth avoiding here is not the drawing, which is milliseconds, but the
setting up. A :class:`bodies.Sky` downloads a seventeen-megabyte ephemeris the
first time and then spends a while working out the Sun's paths and the
constellations, so they are made once per set of options and kept.
"""

import json
import logging
import os
import pathlib
import threading
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import pebble, svg
from .bodies import Sky

_LOGGER = logging.getLogger(__name__)

# how many differently-configured skies to keep set up at once
CACHE_SIZE = 8

# the chart is redrawn from the same model for ten minutes, which is how often
# the card asks for a fresh one
CACHE_SECONDS = 600

BOOLEAN_TRUE = frozenset({"1", "true", "yes", "on"})
BOOLEAN_FALSE = frozenset({"0", "false", "no", "off"})


def data_directory() -> pathlib.Path:
    """Where to keep the ephemeris, following the usual place for a cache."""
    root = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return pathlib.Path(root) / "ha_skyfield"


class SkyCache:
    """
    Skies, kept so that setting one up is paid for once.

    A lock rather than one per sky: they are only held for as long as it takes to
    describe a sky, the whole point of a cache here is that there are few of
    them, and a home web server is not fielding enough at once for the difference
    to be measurable.
    """

    def __init__(self, directory=None, size=CACHE_SIZE):
        self._directory = str(directory or data_directory())
        self._size = size
        self._skies = OrderedDict()
        self._lock = threading.Lock()

    def model(self, options: dict) -> dict:
        """Describe the sky for one set of options."""
        with self._lock:
            return self._sky(options).sky_model()

    def _sky(self, options: dict) -> Sky:
        key = json.dumps(options, sort_keys=True, default=list)
        if key in self._skies:
            self._skies.move_to_end(key)
            return self._skies[key]

        _LOGGER.info("Setting up a sky for %s", key)
        sky = Sky(
            (options["latitude"], options["longitude"]),
            options["timezone"],
            show_constellations=options["show_constellations"],
            show_time=options["show_time"],
            show_legend=options["show_legend"],
            constellation_list=options["constellations"],
            planet_list=options["planets"],
            north_up=options["north_up"],
            horizontal_flip=options["horizontal_flip"],
        )
        sky.load(self._directory)

        self._skies[key] = sky
        if len(self._skies) > self._size:
            self._skies.popitem(last=False)
        return sky


# the short spellings are the ones the command line uses, and the ones anybody
# typing a URL by hand reaches for first
ALIASES = {
    "lat": "latitude",
    "lon": "longitude",
    "tz": "timezone",
    "flip": "horizontal_flip",
}

NUMBERS = ("latitude", "longitude")
WORDS = ("timezone", "theme", "title")
FLAGS = (
    "show_constellations",
    "show_time",
    "show_legend",
    "north_up",
    "horizontal_flip",
)
LISTS = ("constellations", "planets")


def options_from_query(query: dict, defaults: dict) -> dict:
    """
    Read chart options off a query string, falling back to the server's own.

    Anything the caller did not ask about keeps the value the server was started
    with, so a bare ``/sky.svg`` draws the sky the server is for. A parameter
    that means nothing here is refused rather than ignored, because a chart drawn
    for silently the wrong place looks perfectly convincing.
    """
    options = dict(defaults)
    asked = {ALIASES.get(name, name): values for name, values in query.items()}

    unknown = set(asked) - set(NUMBERS) - set(WORDS) - set(FLAGS) - set(LISTS)
    # a cache-busting parameter is the one thing that is meant to be ignored
    unknown.discard("t")
    if unknown:
        raise ValueError(f"no such option: {', '.join(sorted(unknown))}")

    for name in NUMBERS:
        if name in asked:
            try:
                options[name] = float(asked[name][0])
            except ValueError:
                raise ValueError(
                    f"{name} should be a number, not {asked[name][0]!r}"
                ) from None
    for name in WORDS:
        if name in asked:
            options[name] = asked[name][0]
    for name in FLAGS:
        if name in asked:
            options[name] = _boolean(name, asked[name][0])
    for name in LISTS:
        if name in asked:
            # comma separated, since a repeated parameter is fiddlier to write
            # by hand and this is a URL somebody may well be typing
            options[name] = [
                part.strip() for part in asked[name][0].split(",") if part.strip()
            ]
    return options


def _boolean(name: str, raw: str) -> bool:
    lowered = raw.strip().lower()
    if lowered in BOOLEAN_TRUE:
        return True
    if lowered in BOOLEAN_FALSE:
        return False
    raise ValueError(f"{name} should be true or false, not {raw!r}")


def default_options(latitude: float, longitude: float, timezone: str) -> dict:
    """The full set of options, so that a query string only has to differ."""
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": timezone,
        "show_constellations": True,
        "show_time": True,
        "show_legend": True,
        "north_up": False,
        "horizontal_flip": False,
        "constellations": None,
        "planets": None,
        "theme": "auto",
        "title": None,
    }


# options the chart is drawn with rather than computed with; they must not reach
# the Sky, which would otherwise be set up again for every change of colour
DRAWING_OPTIONS = ("theme", "title")


class SkyHandler(BaseHTTPRequestHandler):
    """Answers for one sky, drawn however the query string asks."""

    server_version = "skyfield"

    # set on the class by :func:`serve`
    cache: SkyCache
    defaults: dict

    def do_GET(self):
        route = urlparse(self.path)
        query = parse_qs(route.query)

        try:
            options = options_from_query(query, self.defaults)
        except ValueError as bad:
            self._send(400, "text/plain; charset=utf-8", str(bad).encode())
            return

        try:
            handler = {
                "/": self._index,
                "/sky.svg": self._svg,
                "/sky.json": self._json,
                "/sky.pebble": self._pebble,
            }[route.path]
        except KeyError:
            self._send(404, "text/plain; charset=utf-8", b"no such thing here\n")
            return

        try:
            handler(options)
        except Exception:
            _LOGGER.exception("Could not draw the sky")
            self._send(500, "text/plain; charset=utf-8", b"could not draw the sky\n")

    def _model(self, options: dict) -> dict:
        return self.cache.model(
            {k: v for k, v in options.items() if k not in DRAWING_OPTIONS}
        )

    def _svg(self, options):
        drawing = svg.render(
            self._model(options), theme=options["theme"], title=options["title"]
        )
        self._send(200, "image/svg+xml; charset=utf-8", drawing.encode())

    def _json(self, options):
        body = json.dumps(self._model(options)).encode()
        self._send(200, "application/json; charset=utf-8", body)

    def _pebble(self, options):
        payload = pebble.pack(self._model(options))
        self._send(200, "application/octet-stream", payload)

    def _index(self, options):
        self._send(200, "text/html; charset=utf-8", INDEX)

    def _send(self, status: int, content_type: str, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if status == 200:
            self.send_header("Cache-Control", f"max-age={CACHE_SECONDS}")
            # a watch face on someone else's page, or a chart on a static site,
            # is the ordinary use rather than the exception
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        _LOGGER.info("%s %s", self.address_string(), format % args)


INDEX = b"""<!doctype html>
<meta charset="utf-8">
<title>Sky</title>
<style>
  body { margin: 0; display: grid; place-items: center; min-height: 100vh;
         background: #fff; color: #212121;
         font-family: system-ui, sans-serif; }
  img { width: min(90vw, 90vh); }
  @media (prefers-color-scheme: dark) { body { background: #101318; color: #e3e3e3; } }
</style>
<img src="/sky.svg" alt="Chart of the sky">
<script>
  // the sky turns a degree every four minutes, so this is smoother than an eye
  // can follow; the cache buster is what stops the browser showing a stale one
  setInterval(() => {
    document.querySelector("img").src = "/sky.svg?t=" + Date.now();
  }, 60000);
</script>
"""


def serve(
    latitude: float,
    longitude: float,
    timezone: str,
    host: str = "127.0.0.1",
    port: int = 8099,
    directory=None,
    **overrides,
) -> ThreadingHTTPServer:
    """
    Build a server drawing the sky above one place.

    Returned rather than run, so that a caller can decide whether to serve
    forever or to serve on a thread and get on with something else -- which is
    what the tests do.
    """
    defaults = default_options(latitude, longitude, timezone)
    defaults.update({k: v for k, v in overrides.items() if v is not None})

    handler = type(
        "BoundSkyHandler",
        (SkyHandler,),
        {"cache": SkyCache(directory), "defaults": defaults},
    )
    return ThreadingHTTPServer((host, port), handler)
