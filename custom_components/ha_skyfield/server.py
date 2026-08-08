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

from . import pebble, raster, svg
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
# a coordinate outside these is a typo, and better said so than handed to an
# ephemeris to produce something confident and wrong
LIMITS = {"latitude": 90.0, "longitude": 180.0}
WHOLE_NUMBERS = ("width",)
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

    unknown = (
        set(asked)
        - set(NUMBERS)
        - set(WHOLE_NUMBERS)
        - set(WORDS)
        - set(FLAGS)
        - set(LISTS)
    )
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
            limit = LIMITS[name]
            if not -limit <= options[name] <= limit:
                raise ValueError(
                    f"{name} should be between -{limit} and {limit}, "
                    f"not {options[name]}"
                )
    for name in WHOLE_NUMBERS:
        if name in asked:
            try:
                options[name] = int(asked[name][0])
            except ValueError:
                raise ValueError(
                    f"{name} should be a whole number, not {asked[name][0]!r}"
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


def _somewhere(options: dict) -> bool:
    """Whether there is a place to draw the sky above."""
    return options["latitude"] is not None and options["longitude"] is not None


def default_options(
    latitude: float | None, longitude: float | None, timezone: str
) -> dict:
    """
    The full set of options, so that a query string only has to differ.

    A public server passes no coordinates at all, which leaves the two that say
    where as ``None`` and makes every request name its own place.
    """
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
        "width": raster.DEFAULT_WIDTH,
    }


# options the chart is drawn with rather than computed with; they must not reach
# the Sky, which would otherwise be set up again for every change of color
DRAWING_OPTIONS = ("theme", "title", "width")


class SkyHandler(BaseHTTPRequestHandler):
    """Answers for one sky, drawn however the query string asks."""

    server_version = "skyfield"

    # set on the class by :func:`serve`
    cache: SkyCache
    defaults: dict
    public: bool = False

    def do_GET(self):
        route = urlparse(self.path)
        query = parse_qs(route.query)

        try:
            options = options_from_query(query, self.defaults)
        except ValueError as bad:
            self._send(400, "text/plain; charset=utf-8", str(bad).encode())
            return

        if self.public:
            # a server drawing for strangers has no business holding anyone's
            # address to the metre. Two decimals is about a kilometre, which no
            # chart of the whole sky can tell from none at all, and it keeps the
            # cache down to a few dozen skies rather than one per caller.
            for name in NUMBERS:
                if options[name] is not None:
                    options[name] = round(options[name], 2)

        try:
            handler = {
                "/": self._index,
                "/sky.svg": self._svg,
                "/sky.png": self._png,
                "/sky.json": self._json,
                "/sky.pebble": self._pebble,
            }[route.path]
        except KeyError:
            self._send(404, "text/plain; charset=utf-8", b"no such thing here\n")
            return

        if route.path != "/" and not _somewhere(options):
            # a public server was started without a place of its own, so the
            # caller has to say; it must not quietly draw the sky above whoever
            # happens to be running it
            self._send(
                400,
                "text/plain; charset=utf-8",
                b"say where you are: ?lat=47.61&lon=-122.33\n",
            )
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

    def _png(self, options):
        # a picture cannot ask the reader which colors they want, so `auto`
        # settles for the light ones here
        theme = options["theme"]
        picture = raster.render(
            self._model(options),
            theme="light" if theme == "auto" else theme,
            title=options["title"],
            width=options["width"],
        )
        self._send(200, "image/png", picture)

    def _json(self, options):
        body = json.dumps(self._model(options)).encode()
        self._send(200, "application/json; charset=utf-8", body)

    def _pebble(self, options):
        payload = pebble.pack(self._model(options))
        self._send(200, "application/octet-stream", payload)

    def _index(self, options):
        self._send(
            200, "text/html; charset=utf-8", PUBLIC_INDEX if self.public else INDEX
        )

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


# A public server knows nowhere, so its front page has to ask. Nothing is sent
# until the button is pressed, and the coordinates are cut to two decimals
# first, which is as fine as the server keeps them anyway.
PUBLIC_INDEX = b"""<!doctype html>
<meta charset="utf-8">
<title>Sky</title>
<style>
  body { margin: 0; display: grid; place-items: center; min-height: 100vh;
         background: #fff; color: #212121; text-align: center;
         font-family: system-ui, sans-serif; }
  img { width: min(90vw, 90vh); }
  main { max-width: 30rem; padding: 1.5rem; }
  button { padding: .8rem 1.4rem; font-size: 1rem; border-radius: .5rem;
           border: 0; background: #3f7fd0; color: #fff; }
  .note { color: #6b6b6b; font-size: .85rem; }
  @media (prefers-color-scheme: dark) {
    body { background: #101318; color: #e3e3e3; }
    .note { color: #9b9b9b; }
  }
</style>
<main id="ask">
  <p>The Sun, Moon, planets and constellations above wherever you say.
     This server has no place of its own.</p>
  <p><button id="here">Draw the sky above me</button></p>
  <p class="note">Your coordinates and your IP address reach this server.
     To keep both to yourself, run your own: it is
     <a href="https://github.com/partofthething/ha_skyfield">ha_skyfield</a>.
     Or say where in the address:
     <code>/sky.svg?lat=47.61&amp;lon=-122.33</code></p>
</main>
<img id="sky" alt="Chart of the sky" hidden>
<script>
  var zone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  var img = document.getElementById("sky");
  var ask = document.getElementById("ask");
  var place = null;

  function draw() {
    if (!place) return;
    // the cache buster is what stops the browser showing a stale sky
    img.src = "/sky.svg?lat=" + place.lat + "&lon=" + place.lon +
              "&tz=" + encodeURIComponent(zone) + "&t=" + Date.now();
  }

  document.getElementById("here").addEventListener("click", function () {
    navigator.geolocation.getCurrentPosition(function (fix) {
      place = { lat: fix.coords.latitude.toFixed(2),
                lon: fix.coords.longitude.toFixed(2) };
      ask.hidden = true;
      img.hidden = false;
      draw();
    }, function () {
      ask.querySelector("p").textContent =
        "No location, so nowhere to draw. Put lat and lon in the address instead.";
    });
  });

  // the sky turns a degree every four minutes, so this is smoother than an eye
  // can follow
  setInterval(draw, 60000);
</script>
"""


def serve(
    latitude: float | None = None,
    longitude: float | None = None,
    timezone: str = "UTC",
    host: str = "127.0.0.1",
    port: int = 8099,
    directory=None,
    public: bool = False,
    **overrides,
) -> ThreadingHTTPServer:
    """
    Build a server drawing the sky above one place, or above anywhere at all.

    Returned rather than run, so that a caller can decide whether to serve
    forever or to serve on a thread and get on with something else -- which is
    what the tests do.

    ``public`` is for a server open to strangers: it starts with no place of its
    own, so every request has to say where it is for, and there is no address
    left in the process for a bare ``/sky.svg`` to give away.
    """
    if public:
        latitude = longitude = None
    defaults = default_options(latitude, longitude, timezone)
    defaults.update({k: v for k, v in overrides.items() if v is not None})

    handler = type(
        "BoundSkyHandler",
        (SkyHandler,),
        {"cache": SkyCache(directory), "defaults": defaults, "public": public},
    )
    return ThreadingHTTPServer((host, port), handler)
