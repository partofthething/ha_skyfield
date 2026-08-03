/*
 * The sky as it arrives from the server, and as it is kept between fetches.
 *
 * The layout is written down in ha_skyfield/pebble.py, which is what makes it;
 * that module also has an unpacker of its own so that the two can be checked
 * against each other.
 *
 * Nothing here is read by casting a struct over the buffer. The fields are not
 * aligned the way a compiler would like them, and an unaligned halfword load on
 * a Cortex-M is a fault rather than a slow read, so every field is assembled a
 * byte at a time.
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SKY_FORMAT_VERSION 2

#define SKY_HEADER_SIZE 19
#define SKY_BODY_SIZE 5
#define SKY_STAR_SIZE 4
#define SKY_LINE_SIZE 4
#define SKY_PATH_HEADER_SIZE 1
#define SKY_PATH_POINT_SIZE 4

/* the Sun's daily curves: today's, and the two solstices */
#define SKY_MAX_PATHS 3
#define SKY_PATH_TODAY 0
#define SKY_PATH_WINTER 1
#define SKY_PATH_SUMMER 2

/*
 * How much sky to keep room for. The usual set of constellations comes to about
 * fifteen hundred bytes; this leaves room to spare without eating the heap a
 * watch face is allowed.
 */
#define SKY_MAX_PAYLOAD 2600

/*
 * How much of it comes in one message. This has to be the same number as
 * pebble.CHUNK_SIZE on the other side, since that is what says where a piece
 * belongs; custom_components/tests/test_watchface.py checks that it still is.
 */
#define SKY_CHUNK_SIZE 512

/* the nine things in bodies.BODIES, which the watch has its own table for */
#define SKY_BODY_COUNT 9

typedef struct {
  uint16_t ra;
  int16_t dec;
  uint8_t body; /* an index into bodies.BODIES, and into SKY_BODIES here */
} SkyBody;

typedef struct {
  uint16_t ra;
  int16_t dec;
} SkyStar;

typedef struct {
  uint16_t from;
  uint16_t to;
} SkyLine;

/*
 * A point on one of the Sun's daily curves.
 *
 * Already azimuth and altitude rather than sky coordinates: a day's track does
 * not turn with the hour, so unlike a star this needs no rotating, only
 * projecting.
 */
typedef struct {
  uint16_t azimuth;
  int16_t altitude;
} SkyPathPoint;

/* A payload, and the way into the things packed inside it. */
typedef struct {
  uint8_t bytes[SKY_MAX_PAYLOAD];
  uint16_t length;
  bool valid;

  int32_t generated;
  int16_t latitude;  /* hundredths of a degree north */
  int16_t longitude; /* hundredths of a degree east */
  uint8_t body_count;
  uint16_t star_count;
  uint16_t line_count;
  uint8_t path_count;
  uint8_t path_points;
} SkyData;

/*
 * Check a payload over and note where everything in it is.
 *
 * Says whether it made sense. A watch face that drew whatever it was handed
 * would draw nonsense after a bad fetch, which looks like a broken sky rather
 * than a broken download.
 */
bool sky_data_parse(SkyData *sky);

SkyBody sky_data_body(const SkyData *sky, uint16_t index);
SkyStar sky_data_star(const SkyData *sky, uint16_t index);
SkyLine sky_data_line(const SkyData *sky, uint16_t index);

/* Which of the Sun's curves this is: one of the SKY_PATH_ values above. */
uint8_t sky_data_path_kind(const SkyData *sky, uint8_t path);
SkyPathPoint sky_data_path_point(const SkyData *sky, uint8_t path, uint8_t point);

/* What each body is called and how big to draw it, by its index. */
typedef struct {
  const char *name;
  uint8_t radius; /* in pixels, on a chart of the usual size */
} SkyBodyStyle;

extern const SkyBodyStyle SKY_BODIES[SKY_BODY_COUNT];
