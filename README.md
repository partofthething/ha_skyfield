# Live Sun, Moon, and Planets

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/partofthething/ha_skyfield)

A live polar sun path chart for your location. Besides the Sun, it also shows the
Moon and a few major planets. Plus, it shows the Winter and Summer solstice sun
paths so you can see where you are in the seasons!

![Screenshot of the skyfield](screenshot.png)

This uses the [skyfield library](https://rhodesmill.org/skyfield/) to do the computations. 

It is three things in one repository, drawing one chart:

* a **custom component for [Home Assistant](https://www.home-assistant.io/)**, with
  a Lovelace card that draws itself in the browser
* a **command line tool and small web server** that write the same chart as an SVG
  file, for a web page or anything else that wants a picture
* a **Pebble watch face**, in [`pebble/`](pebble/)

See [`pebble/README.md`](pebble/README.md) for the watch and
[Standalone](#standalone) below for everything outside Home Assistant.

## To use with Home Assistant

* Install this in your `custom_components` folder
* Add the following to your home assistant config and restart:
```yaml
ha_skyfield:
```
* Add this card to your dashboard:
```yaml
type: custom:skyfield-card
```

The card registers itself as a dashboard resource, so there is normally nothing to
add by hand. It draws itself as SVG, so it stays sharp at any size and takes its
colours from your theme, dark mode included.

If your dashboard resources are managed in YAML rather than through the UI, Home
Assistant will not let the integration add to them, and you will see a warning in
the log saying so. Add it yourself in that case:

```yaml
lovelace:
  resources:
    - url: /ha_skyfield/skyfield-card.js
      type: module
```

If a dashboard ever reports `Custom element doesn't exist: skyfield-card`, look in
the browser console for a `skyfield-card loaded` line. If it is absent the file is
not reaching the browser; if it is present the card is loaded and the dashboard
simply asked for it too early, which the resource registration above fixes.

The chart is drawn in your browser from the sky coordinates Home Assistant sends
it. Those only change slowly, so the browser can turn the sky itself as the
minutes pass — it redraws twice a minute and only asks the server for new
positions every ten minutes.

Optional card configuration:

* `title` a heading for the card
* `show_time` show a timestamp under the chart
* `show_legend` show a legend of the bodies
* `show_constellations` draw the constellations
* `north_up` (boolean) puts North at the top (useful in the Southern Hemisphere)
* `horizontal_flip` (boolean) flips projection horizontally
* `refresh_interval` seconds between asking the server for new positions (default 600)
* `redraw_interval` seconds between redraws (default 30)

Anything you leave out follows the `ha_skyfield:` configuration below. The
solstice path colours can be restyled with the `--skyfield-winter-color` and
`--skyfield-summer-color` theme variables.

Optional configuration under `ha_skyfield:`:

* `show_constellations` enable or disable the constellations (default is True).
* `show_time` and `show_legend` defaults for the card
* `planet_list` customize which planets are shown
* `constellations_list` customize which constellations are shown (use names from
  [here](https://github.com/partofthething/ha_skyfield/blob/master/custom_components/ha_skyfield/constellations_by_RA_Dec.dat))
* `north_up` (boolean) puts North at the top (useful in the Southern Hemisphere)
* `horizontal_flip` (boolean) flips projection horizontally
* `latitude` and `longitude` if you want somewhere other than your home

## The image version

If you would rather have an image than a card, the integration also serves the
chart ready-drawn at `/api/ha_skyfield/sky.svg`, and there is a camera entity:

```yaml
camera:
  platform: ha_skyfield
  show_constellations: false
```

Then add a picture entity to your GUI with this camera. It takes the same options
as `ha_skyfield:` above. There is also a sensor platform, whose state is the
Sun's altitude and which writes the chart to `www/sun.svg` for `/local/sun.svg`.

The card is still the better option: it turns the sky in your browser without
asking the server, and it follows your theme.

## Standalone

None of the below needs Home Assistant.

```console
$ pip install git+https://github.com/partofthething/ha_skyfield
$ skyfield-sky svg --lat 47.608 --lon -122.335 --tz America/Los_Angeles -o sky.svg
```

The first run downloads a 17 MB ephemeris and keeps it in `~/.cache/ha_skyfield`,
so it is only slow once. The SVG is self-contained — one file, no external CSS,
no fonts to fetch — and follows the reader's dark mode unless you pin it with
`--theme light` or `--theme dark`. `--palette` is available from Python if you
want it to match a site's colours.

For a web page, the simplest thing is usually to redraw a file on a timer and let
whatever already serves the site hand it out:

```console
$ skyfield-sky watch --lat 47.608 --lon -122.335 --tz America/Los_Angeles \
      --interval 300 -o /var/www/sky.svg
```

Or run the built-in server, which has no dependencies beyond the ones drawing the
chart already needs:

```console
$ skyfield-sky serve --lat 47.608 --lon -122.335 --tz America/Los_Angeles --port 8099
```

| | |
|---|---|
| `/` | a page showing the chart, refreshing itself |
| `/sky.svg` | the chart |
| `/sky.json` | the sky as data, the same thing the card is sent |
| `/sky.pebble` | the sky packed small, for the watch face |

Every option can be given in the query string — `?lat=51.5&lon=-0.13&tz=Europe/London`,
`?theme=dark`, `?constellations=Orion,UrsaMajor` — so one server can draw
anywhere. A misspelled parameter is a 400 rather than a chart quietly drawn for
the wrong place.

`skyfield-sky json` and `skyfield-sky pebble` print the underlying data if you
would rather draw it yourself. `python -m ha_skyfield` is the same command.

## Upgrading from 2.x

**matplotlib is gone.** It was the heaviest dependency here by a wide margin, and
Home Assistant installs everything in `requirements` on setup, so on any system
without a prebuilt wheel it meant compiling it. The chart is now drawn as SVG in
Python, which is the same drawing the card was already making in the browser.

What this changes:

* The camera entity serves `image/svg+xml` instead of PNG or JPEG. Its
  `image_type` option no longer does anything and can be removed; leaving it in
  place logs a warning and is otherwise harmless.
* The sensor writes `www/sun.svg`, so its picture is now `/local/sun.svg`.
  Delete the old `www/sun.png` if you like.
* `Sky.plot_sky()` and the `plots` module are gone. `ha_skyfield.svg.render()`
  replaces them.

Known Issues:

* More (maybe) at [Issues](https://github.com/partofthething/ha_skyfield/issues)

Inspiration comes from the University of Oregon 
[Solar Radiation Monitoring Lab](http://solardat.uoregon.edu/PolarSunChartProgram.html).

## Developing

```console
$ uv venv && uv pip install -e .
$ cd custom_components && python -m unittest discover -s tests -t .
```

The chart is drawn in three languages — Python for files and the server,
JavaScript for the card, C for the watch — because each has to draw it somewhere
the others cannot reach. They are only three views of one chart for as long as
they agree, so the suite checks that directly rather than trusting it:

* `test_projection.py` reads the card's layout constants out of the JavaScript
  and compares them to the Python's.
* `test_svg_matches_card.py` runs the card's own `altAz` under `node` and checks
  it lands where the Python does.
* `test_watchface.py` compiles `pebble/src/c/projection.c` with `cc` and checks
  it lands in the same pixel, to within half of one.
* `test_watchface_parser.py` compiles the watch's payload parser and feeds it
  what `ha_skyfield.pebble` packs.

The last three skip themselves if `node` or a C compiler is missing.


