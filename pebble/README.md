# Skyfield, on a wrist

A Pebble watch face showing the Sun, Moon, planets and constellation figures
above wherever you are, with the time in the middle.

## Building

Needs the [Pebble SDK](https://github.com/pebble-dev/rebble-tool) — the community
one, since the original is long gone. No npm dependencies.

```console
$ cd pebble
$ pebble build
```

That builds for every platform the SDK knows about:

| platform | screen | watch |
|---|---|---|
| `emery` | 200×228 colour | **Pebble Time 2** |
| `flint` | 144×168 b&w | **Pebble 2 Duo** |
| `gabbro` | 260×260 colour, round | round Core Devices watch |
| `chalk` | 180×180 colour, round | Pebble Time Round |
| `basalt` | 144×168 colour | Pebble Time |
| `diorite` | 144×168 b&w | Pebble 2 |
| `aplite` | 144×168 b&w | original Pebble |

Lettering comes in two sizes, chosen from the screen's width, because type
picked for a 144 pixel screen reads like a caption on a 260 pixel one.

## Putting it on a watch

Any of these; the first is the one to try if the Pebble app says it is connected
to CloudPebble.

```console
$ pebble install --cloudpebble          # via the phone's CloudPebble connection
$ pebble install --phone 192.168.1.42   # direct, same wifi, developer connection on
$ pebble install --emulator emery       # no watch needed
```

`--cloudpebble` needs `pebble login` first, and needs the Developer Connection
turned on in the Pebble app. `--phone` wants the address the app shows on that
same screen, and both devices on one network.

Failing all that, `build/pebble.pbw` is the app: send it to the phone however
you like and open it with the Pebble app.

`pebble logs` shows what the watch and the phone-side JavaScript are saying,
which is where a fetch that is not happening will explain itself.

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
| `src/pkjs/config.js` | the settings page, as plain HTML |

The settings page is written by hand rather than with [Clay][clay], which is the
usual way to do it. Clay 1.0.4 does not build for `flint` or `gabbro`, and those
are the watches this is mostly for. What Clay actually does is hand the phone a
`data:text/html` URL with the whole page in it, so doing the same by hand costs
a page of HTML, works on every platform, and leaves the project with no npm
dependencies at all.

[clay]: https://github.com/pebble/clay

`projection.c` and `sky_data.c` compile on a desktop as well as a watch — that is
what `SKY_HOST` in `sky_trig.h` is for — and the Python test suite compiles both
and checks them against the Python that produced their input. See
`custom_components/tests/test_watchface.py` and `test_watchface_parser.py`.
`main.c` needs the real SDK and is only checked by building it.
