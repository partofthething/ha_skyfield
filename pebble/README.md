# Skyfield, on a wrist

A Pebble watch face showing the Sun, Moon, planets and constellation figures
above wherever you are, with the time in the middle.

## Building

Needs the [Pebble SDK](https://github.com/pebble-dev/rebble-tool) — the community
one, since the original is long gone.

```console
$ cd pebble
$ pebble build
$ pebble install --emulator chalk
```

`chalk` is the round 180×180 screen, which suits a polar chart better than
anything else Pebble made. `diorite` is a good second check: it is black and
white, so it shows whether the chart still reads without colour.

To put it on a real watch: `pebble install --phone <address>`.

## Feeding it

The watch face fetches from a skyfield server. Either will do:

* `skyfield-sky serve --lat 47.608 --lon -122.335 --tz America/Los_Angeles`,
  reachable from your phone, with no token
* Home Assistant, at `https://your-home-assistant/api/ha_skyfield`, with a
  long-lived access token

Both go in the settings page, in the Pebble app.

## Why it is built this way

**The radio is the battery, not the processor.** Placing a hundred-odd objects is
about six trigonometric operations each — a few milliseconds on the 64 MHz core,
which at one redraw a minute is a two-hundred-thousandth of the watch's time.
Waking Bluetooth for a single exchange costs orders of magnitude more.

So the server sends **right ascension and declination**, not screen positions.
Screen positions would save the watch its arithmetic, but they go stale: the
chart is roughly a pixel per degree of altitude and the sky turns fifteen degrees
an hour, so they would have to be fetched again every few minutes, all day. Sky
coordinates do not go stale. The watch fetches **twice a day**, turns the sky from
its own clock in between, and keeps working with the phone in another room.

**None of it is floating point.** A Cortex-M3 has no floating point unit, so a
`double` is built out of software. The Pebble SDK measures a full turn in 65536
steps and `ha_skyfield.pebble` sends angles already in those units, so what
arrives on the wire goes straight into `sin_lookup` with nothing converted.
Altitude comes out of `atan2_lookup` rather than an arcsine, because the SDK has
a table for one and not the other — which is also how `bodies.to_altaz` does it
in Python.

**The payload is about 1.5 kB** for the usual constellations: a 17-byte header
and then four or five bytes per object. It is split into 512-byte pieces, each
labelled with its position, so it does not matter what size inbox the watch
negotiated or what order Bluetooth delivers them in. Setting *Only these* in the
settings to a few constellation names makes it considerably smaller, which is the
one setting that actually affects battery.

The last payload is kept in watch storage, so a restart draws a sky immediately
rather than waiting on the phone.

## What is here

| | |
|---|---|
| `src/c/projection.c` | where a point of sky lands on the screen |
| `src/c/sky_data.c` | reading the payload, and refusing a bad one |
| `src/c/main.c` | the watch face itself |
| `src/pkjs/index.js` | the phone's half: fetch, split, send |
| `src/pkjs/config.js` | the settings page |

`projection.c` and `sky_data.c` compile on a desktop as well as a watch — that is
what `SKY_HOST` in `sky_trig.h` is for — and the Python test suite compiles both
and checks them against the Python that produced their input. See
`custom_components/tests/test_watchface.py` and `test_watchface_parser.py`.
`main.c` needs the real SDK and is only checked by building it.
