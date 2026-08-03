/*
 * A sky chart on a watch face.
 *
 * The sky arrives as right ascension and declination, which do not go stale, and
 * the watch turns it for itself from its own clock. That is the whole design:
 * the radio is what costs battery, so it sleeps, and a few milliseconds of
 * arithmetic once a minute is what buys the silence. It also means the chart
 * stays right when the phone is in another room.
 */

#include "projection.h"
#include "sky_data.h"
#include <pebble.h>

/* how often to redraw: the sky turns a quarter degree a minute */
#define REDRAW_UNIT MINUTE_UNIT

/* how old the sky may get before asking for a fresh one. The planets move
 * slowly and the stars not at all, so twice a day is plenty and is the
 * difference between a watch that lasts a week and one that does not. */
#define REFRESH_SECONDS (12 * 60 * 60)

/* how many points to bend a constellation line along. Fewer than the ten the
 * card and the SVG use: on a screen this size the rest of them land on pixels
 * that are already lit. */
#define POINTS_PER_LINE 4

/* room around the chart, for the compass letters */
#define MARGIN 10

/* persist_write_data will not take more than this at once */
#define PERSIST_CHUNK 256
#define PERSIST_FIRST_KEY 100
#define PERSIST_LENGTH_KEY 99

enum {
  MESSAGE_PAYLOAD = 0,
  MESSAGE_NORTH_UP = 1,
  MESSAGE_HORIZONTAL_FLIP = 2,
  MESSAGE_SHOW_STARS = 3,
};

enum {
  SETTING_NORTH_UP = 1,
  SETTING_HORIZONTAL_FLIP = 2,
  SETTING_SHOW_STARS = 3,
};

static Window *s_window;
static Layer *s_chart;
static SkyData s_sky;
static SkyLayout s_layout;
static bool s_show_stars = true;

/* which pieces of a split payload have turned up, one bit each */
static uint32_t s_pieces_wanted;
static uint32_t s_pieces_seen;

static const GColor *body_colours(void) {
  /* the same colours as everywhere else, as near as sixty-four of them get */
  static GColor colours[SKY_BODY_COUNT];
  colours[0] = GColorYellow;      /* Sun */
  colours[1] = GColorMelon;       /* Mercury */
  colours[2] = GColorRajah;       /* Venus */
  colours[3] = GColorLightGray;   /* Moon */
  colours[4] = GColorRed;         /* Mars */
  colours[5] = GColorWindsorTan;  /* Jupiter */
  colours[6] = GColorPastelYellow;/* Saturn */
  colours[7] = GColorCeleste;     /* Uranus */
  colours[8] = GColorBlueMoon;    /* Neptune */
  return colours;
}

/* ---------------------------------------------------------------- keeping it */

static void save_sky(void) {
  persist_write_int(PERSIST_LENGTH_KEY, s_sky.length);
  for (uint16_t at = 0, key = 0; at < s_sky.length; at += PERSIST_CHUNK, key++) {
    uint16_t piece = s_sky.length - at;
    if (piece > PERSIST_CHUNK) {
      piece = PERSIST_CHUNK;
    }
    persist_write_data(PERSIST_FIRST_KEY + key, &s_sky.bytes[at], piece);
  }
}

static bool load_sky(void) {
  if (!persist_exists(PERSIST_LENGTH_KEY)) {
    return false;
  }
  int32_t length = persist_read_int(PERSIST_LENGTH_KEY);
  if (length <= 0 || length > SKY_MAX_PAYLOAD) {
    return false;
  }

  s_sky.length = (uint16_t)length;
  for (uint16_t at = 0, key = 0; at < s_sky.length; at += PERSIST_CHUNK, key++) {
    uint16_t piece = s_sky.length - at;
    if (piece > PERSIST_CHUNK) {
      piece = PERSIST_CHUNK;
    }
    if (persist_read_data(PERSIST_FIRST_KEY + key, &s_sky.bytes[at], piece) < 0) {
      return false;
    }
  }
  return sky_data_parse(&s_sky);
}

/* ------------------------------------------------------------------ fetching */

static void ask_for_the_sky(void) {
  DictionaryIterator *out;
  if (app_message_outbox_begin(&out) != APP_MSG_OK) {
    return;
  }
  dict_write_uint8(out, MESSAGE_PAYLOAD, 1); /* any value; the asking is the message */
  app_message_outbox_send();
}

static bool the_sky_is_stale(void) {
  if (!s_sky.valid) {
    return true;
  }
  int32_t age = (int32_t)time(NULL) - s_sky.generated;
  return age < 0 || age > REFRESH_SECONDS;
}

static void piece_arrived(const uint8_t *piece, uint16_t size) {
  if (size < 2) {
    return;
  }
  uint8_t index = piece[0];
  uint8_t total = piece[1];
  const uint8_t *content = piece + 2;
  uint16_t length = size - 2;

  if (total == 0 || total > 32 || index >= total) {
    return;
  }

  uint32_t offset = (uint32_t)index * SKY_CHUNK_SIZE;
  if (offset + length > SKY_MAX_PAYLOAD) {
    return;
  }

  if (index == 0 || s_pieces_wanted == 0) {
    /* a fresh payload: forget whatever was half-collected before */
    s_pieces_wanted = (total >= 32) ? 0xffffffffu : ((1u << total) - 1u);
    s_pieces_seen = 0;
  }

  memcpy(&s_sky.bytes[offset], content, length);
  s_pieces_seen |= (1u << index);

  /* the last piece is the short one, so it is what fixes the total length */
  if (index == total - 1) {
    s_sky.length = (uint16_t)(offset + length);
  }

  if (s_pieces_seen != s_pieces_wanted) {
    return;
  }

  if (sky_data_parse(&s_sky)) {
    save_sky();
    layer_mark_dirty(s_chart);
  }
  s_pieces_wanted = 0;
  s_pieces_seen = 0;
}

static void message_arrived(DictionaryIterator *received, void *context) {
  Tuple *payload = dict_find(received, MESSAGE_PAYLOAD);
  if (payload && payload->type == TUPLE_BYTE_ARRAY) {
    piece_arrived(payload->value->data, payload->length);
  }

  Tuple *north_up = dict_find(received, MESSAGE_NORTH_UP);
  if (north_up) {
    s_layout.north_up = north_up->value->int32 != 0;
    persist_write_bool(SETTING_NORTH_UP, s_layout.north_up);
    layer_mark_dirty(s_chart);
  }

  Tuple *flip = dict_find(received, MESSAGE_HORIZONTAL_FLIP);
  if (flip) {
    s_layout.horizontal_flip = flip->value->int32 != 0;
    persist_write_bool(SETTING_HORIZONTAL_FLIP, s_layout.horizontal_flip);
    layer_mark_dirty(s_chart);
  }

  Tuple *stars = dict_find(received, MESSAGE_SHOW_STARS);
  if (stars) {
    s_show_stars = stars->value->int32 != 0;
    persist_write_bool(SETTING_SHOW_STARS, s_show_stars);
    layer_mark_dirty(s_chart);
  }
}

/* ------------------------------------------------------------------- drawing */

static SkyPoint place(uint16_t ra, int16_t dec, const SkyObserver *observer,
                      int32_t *altitude) {
  SkyAltAz position = sky_alt_az(ra, dec, observer);
  if (altitude) {
    *altitude = position.altitude;
  }
  return sky_project(position, &s_layout);
}

static void draw_grid(GContext *ctx) {
  GPoint centre = GPoint(s_layout.centre_x, s_layout.centre_y);

  graphics_context_set_stroke_color(ctx, PBL_IF_COLOR_ELSE(GColorDarkGray, GColorWhite));
  graphics_context_set_stroke_width(ctx, 1);
  /* a ring every thirty degrees, rather than the ten of the full-size chart:
     any more and they close up into a grey disc at this size */
  for (int32_t altitude = 30; altitude < 90; altitude += 30) {
    int32_t radius =
        sky_radius_for(altitude * SKY_QUARTER_TURN / 90, s_layout.horizon_radius);
    graphics_draw_circle(ctx, centre, radius);
  }

  graphics_context_set_stroke_color(ctx, GColorWhite);
  graphics_context_set_stroke_width(ctx, 2);
  graphics_draw_circle(ctx, centre, s_layout.horizon_radius);
}

static void draw_compass(GContext *ctx) {
  static const char *const NAMES[] = {"N", "E", "S", "W"};

  graphics_context_set_text_color(ctx, GColorWhite);
  for (int quarter = 0; quarter < 4; quarter++) {
    SkyAltAz at = {.azimuth = quarter * TRIG_MAX_ANGLE / 4, .altitude = 0};
    SkyPoint point = sky_project(at, &s_layout);
    GRect box = GRect(point.x - 8, point.y - 9, 16, 16);
    graphics_draw_text(ctx, NAMES[quarter],
                       fonts_get_system_font(FONT_KEY_GOTHIC_14),
                       box, GTextOverflowModeTrailingEllipsis,
                       GTextAlignmentCenter, NULL);
  }
}

static void draw_stars(GContext *ctx, const SkyObserver *observer) {
  graphics_context_set_stroke_color(ctx, PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));
  graphics_context_set_stroke_width(ctx, 1);

  /* the joins first, so the stars themselves sit on top of them */
  for (uint16_t index = 0; index < s_sky.line_count; index++) {
    SkyLine line = sky_data_line(&s_sky, index);
    SkyStar from = sky_data_star(&s_sky, line.from);
    SkyStar to = sky_data_star(&s_sky, line.to);

    SkyAltAz start = sky_alt_az(from.ra, from.dec, observer);
    SkyAltAz end = sky_alt_az(to.ra, to.dec, observer);
    if (start.altitude < 0 && end.altitude < 0) {
      continue;
    }

    /* the short way round, rather than the wrong way across the chart */
    int32_t sweep = end.azimuth - start.azimuth;
    if (sweep > TRIG_MAX_ANGLE / 2) {
      sweep -= TRIG_MAX_ANGLE;
    } else if (sweep < -TRIG_MAX_ANGLE / 2) {
      sweep += TRIG_MAX_ANGLE;
    }

    SkyPoint previous = sky_project(start, &s_layout);
    for (int step = 1; step < POINTS_PER_LINE; step++) {
      SkyAltAz along = {
          .azimuth = start.azimuth + sweep * step / (POINTS_PER_LINE - 1),
          .altitude = start.altitude +
                      (end.altitude - start.altitude) * step / (POINTS_PER_LINE - 1),
      };
      SkyPoint next = sky_project(along, &s_layout);
      graphics_draw_line(ctx, GPoint(previous.x, previous.y),
                         GPoint(next.x, next.y));
      previous = next;
    }
  }

  graphics_context_set_fill_color(ctx, GColorWhite);
  for (uint16_t index = 0; index < s_sky.star_count; index++) {
    SkyStar star = sky_data_star(&s_sky, index);
    int32_t altitude;
    SkyPoint point = place(star.ra, star.dec, observer, &altitude);
    if (altitude < 0) {
      continue;
    }
    graphics_fill_circle(ctx, GPoint(point.x, point.y), 1);
  }
}

static void draw_bodies(GContext *ctx, const SkyObserver *observer) {
  const GColor *colours = body_colours();

  for (uint16_t index = 0; index < s_sky.body_count; index++) {
    SkyBody body = sky_data_body(&s_sky, index);
    if (body.body >= SKY_BODY_COUNT) {
      continue;
    }
    int32_t altitude;
    SkyPoint point = place(body.ra, body.dec, observer, &altitude);
    if (altitude < 0) {
      continue; /* below the horizon is behind the Earth */
    }

    GPoint at = GPoint(point.x, point.y);
    uint8_t radius = SKY_BODIES[body.body].radius;
    graphics_context_set_fill_color(ctx, PBL_IF_COLOR_ELSE(colours[body.body], GColorWhite));
    graphics_fill_circle(ctx, at, radius);
    /* a ring, so a pale planet is still visible against a lit star field */
    graphics_context_set_stroke_color(ctx, GColorBlack);
    graphics_context_set_stroke_width(ctx, 1);
    graphics_draw_circle(ctx, at, radius);
  }
}

static void draw_time(GContext *ctx) {
  static char clock[8];
  time_t now = time(NULL);
  strftime(clock, sizeof(clock), clock_is_24h_style() ? "%H:%M" : "%I:%M",
           localtime(&now));

  /* in the middle, which is the zenith, and the emptiest part of most skies */
  GRect box = GRect(s_layout.centre_x - 40, s_layout.centre_y - 21, 80, 34);
  graphics_context_set_fill_color(ctx, GColorBlack);
  graphics_fill_rect(ctx, GRect(box.origin.x + 12, box.origin.y + 4, 56, 26), 4,
                     GCornersAll);
  graphics_context_set_text_color(ctx, GColorWhite);
  graphics_draw_text(ctx, clock, fonts_get_system_font(FONT_KEY_GOTHIC_28_BOLD),
                     box, GTextOverflowModeTrailingEllipsis, GTextAlignmentCenter,
                     NULL);
}

static void draw_waiting(GContext *ctx, GRect bounds) {
  graphics_context_set_text_color(ctx, GColorWhite);
  graphics_draw_text(ctx, "waiting for the sky",
                     fonts_get_system_font(FONT_KEY_GOTHIC_18),
                     GRect(bounds.origin.x, bounds.size.h / 2 - 12, bounds.size.w, 40),
                     GTextOverflowModeWordWrap, GTextAlignmentCenter, NULL);
}

static void draw_chart(Layer *layer, GContext *ctx) {
  GRect bounds = layer_get_bounds(layer);

  graphics_context_set_fill_color(ctx, GColorBlack);
  graphics_fill_rect(ctx, bounds, 0, GCornerNone);

  if (!s_sky.valid) {
    draw_waiting(ctx, bounds);
    return;
  }

  SkyObserver observer =
      sky_observer_at((int32_t)time(NULL), s_sky.latitude, s_sky.longitude);

  draw_grid(ctx);
  if (s_show_stars) {
    draw_stars(ctx, &observer);
  }
  draw_bodies(ctx, &observer);
  draw_compass(ctx);
  draw_time(ctx);
}

/* --------------------------------------------------------------------- ticks */

static void handle_tick(struct tm *now, TimeUnits changed) {
  (void)now;
  (void)changed;
  layer_mark_dirty(s_chart);

  /* asking is the expensive thing, so it happens on a timer of its own */
  if (the_sky_is_stale()) {
    ask_for_the_sky();
  }
}

/* ---------------------------------------------------------------------- setup */

static void window_load(Window *window) {
  Layer *root = window_get_root_layer(window);
  GRect bounds = layer_get_bounds(root);

  int16_t across = bounds.size.w < bounds.size.h ? bounds.size.w : bounds.size.h;
  s_layout.centre_x = bounds.size.w / 2;
  s_layout.centre_y = bounds.size.h / 2;
  s_layout.horizon_radius = across / 2 - MARGIN;

  s_chart = layer_create(bounds);
  layer_set_update_proc(s_chart, draw_chart);
  layer_add_child(root, s_chart);
}

static void window_unload(Window *window) {
  (void)window;
  layer_destroy(s_chart);
}

static void init(void) {
  s_layout.north_up = persist_read_bool(SETTING_NORTH_UP);
  s_layout.horizontal_flip = persist_read_bool(SETTING_HORIZONTAL_FLIP);
  s_show_stars = persist_exists(SETTING_SHOW_STARS)
                     ? persist_read_bool(SETTING_SHOW_STARS)
                     : true;

  /* whatever was on the wrist last time, so there is a sky before the phone
     has said anything and one even if the phone never does */
  load_sky();

  s_window = window_create();
  window_set_background_color(s_window, GColorBlack);
  window_set_window_handlers(s_window, (WindowHandlers){
                                           .load = window_load,
                                           .unload = window_unload,
                                       });
  window_stack_push(s_window, true);

  app_message_register_inbox_received(message_arrived);
  app_message_open(app_message_inbox_size_maximum(),
                   app_message_outbox_size_maximum());

  tick_timer_service_subscribe(REDRAW_UNIT, handle_tick);

  if (the_sky_is_stale()) {
    ask_for_the_sky();
  }
}

static void deinit(void) {
  tick_timer_service_unsubscribe();
  window_destroy(s_window);
}

int main(void) {
  init();
  app_event_loop();
  deinit();
  return 0;
}
