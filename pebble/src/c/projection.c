#include "projection.h"

/*
 * Sidereal time advances by this many sixty-five-thousandths of a turn per day,
 * times ten thousand. That is 360.98564736629 degrees, which is a full turn plus
 * the degree or so the Earth has to go round again to face the Sun after moving
 * along its orbit. The scaling by ten thousand is what keeps the fraction
 * without a decimal point; see the same numbers in ha_skyfield/projection.py.
 */
/* Every name here is prefixed, because pebble.h is in scope and defines a
 * SECONDS_PER_DAY of its own -- which the desktop build, having no pebble.h,
 * cannot warn about. */
#define SKY_SIDEREAL_PER_DAY 657154316L
#define SKY_SIDEREAL_AT_EPOCH 510562975L
#define SKY_SIDEREAL_SCALE 10000L
#define SKY_SECONDS_PER_DAY 86400L

/* hundredths of a degree to TRIG_MAX_ANGLE units, times ten thousand */
#define SKY_DEGREE_HUNDREDTHS_TO_TRIG 18204L /* 65536 / 360 / 100 * 10000 */

/* Multiply two Q16 fixed-point numbers. */
static int32_t mul16(int32_t a, int32_t b) {
  return (int32_t)(((int64_t)a * (int64_t)b) >> 16);
}

/*
 * Integer square root, since the SDK has no such thing and a double would be
 * built out of software. Bit by bit, so it is a couple of dozen cycles.
 */
static uint32_t isqrt(uint32_t value) {
  uint32_t rest = value;
  uint32_t result = 0;
  uint32_t bit = 1UL << 30;

  while (bit > rest) {
    bit >>= 2;
  }
  while (bit != 0) {
    if (rest >= result + bit) {
      rest -= result + bit;
      result = (result >> 1) + bit;
    } else {
      result >>= 1;
    }
    bit >>= 2;
  }
  return result;
}

int32_t sky_sidereal_time(int32_t unix_seconds) {
  /*
   * Whole days and the remainder separately, rather than seconds all at once.
   * Seconds since J2000 times the per-day figure would run past what sixty-four
   * bits will hold within a few years of now.
   */
  int32_t since_j2000 = unix_seconds - SKY_J2000_EPOCH;
  int32_t days = since_j2000 / SKY_SECONDS_PER_DAY;
  int32_t seconds = since_j2000 % SKY_SECONDS_PER_DAY;

  if (seconds < 0) { /* C rounds a negative division towards zero */
    seconds += SKY_SECONDS_PER_DAY;
    days -= 1;
  }

  int64_t turned = SKY_SIDEREAL_AT_EPOCH + (int64_t)days * SKY_SIDEREAL_PER_DAY +
                   ((int64_t)seconds * SKY_SIDEREAL_PER_DAY) / SKY_SECONDS_PER_DAY;

  /* a full turn is a power of two, so this wraps with a mask */
  return (int32_t)((turned / SKY_SIDEREAL_SCALE) & (TRIG_MAX_ANGLE - 1));
}

SkyObserver sky_observer_at(int32_t unix_seconds, int16_t latitude_hundredths,
                            int16_t longitude_hundredths) {
  int32_t latitude =
      ((int32_t)latitude_hundredths * SKY_DEGREE_HUNDREDTHS_TO_TRIG) / SKY_SIDEREAL_SCALE;
  int32_t longitude =
      ((int32_t)longitude_hundredths * SKY_DEGREE_HUNDREDTHS_TO_TRIG) / SKY_SIDEREAL_SCALE;

  SkyObserver observer = {
      .sin_latitude = sin_lookup(latitude),
      .cos_latitude = cos_lookup(latitude),
      .sidereal = sky_sidereal_time(unix_seconds) + longitude,
  };
  return observer;
}

SkyAltAz sky_alt_az(uint16_t ra, int16_t dec, const SkyObserver *observer) {
  int32_t hour_angle = (observer->sidereal - (int32_t)ra) & (TRIG_MAX_ANGLE - 1);

  int32_t sin_dec = sin_lookup(dec);
  int32_t cos_dec = cos_lookup(dec);
  int32_t sin_hour = sin_lookup(hour_angle);
  int32_t cos_hour = cos_lookup(hour_angle);

  /*
   * The direction of the body in the observer's own frame, as a unit vector:
   * x towards the horizon due north, y towards the east, z straight up. Working
   * this out rather than reaching for asin is what keeps everything in
   * integers, since the SDK has an atan2 lookup and no asin.
   */
  int32_t x = mul16(sin_dec, observer->cos_latitude) -
              mul16(mul16(cos_dec, observer->sin_latitude), cos_hour);
  int32_t y = -mul16(cos_dec, sin_hour);
  int32_t z = mul16(sin_dec, observer->sin_latitude) +
              mul16(mul16(cos_dec, observer->cos_latitude), cos_hour);

  /*
   * atan2_lookup takes sixteen-bit arguments and only cares about the ratio, so
   * everything is brought down by the same two bits first. Squaring them for
   * the horizontal distance would otherwise run past what thirty-two bits hold.
   */
  int32_t small_x = x >> 2;
  int32_t small_y = y >> 2;
  int32_t small_z = z >> 2;
  uint32_t horizontal =
      isqrt((uint32_t)(small_x * small_x) + (uint32_t)(small_y * small_y));

  SkyAltAz position = {
      .azimuth = atan2_lookup((int16_t)small_y, (int16_t)small_x) &
                 (TRIG_MAX_ANGLE - 1),
      .altitude = atan2_lookup((int16_t)small_z, (int16_t)horizontal),
  };

  /* atan2 comes back going the long way round for a body below the horizon */
  if (position.altitude > TRIG_MAX_ANGLE / 2) {
    position.altitude -= TRIG_MAX_ANGLE;
  }
  return position;
}

int32_t sky_radius_for(int32_t altitude, int16_t horizon_radius) {
  /* straight up is the middle and the horizon is the rim */
  return ((int32_t)horizon_radius * (SKY_QUARTER_TURN - altitude)) /
         SKY_QUARTER_TURN;
}

/*
 * Sixty-fourths of a pixel, which the radius is carried in on its way to a
 * point. Rounding it to whole pixels first and then rounding again after the
 * trigonometry threw away enough to move things a couple of pixels; keeping the
 * fraction through both costs nothing and brings it under a tenth of one.
 */
#define SKY_SUBPIXEL_BITS 6

/* shift back down, rounding to nearest rather than towards the floor */
static int16_t rounded_shift(int32_t value, int bits) {
  return (int16_t)((value + (1L << (bits - 1))) >> bits);
}

SkyPoint sky_project(SkyAltAz position, const SkyLayout *layout) {
  int32_t radius =
      (((int32_t)layout->horizon_radius << SKY_SUBPIXEL_BITS) *
       (SKY_QUARTER_TURN - position.altitude)) /
      SKY_QUARTER_TURN;

  /*
   * The chart reads as though you were lying on your back looking up, which puts
   * east to the left of north: the way round a sky chart goes, and the opposite
   * of a map.
   */
  int32_t zero = layout->north_up ? SKY_QUARTER_TURN : -SKY_QUARTER_TURN;
  int32_t direction = layout->horizontal_flip ? 1 : -1;
  int32_t angle = (zero + direction * position.azimuth) & (TRIG_MAX_ANGLE - 1);

  /* the trig ratios are sixteen-bit, so this comes back down by that and the
     sub-pixel bits together */
  const int bits = 16 + SKY_SUBPIXEL_BITS;
  SkyPoint point = {
      .x = (int16_t)(layout->centre_x +
                     rounded_shift(radius * cos_lookup(angle), bits)),
      /* subtracted because a screen counts downwards */
      .y = (int16_t)(layout->centre_y -
                     rounded_shift(radius * sin_lookup(angle), bits)),
  };
  return point;
}
