# Running the sky server on a real server

These are examples. Change the hostname, paths, and coordinates to match your
setup.

There are two servers, which can run side by side. The private one draws a
single location, set in `/etc/skyfield-sky.env`. The public one has no default
location, so every request has to include coordinates.

| | |
|---|---|
| `skyfield-sky.service` | private server on 8099, coordinates from the environment |
| `skyfield-sky.env` | the coordinates, kept out of the unit file, mode 600 |
| `apache-skyfield.conf` | TLS vhost and reverse proxy for it |
| `skyfield-sky-public.service` | `--public`, on 8100, no coordinates anywhere |
| `apache-skyfield-public.conf` | same, with minimal logging and rate limits |

`skyfield-sky serve` binds to localhost and has no authentication, so Apache
handles public traffic. It serves `/sky.svg`, `/sky.png`, `/sky.json`,
`/sky.pebble`, and `/`, a page that reloads the chart every minute. On the
public server, `/` asks for your location first.

In the watch face settings, use the vhost address with no path (e.g.
`https://sky.example.com`) and leave the token empty. The token is only for
Home Assistant.

## What the public one costs

Rough numbers, which the vhost rate limits are based on:

| | |
|---|---|
| a chart it has not drawn before | ~20 ms |
| one it has | ~6 ms |
| all of them, together | ~50 a second |

The last number is a ceiling. The server draws one chart at a time behind a
lock, so more concurrent requests just means longer queues. Ten thousand
watches fetching twice a day is about 0.25 requests per second, half a percent
of capacity. The rate limits are there for the case of a single client looping
over lots of new coordinates, where every request is a cache miss.

The public server also shouldn't log people's locations. Coordinates are in
the query string, so the standard `combined` log format would record them next
to each IP address. The public vhost logs the path without the query string and
no IP address.
