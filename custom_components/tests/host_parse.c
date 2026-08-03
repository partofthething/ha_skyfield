/*
 * Read a payload on stdin with the watch face's own parser and print what it
 * made of it, so the test can compare that against what Python packed.
 */

#include "../../pebble/src/c/sky_data.h"
#include <stdio.h>

int main(void) {
  static SkyData sky;
  size_t read = fread(sky.bytes, 1, SKY_MAX_PAYLOAD, stdin);
  sky.length = (uint16_t)read;

  if (!sky_data_parse(&sky)) {
    printf("rejected\n");
    return 0;
  }

  printf("accepted %ld %d %d %u %u %u\n", (long)sky.generated, sky.latitude,
         sky.longitude, sky.body_count, sky.star_count, sky.line_count);

  for (uint16_t index = 0; index < sky.body_count; index++) {
    SkyBody body = sky_data_body(&sky, index);
    printf("body %u %d %u %s\n", body.ra, body.dec, body.body,
           SKY_BODIES[body.body].name);
  }
  for (uint16_t index = 0; index < sky.star_count; index++) {
    SkyStar star = sky_data_star(&sky, index);
    printf("star %u %d\n", star.ra, star.dec);
  }
  for (uint16_t index = 0; index < sky.line_count; index++) {
    SkyLine line = sky_data_line(&sky, index);
    printf("line %u %u\n", line.from, line.to);
  }
  return 0;
}
