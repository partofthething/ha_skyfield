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
| `emery` | 200×228 color | **Pebble Time 2** |
| `flint` | 144×168 b&w | **Pebble 2 Duo** |
| `gabbro` | 260×260 color, round | round Core Devices watch |
| `chalk` | 180×180 color, round | Pebble Time Round |
| `basalt` | 144×168 color | Pebble Time |
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

## The corners

On a rectangular screen the horizon is a circle inscribed in it, which leaves
four corners doing nothing. Each holds one reading, and each can be turned off
in the settings page. A round watch has no corners, so `chalk` and `gabbro`
leave all four out however they are set.

| | |
|---|---|
| top left | steps today, with a walking figure |
| top right | battery, green on the charger and red at 20% |
| bottom left | heart rate, with a heart |
| bottom right | temperature and a weather icon |

Three of those the watch already knows. **Steps and heart rate are read, never
asked for**: `health_service_sum_today` and `health_service_peek_current_value`
return whatever the firmware has already recorded. The call that would make the
heart sensor run more often is `health_service_set_heart_rate_sample_period`,
and this face never makes it — the sampling rate stays whatever the wearer chose
in the watch's own health settings, so a heart rate here may be some minutes old
and costs nothing at all to show.

**Weather is the exception, and it is not free.** A Pebble exposes 547 calls to
a watchface and not one of them is about the weather: the system weather app and
its timeline pins are filled in by the phone, into storage no watchapp can read.
So the temperature has to come over the air. `src/pkjs/index.js` fetches it
hourly from [open-meteo.com][om], which wants no key and no account, and is
where most weather watchfaces get theirs. It is also **the only thing this
watchface asks of anyone but your own server**, and it is sent your coordinates
to answer — turning the corner off in the settings stops the fetch entirely.

The watch keeps the last temperature it was told and ages it out after four
hours, so a restart is not blank but a number from yesterday never passes for
one from now. Open-Meteo answers in [WMO present-weather codes][wmo], ninety-nine
of them, which the phone flattens to the eight the watch can draw: clear by day,
clear by night, partly cloudy, cloudy, rain, snow, thunder, fog. Every grade of
drizzle, freezing rain and shower lands on the one raincloud, because at fifteen
pixels light rain and heavy rain are the same picture.

Weather needs coordinates, so it needs either *Use the phone's location* on or
something typed into the latitude and longitude boxes. A server drawing its own
place keeps that place to itself, and there is nothing for Open-Meteo to go on.

[om]: https://open-meteo.com/
[wmo]: https://open-meteo.com/en/docs#weather_variable_documentation

The icons are not resources. A walking figure at this size is a dozen lines of
arithmetic, and a PNG of it is seven more files to keep in step across seven
platforms.

> Note for anyone editing `messageKeys` in `package.json`: waf does not always
> notice, and a stale `build/include/message_keys.auto.h` means the phone and the
> watch disagree about which number means what. Run `pebble clean` after.

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
| `src/pkjs/index.js` | the phone's half: fetch, split, send, and the weather |
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
