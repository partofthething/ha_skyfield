#include "sky_data.h"

/*
 * The same nine bodies as bodies.BODIES, in the same order, since that order is
 * what the payload sends instead of a name. The radii are the matplotlib marker
 * areas brought down to something sensible on a watch: the Sun and Moon want to
 * be recognisable, and the outer planets are dots.
 */
const SkyBodyStyle SKY_BODIES[SKY_BODY_COUNT] = {
    {"Sun", 5},     {"Mercury", 2}, {"Venus", 2},
    {"Moon", 4},    {"Mars", 2},    {"Jupiter", 3},
    {"Saturn", 3},  {"Uranus", 2},  {"Neptune", 2},
};

/* Little-endian, a byte at a time, because the fields are not aligned. */
static uint16_t read_u16(const uint8_t *at) {
  return (uint16_t)(at[0] | ((uint16_t)at[1] << 8));
}

static int16_t read_i16(const uint8_t *at) { return (int16_t)read_u16(at); }

static uint32_t read_u32(const uint8_t *at) {
  return (uint32_t)at[0] | ((uint32_t)at[1] << 8) | ((uint32_t)at[2] << 16) |
         ((uint32_t)at[3] << 24);
}

bool sky_data_parse(SkyData *sky) {
  sky->valid = false;

  if (sky->length < SKY_HEADER_SIZE) {
    return false;
  }
  if (sky->bytes[0] != 'S' || sky->bytes[1] != 'K' || sky->bytes[2] != 'Y') {
    return false;
  }
  if (sky->bytes[3] != SKY_FORMAT_VERSION) {
    return false;
  }

  sky->generated = (int32_t)read_u32(&sky->bytes[4]);
  sky->latitude = read_i16(&sky->bytes[8]);
  sky->longitude = read_i16(&sky->bytes[10]);
  sky->body_count = sky->bytes[12];
  sky->star_count = read_u16(&sky->bytes[13]);
  sky->line_count = read_u16(&sky->bytes[15]);

  /*
   * The counts have to account for exactly what arrived. A payload that ends
   * early would otherwise be read off the end of the buffer, and one that
   * claims fewer things than it carries is not the payload that was sent.
   */
  uint32_t expected = (uint32_t)SKY_HEADER_SIZE +
                      (uint32_t)sky->body_count * SKY_BODY_SIZE +
                      (uint32_t)sky->star_count * SKY_STAR_SIZE +
                      (uint32_t)sky->line_count * SKY_LINE_SIZE;
  if (expected != sky->length) {
    return false;
  }
  if (sky->body_count > SKY_BODY_COUNT) {
    return false;
  }

  /* every join has to point at a star that is actually here */
  for (uint16_t index = 0; index < sky->line_count; index++) {
    SkyLine line = sky_data_line(sky, index);
    if (line.from >= sky->star_count || line.to >= sky->star_count) {
      return false;
    }
  }

  sky->valid = true;
  return true;
}

SkyBody sky_data_body(const SkyData *sky, uint16_t index) {
  const uint8_t *at = &sky->bytes[SKY_HEADER_SIZE + index * SKY_BODY_SIZE];
  SkyBody body = {
      .ra = read_u16(at),
      .dec = read_i16(at + 2),
      .body = at[4],
  };
  return body;
}

SkyStar sky_data_star(const SkyData *sky, uint16_t index) {
  const uint8_t *at = &sky->bytes[SKY_HEADER_SIZE +
                                  sky->body_count * SKY_BODY_SIZE +
                                  index * SKY_STAR_SIZE];
  SkyStar star = {.ra = read_u16(at), .dec = read_i16(at + 2)};
  return star;
}

SkyLine sky_data_line(const SkyData *sky, uint16_t index) {
  const uint8_t *at = &sky->bytes[SKY_HEADER_SIZE +
                                  sky->body_count * SKY_BODY_SIZE +
                                  sky->star_count * SKY_STAR_SIZE +
                                  index * SKY_LINE_SIZE];
  SkyLine line = {.from = read_u16(at), .to = read_u16(at + 2)};
  return line;
}
