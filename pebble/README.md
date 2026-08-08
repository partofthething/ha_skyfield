# Skyfield, on a wrist

A Pebble watch face showing the Sun, Moon, planets and constellation figures
above wherever you are, with the time in the middle.

## Building

Needs the community [Pebble SDK](https://github.com/pebble-dev/rebble-tool). No
npm dependencies.

```console
$ cd pebble
$ pebble build
```

That builds every platform the SDK knows: `emery` (Pebble Time 2), `flint`
(Pebble 2 Duo), `gabbro` (round Core Devices), `chalk`, `basalt`, `diorite`,
`aplite`. Lettering comes in two sizes, chosen from the screen's width.

## Putting it on a watch

```console
$ pebble install --cloudpebble          # needs `pebble login` + Developer Connection on
$ pebble install --phone 192.168.1.42   # direct, same wifi, Developer Connection on
$ pebble install --emulator emery       # no watch needed
```

Failing those, send `build/pebble.pbw` to the phone and open it with the Pebble
app. `pebble logs` shows what the watch and the phone-side JavaScript are
saying.

## Feeding it

The watch face fetches from a skyfield server — either

* `skyfield-sky serve --lat 47.608 --lon -122.335 --tz America/Los_Angeles`,
  reachable from your phone, no token, or
* Home Assistant at `https://your-home-assistant/api/ha_skyfield` with a
  long-lived access token.

Both go in the settings page in the Pebble app.

## The corners

A rectangular screen has four corners left over around the horizon circle. Each
holds one reading and each can be turned off. Round watches (`chalk`, `gabbro`)
leave all four out.

| | |
|---|---|
| top left | steps today |
| top right | battery, green on the charger, red at 20% |
| bottom left | heart rate |
| bottom right | temperature and a weather icon |

Steps and heart rate are only *read* from what the firmware already recorded —
this face never calls `health_service_set_heart_rate_sample_period`, so a heart
rate may be some minutes old and costs no battery.

**Weather is off by default**, because it is the only thing that leaves. No
Pebble API exposes the weather, so `src/pkjs/index.js` fetches it hourly from
[open-meteo.com][om], which is sent your coordinates to answer — the only
request this watchface makes of anyone but your own server. Turning the corner
on needs *Use the phone's location* or a typed latitude and longitude; a server
keeps its own place to itself. The watch ages a reading out after four hours.
Open-Meteo's [WMO codes][wmo] are flattened by the phone to eight drawable
conditions, because at fifteen pixels light and heavy rain are the same picture.

The corner icons are drawn in code, not shipped as resources — a PNG would be
seven more files to keep in step across seven platforms. The one real resource
is `resources/images/menu_icon.png`, the 25×25 launcher icon, which the
appstore and the phone insist on; `tools/make_menu_icon.py` redraws it.

> Editing `messageKeys` in `package.json`? Run `pebble clean` after: waf misses
> it, and a stale `message_keys.auto.h` makes the phone and watch disagree.

[om]: https://open-meteo.com/
[wmo]: https://open-meteo.com/en/docs#weather_variable_documentation

## Why it is built this way

**The radio is the battery, not the processor.** Placing a hundred-odd objects
is a few milliseconds on the 64 MHz core; waking Bluetooth costs orders of
magnitude more. So the server sends **right ascension and declination**, not
screen positions — screen positions go stale within minutes as the sky turns,
sky coordinates never do. The watch fetches **twice a day** and turns the sky
from its own clock in between, working with the phone in another room.

**None of it is floating point.** A Cortex-M3 has no FPU. The SDK measures a
full turn in 65536 steps and `ha_skyfield.pebble` sends angles already in those
units, so they go straight into `sin_lookup`. Altitude comes from
`atan2_lookup` rather than an arcsine, because the SDK has a table for one and
not the other — as `bodies.to_altaz` does in Python.

**The payload is about 1.5 kB**: a 17-byte header plus four or five bytes per
object, split into labelled 512-byte pieces so inbox size and delivery order do
not matter. Setting *Only these* to a few constellations shrinks it, which is
the one setting that really affects battery. The last payload is kept in watch
storage, so a restart draws immediately.

## What is here

| | |
|---|---|
| `src/c/projection.c` | where a point of sky lands on the screen |
| `src/c/sky_data.c` | reading the payload, and refusing a bad one |
| `src/c/main.c` | the watch face itself |
| `src/pkjs/index.js` | the phone's half: fetch, split, send, weather |
| `src/pkjs/config.js` | the settings page, as plain HTML |

The settings page is hand-written rather than [Clay][clay], which does not build
for `flint` or `gabbro`. Clay just hands the phone a `data:text/html` URL, so
doing it by hand costs a page of HTML and leaves no npm dependencies.

`projection.c` and `sky_data.c` also compile on a desktop — that is what
`SKY_HOST` in `sky_trig.h` is for — and the Python tests check them against the
Python that produced their input (`custom_components/tests/test_watchface.py`,
`test_watchface_parser.py`). `main.c` is only checked by building it.

[clay]: https://github.com/pebble/clay
