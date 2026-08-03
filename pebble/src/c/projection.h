/*
 * Where a point of sky lands on the watch.
 *
 * This is the third copy of the arithmetic in ha_skyfield -- the card does it in
 * JavaScript and ha_skyfield/projection.py does it in Python -- and it exists
 * because doing it here is what lets the watch fetch twice a day instead of
 * every few minutes. Sky coordinates do not go stale; screen coordinates do.
 *
 * All of it is integers. A Cortex-M3 has no floating point unit, so a double
 * would be built out of software, and there is no need: the Pebble SDK measures
 * angles in 65536ths of a turn and ha_skyfield.pebble sends them already in
 * those units. Altitude comes out of atan2 rather than asin for the same
 * reason -- the SDK has a lookup for one and not the other -- which is also how
 * bodies.to_altaz does it in Python.
 */

#pragma once

#include "sky_trig.h"
#include <stdbool.h>
#include <stdint.h>

/* a quarter turn: 90 degrees of declination, or of altitude */
#define SKY_QUARTER_TURN (TRIG_MAX_ANGLE / 4)

/* seconds between the Unix epoch and J2000, which the sidereal formula counts from */
#define SKY_J2000_EPOCH 946728000L

/* Where the observer is, and which way the sky has turned for them. */
typedef struct {
  int32_t sin_latitude; /* Q16 */
  int32_t cos_latitude; /* Q16 */
  int32_t sidereal;     /* local, in TRIG_MAX_ANGLE units */
} SkyObserver;

/* How the chart is laid out on this particular screen. */
typedef struct {
  int16_t centre_x;
  int16_t centre_y;
  int16_t horizon_radius;
  bool north_up;
  bool horizontal_flip;
} SkyLayout;

typedef struct {
  int32_t azimuth;  /* TRIG_MAX_ANGLE units, east of north */
  int32_t altitude; /* TRIG_MAX_ANGLE units, up from the horizon */
} SkyAltAz;

typedef struct {
  int16_t x;
  int16_t y;
} SkyPoint;

/*
 * Greenwich mean sidereal time for a moment, in TRIG_MAX_ANGLE units.
 *
 * The angle the Earth has turned to against the stars. Treating Unix time as
 * UT1 leaves it under a second out, which is a hundredth of a pixel here.
 */
int32_t sky_sidereal_time(int32_t unix_seconds);

/*
 * Work out the parts of the rotation every body shares.
 *
 * Longitude in hundredths of a degree east, as it arrives on the wire.
 */
SkyObserver sky_observer_at(int32_t unix_seconds, int16_t latitude_hundredths,
                            int16_t longitude_hundredths);

/* Turn right ascension and declination into azimuth and altitude. */
SkyAltAz sky_alt_az(uint16_t ra, int16_t dec, const SkyObserver *observer);

/* Place a point of sky on the screen. Below the horizon still lands somewhere. */
SkyPoint sky_project(SkyAltAz position, const SkyLayout *layout);

/* How far from the middle a given altitude sits. */
int32_t sky_radius_for(int32_t altitude, int16_t horizon_radius);
