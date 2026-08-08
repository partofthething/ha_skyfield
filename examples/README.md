# Running the sky server on a real server

Examples, not configuration: change the hostname, the paths and the coordinates.

Two servers, which run side by side. Yours draws one place and is told where by
`/etc/skyfield-sky.env`. The public one draws anywhere and is told nowhere, so
every request has to say.

| | |
|---|---|
| `skyfield-sky.service` | yours, on 8099, coordinates from the environment |
| `skyfield-sky.env` | those coordinates, out of the unit and mode 600 |
| `apache-skyfield.conf` | TLS vhost and reverse proxy for it |
| `skyfield-sky-public.service` | `--public`, on 8100, no coordinates anywhere |
| `apache-skyfield-public.conf` | the same, with quiet logs and real rate limits |

`skyfield-sky serve` binds localhost and has no authentication, so Apache is
what faces the world. It serves `/sky.svg`, `/sky.png`, `/sky.json`,
`/sky.pebble` and an `/` that reloads the chart every minute — on a public
server, an `/` that asks the reader where they are first.

The watch face wants the vhost address with no path — `https://sky.example.com`
— and no token; the token box is for Home Assistant.

## What the public one costs

Worth knowing before pointing a domain at it, because it is what the limits in
the vhost are sized against:

| | |
|---|---|
| a chart it has not drawn before | ~20 ms |
| one it has | ~6 ms |
| all of them, together | ~50 a second |

That last one is a ceiling rather than a rate: the server draws one sky at a
time behind a single lock, so more callers at once buys no more charts, only
longer queues. Ten thousand watches fetching twice a day is a quarter of a
request a second, half a percent of it. The limits are not there for the
watches — they are there because one caller with a loop and a list of
coordinates is a hundred percent of it, every request a chart nobody has asked
for before.

The other thing a public server owes people is not writing down where they are.
Coordinates arrive in the query string, so the ordinary `combined` log format
would keep everyone's location beside their IP address; the public vhost logs a
path without a query and no address at all.
