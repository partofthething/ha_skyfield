/*
 * The handful of things the projection needs from its surroundings.
 *
 * On a watch these come from the Pebble SDK, which keeps a table of sines and
 * measures a full turn in 65536 steps. On a desktop they come from libm, so
 * that the projection can be compiled and checked against the Python without a
 * watch in the room -- see custom_components/tests/test_watchface.py.
 */

#pragma once

#ifdef SKY_HOST

#include <stdint.h>

#define TRIG_MAX_ANGLE 0x10000
#define TRIG_MAX_RATIO 0xffff

int32_t sin_lookup(int32_t angle);
int32_t cos_lookup(int32_t angle);
int32_t atan2_lookup(int16_t y, int16_t x);

#else

#include <pebble.h>

#endif
