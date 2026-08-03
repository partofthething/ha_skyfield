/*
 * Stand-ins for the Pebble SDK's trigonometry, so the watch face's projection
 * can be compiled and checked on a desktop.
 *
 * These are exact where the SDK's are a table with interpolation, so what this
 * proves is that the formulae in projection.c are right -- not that the SDK's
 * table is precise enough. The table is good to about a part in ten thousand,
 * which on a 180 pixel watch is a hundredth of a pixel.
 */

#include <math.h>
#include <stdint.h>

#define TRIG_MAX_ANGLE 0x10000
#define TRIG_MAX_RATIO 0xffff

static double radians(int32_t angle) {
  return (double)angle * 2.0 * M_PI / (double)TRIG_MAX_ANGLE;
}

int32_t sin_lookup(int32_t angle) {
  return (int32_t)lround(sin(radians(angle)) * TRIG_MAX_RATIO);
}

int32_t cos_lookup(int32_t angle) {
  return (int32_t)lround(cos(radians(angle)) * TRIG_MAX_RATIO);
}

int32_t atan2_lookup(int16_t y, int16_t x) {
  double angle = atan2((double)y, (double)x);
  int32_t units = (int32_t)lround(angle * TRIG_MAX_ANGLE / (2.0 * M_PI));
  return units & (TRIG_MAX_ANGLE - 1);
}
