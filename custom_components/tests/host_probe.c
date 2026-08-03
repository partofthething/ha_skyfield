/*
 * Ask the watch face's projection where things are, and print the answers.
 *
 * Reads lines of "unix_seconds lat_hundredths lon_hundredths ra dec" on stdin
 * and prints "azimuth altitude x y" for each, all in the watch's own units. The
 * test drives it and compares against the Python.
 */

#include "../../pebble/src/c/projection.h"
#include <stdio.h>

int main(void) {
  long when, ra, dec;
  int latitude, longitude;

  while (scanf("%ld %d %d %ld %ld", &when, &latitude, &longitude, &ra, &dec) == 5) {
    SkyObserver observer =
        sky_observer_at((int32_t)when, (int16_t)latitude, (int16_t)longitude);
    SkyAltAz position = sky_alt_az((uint16_t)ra, (int16_t)dec, &observer);

    /* the same 400-unit layout the card and the SVG use, so they can be compared */
    SkyLayout layout = {
        .centre_x = 200,
        .centre_y = 200,
        .horizon_radius = 165,
        .north_up = false,
        .horizontal_flip = false,
    };
    SkyPoint point = sky_project(position, &layout);

    printf("%ld %ld %d %d %ld\n", (long)position.azimuth, (long)position.altitude,
           point.x, point.y, (long)observer.sidereal);
  }
  return 0;
}
