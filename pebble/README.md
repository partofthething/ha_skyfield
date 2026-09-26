# Skyfield Pebble watch face

A Pebble watch face showing the Sun, Moon, planets, and constellations above
your location, with the time in the middle.

## Building

Needs the community [Pebble SDK](https://github.com/pebble-dev/rebble-tool). No
npm dependencies.

```console
$ cd pebble
$ pebble build
```

That builds for every platform the SDK supports: `emery` (Pebble Time 2),
`flint` (Pebble 2 Duo), `gabbro` (round Core Devices), `chalk`, `basalt`,
`diorite`, and `aplite`. Text size is picked based on screen width.

## Putting it on a watch

```console
$ pebble install --cloudpebble          # needs `pebble login` + Developer Connection on
$ pebble install --phone 192.168.1.42   # direct, same wifi, Developer Connection on
$ pebble install --emulator emery       # no watch needed
```

Otherwise, send `build/pebble.pbw` to your phone and open it with the Pebble
app. `pebble logs` shows log output from the watch and the phone-side JavaScript.

## Feeding it

The watch face fetches data from a skyfield server, either:

* `skyfield-sky serve --lat 47.608 --lon -122.335 --tz America/Los_Angeles`,
  reachable from your phone, no token, or
* Home Assistant at `https://your-home-assistant/api/ha_skyfield` with a
  long-lived access token.

Set these in the watch face settings in the Pebble app.

If you don't run your own server, *Use the public server* points the watch at
`skyfield.partofthething.com`. It's off by default because it sends your
coordinates and IP address to a server you don't control. The token is never
sent to it. Since it has no location of its own, you'll need to enable the
phone's location or enter coordinates.

## Light mode

*Light mode* in the settings switches to black on white. The horizon, text,
and constellations are inverted, and each planet uses a darker version of its
color, since many of the dark mode colors are too pale to see on white. The
default is dark because it's a night sky chart, but reflective Pebble screens
are hard to read in dark mode in bright sunlight.

`main.c` never uses black or white directly. Everything is drawn with `paper()`
and `ink()`, so light mode doesn't need a second copy of the drawing code. The
star field is the only thing drawn in grey. With 64 colors (two bits per
channel) there are only four greys, and the date and corner readings use full
ink because grey is hard to read in sunlight.

## The date

*Date* in the settings picks the format of the date under the time:

| | |
|---|---|
| `Sun 16 Aug` | the default |
| `Sun Aug 16` | the same, US order |
| `2026-08-16` | ISO 8601 |
| `08/16` | month first |
| `16/08` | day first |

The watch stores these as `strftime` formats in `DATE_FORMATS` and the phone
sends an index into that list. The settings dropdown shows today's date in each
format, so `dateSamples()` in `config.js` needs to stay in sync with that table.

## The corners

Rectangular screens have four free corners around the horizon circle. Each
shows one reading and each can be turned off. Round watches (`chalk`, `gabbro`)
don't show them.

| | |
|---|---|
| top left | steps today |
| top right | battery, green on the charger, red at 20% |
| bottom left | heart rate |
| bottom right | temperature and a weather icon |

Steps and heart rate are read from whatever the firmware has already recorded.
The face never calls `health_service_set_heart_rate_sample_period`, so heart
rate may be a few minutes old but costs no extra battery.

**Weather is off by default** because it's the only feature that sends data to
a third party. There's no Pebble weather API, so `src/pkjs/index.js` fetches it
hourly from [open-meteo.com][om] using your coordinates. This is the only
request the watch face makes to anything other than your own server. Weather
needs *Use the phone's location* or a typed latitude and longitude, since the
server doesn't share its location. Readings older than four hours are dropped.
The phone maps Open-Meteo's [WMO codes][wmo] down to eight icons, since at 15
pixels light and heavy rain look the same.

The corner icons are drawn in code rather than shipped as image resources, to
avoid maintaining extra files across seven platforms. The only image resource
is `resources/images/menu_icon.png`, the 25×25 launcher icon required by the
appstore and phone app. `tools/make_menu_icon.py` regenerates it.

> Editing `messageKeys` in `package.json`? Run `pebble clean` after: waf misses
> it, and a stale `message_keys.auto.h` makes the phone and watch disagree.

[om]: https://open-meteo.com/
[wmo]: https://open-meteo.com/en/docs#weather_variable_documentation

## Design notes

**Battery use is dominated by the radio, not the CPU.** Positioning a hundred or
so objects takes a few milliseconds on the 64 MHz core, while waking Bluetooth
costs far more. So the server sends **right ascension and declination** instead
of screen positions. Screen positions go stale within minutes, but sky
coordinates don't. The watch fetches **twice a day** and rotates the sky using
its own clock in between, so it keeps working when the phone is out of range.

**No floating point.** The Cortex-M3 has no FPU. The SDK represents a full turn
as 65536 steps, and `ha_skyfield.pebble` sends angles in those units so they go
straight into `sin_lookup`. Altitude uses `atan2_lookup` instead of an arcsine
because the SDK only has a lookup table for atan2. `bodies.to_altaz` does the
same in Python.

**The payload is about 1.5 kB**: a 17-byte header plus four or five bytes per
object, split into numbered 512-byte chunks so inbox size and delivery order
don't matter. Limiting *Only these* to a few constellations makes it smaller,
which is the one setting that noticeably affects battery. The last payload is
saved in watch storage, so the face draws immediately after a restart.

## What is here

| | |
|---|---|
| `src/c/projection.c` | where a point of sky lands on the screen |
| `src/c/sky_data.c` | reading the payload, and refusing a bad one |
| `src/c/main.c` | the watch face itself |
| `src/pkjs/index.js` | the phone's half: fetch, split, send, weather |
| `src/pkjs/config.js` | the settings page, as plain HTML |

The settings page is hand-written instead of using [Clay][clay], which doesn't
build for `flint` or `gabbro`. Clay just gives the phone a `data:text/html` URL,
so doing it by hand is one page of HTML and no npm dependencies.

`projection.c` and `sky_data.c` also compile on desktop (that's what `SKY_HOST`
in `sky_trig.h` is for), and the Python tests check them against the Python
code that generates their input (`custom_components/tests/test_watchface.py`,
`test_watchface_parser.py`). `main.c` is only checked by building it.

[clay]: https://github.com/pebble/clay
