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

/* how far outside the horizon the compass letters sit, in degrees of altitude */
#define COMPASS_OFFSET (-7)

/*
 * A screen this wide or wider gets the larger lettering.
 *
 * Pebble made screens from 144 to 260 pixels across, and type chosen to suit
 * the smallest is lost on the largest: on a Pebble Time 2 the time came out
 * looking like a caption. There are only two sizes here because there are only
 * really two sizes of Pebble.
 */
#define WIDE_SCREEN 180

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

/* worked out once from whatever screen this turns out to be on */
static GFont s_compass_font;
static GFont s_time_font;
static GFont s_date_font;
static int16_t s_compass_box;
static int16_t s_date_height;
static GSize s_time_box;

static Window *s_window;
static Layer *s_chart;
static SkyData s_sky;
static SkyLayout s_layout;
static bool s_show_stars = true;

/* which pieces of a split payload have turned up, one bit each */
static uint32_t s_pieces_wanted;
static uint32_t s_pieces_seen;

#ifdef PBL_COLOR
/*
 * The same colors as everywhere else, as near as sixty-four of them get.
 *
 * Only on a screen that has them. A black and white watch draws every body
 * white and tells them apart by size, so naming colors there would be a table
 * nothing reads.
 */
static const GColor BODY_COLORS[SKY_BODY_COUNT] = {
    {.argb = GColorYellowARGB8},       /* Sun */
    {.argb = GColorMelonARGB8},        /* Mercury */
    {.argb = GColorRajahARGB8},        /* Venus */
    {.argb = GColorLightGrayARGB8},    /* Moon */
    {.argb = GColorRedARGB8},          /* Mars */
    {.argb = GColorWindsorTanARGB8},   /* Jupiter */
    {.argb = GColorPastelYellowARGB8}, /* Saturn */
    {.argb = GColorCelesteARGB8},      /* Uranus */
    {.argb = GColorBlueMoonARGB8},     /* Neptune */
};
#endif

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

  /*
   * No rings of equal altitude here, unlike the full-size chart. There is only
   * so much room, and the Sun's paths say more about the season than a ring at
   * thirty degrees says about anything.
   */
  graphics_context_set_stroke_color(ctx, GColorWhite);
  graphics_context_set_stroke_width(ctx, 2);
  graphics_draw_circle(ctx, centre, s_layout.horizon_radius);
}

static void draw_arc_segment(GContext *ctx, SkyPathPoint from, SkyPathPoint to);

/*
 * The Sun's daily curves: where it went at the solstices, and where it goes
 * today.
 *
 * These arrive as azimuth and altitude, so they need no rotating -- a day's
 * track is where the Sun will be all day, not where it is now. A segment with
 * an end below the horizon is cut short at it rather than dropped, so the curve
 * meets the rim where the Sun rises and sets instead of stopping short.
 */
static void draw_sun_paths(GContext *ctx) {
  for (uint8_t path = 0; path < s_sky.path_count; path++) {
    uint8_t kind = sky_data_path_kind(&s_sky, path);

    GColor color = GColorWhite;
#ifdef PBL_COLOR
    if (kind == SKY_PATH_WINTER) {
      color = GColorPictonBlue;
    } else if (kind == SKY_PATH_SUMMER) {
      color = GColorScreaminGreen;
    } else {
      /* the Sun's own color, so today's track is not mistaken for the horizon,
         which is the other white circle of about that size */
      color = GColorYellow;
    }
#endif
    graphics_context_set_stroke_color(ctx, color);
    graphics_context_set_stroke_width(ctx, kind == SKY_PATH_TODAY ? 2 : 1);

    SkyPathPoint previous = sky_data_path_point(&s_sky, path, 0);
    for (uint8_t point = 1; point < s_sky.path_points; point++) {
      SkyPathPoint next = sky_data_path_point(&s_sky, path, point);

      /* on a screen with no colors, the solstices are dotted instead */
      bool skip = PBL_IF_COLOR_ELSE(false, kind != SKY_PATH_TODAY && (point & 1));
      if (!skip) {
        draw_arc_segment(ctx, previous, next);
      }
      previous = next;
    }
  }
}

/* One piece of a daily curve, cut off where it dips below the horizon. */
static void draw_arc_segment(GContext *ctx, SkyPathPoint from,
                             SkyPathPoint to) {
  int32_t first = from.altitude;
  int32_t second = to.altitude;
  if (first < 0 && second < 0) {
    return;
  }

  SkyAltAz start = {.azimuth = from.azimuth, .altitude = first};
  SkyAltAz end = {.azimuth = to.azimuth, .altitude = second};

  /* where one end has set, walk it up the segment to the horizon */
  if (first < 0 || second < 0) {
    int32_t span = second - first;
    if (span != 0) {
      int32_t along = (-first * TRIG_MAX_ANGLE) / span; /* fraction, in 1/65536 */
      int32_t sweep = (int32_t)to.azimuth - (int32_t)from.azimuth;
      if (sweep > TRIG_MAX_ANGLE / 2) {
        sweep -= TRIG_MAX_ANGLE;
      } else if (sweep < -TRIG_MAX_ANGLE / 2) {
        sweep += TRIG_MAX_ANGLE;
      }
      SkyAltAz crossing = {
          .azimuth = from.azimuth + (sweep * along) / TRIG_MAX_ANGLE,
          .altitude = 0,
      };
      if (first < 0) {
        start = crossing;
      } else {
        end = crossing;
      }
    }
  }

  SkyPoint a = sky_project(start, &s_layout);
  SkyPoint b = sky_project(end, &s_layout);
  graphics_draw_line(ctx, GPoint(a.x, a.y), GPoint(b.x, b.y));
}

static void draw_compass(GContext *ctx) {
  static const char *const NAMES[] = {"N", "E", "S", "W"};

  graphics_context_set_text_color(ctx, GColorWhite);
  for (int quarter = 0; quarter < 4; quarter++) {
    SkyAltAz at = {
        .azimuth = quarter * TRIG_MAX_ANGLE / 4,
        .altitude = COMPASS_OFFSET * SKY_QUARTER_TURN / 90,
    };
    SkyPoint point = sky_project(at, &s_layout);
    GRect box = GRect(point.x - s_compass_box / 2,
                      point.y - s_compass_box / 2 - 1, s_compass_box,
                      s_compass_box);
    graphics_draw_text(ctx, NAMES[quarter], s_compass_font, box,
                       GTextOverflowModeTrailingEllipsis, GTextAlignmentCenter,
                       NULL);
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
    graphics_context_set_fill_color(
        ctx, PBL_IF_COLOR_ELSE(BODY_COLORS[body.body], GColorWhite));
    graphics_fill_circle(ctx, at, radius);
    /* a ring, so a pale planet is still visible against a lit star field */
    graphics_context_set_stroke_color(ctx, GColorBlack);
    graphics_context_set_stroke_width(ctx, 1);
    graphics_draw_circle(ctx, at, radius);
  }
}

static void draw_time(GContext *ctx) {
  static char clock[8];
  static char date[16];
  time_t now = time(NULL);
  struct tm *local = localtime(&now);
  strftime(clock, sizeof(clock), clock_is_24h_style() ? "%H:%M" : "%I:%M", local);
  strftime(date, sizeof(date), "%a %e %b", local);

  /*
   * Below the middle rather than on it. The middle is the zenith, and the Sun
   * spends the day across the top of the chart in the northern hemisphere, so
   * the time sat there was in the way of the one line most worth seeing.
   */
  int16_t top = s_layout.centre_y - s_time_box.h / 2 + s_time_box.h / 2;
  GRect box = GRect(s_layout.centre_x - s_time_box.w / 2, top, s_time_box.w,
                    s_time_box.h);
  GRect under = GRect(box.origin.x, box.origin.y + s_time_box.h - 2,
                      s_time_box.w, s_date_height);

  /* a patch of night behind them, so the stars do not read through the numbers */
  graphics_context_set_fill_color(ctx, GColorBlack);
  graphics_fill_rect(ctx, grect_inset(box, GEdgeInsets(3, 6)), 4, GCornersAll);
  graphics_fill_rect(ctx, grect_inset(under, GEdgeInsets(1, 6)), 4, GCornersAll);

  graphics_context_set_text_color(ctx, GColorWhite);
  graphics_draw_text(ctx, clock, s_time_font, box,
                     GTextOverflowModeTrailingEllipsis, GTextAlignmentCenter,
                     NULL);

  graphics_context_set_text_color(ctx,
                                  PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));
  graphics_draw_text(ctx, date, s_date_font, under,
                     GTextOverflowModeTrailingEllipsis, GTextAlignmentCenter,
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
  draw_sun_paths(ctx);
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

  /*
   * Everything is measured off the screen rather than fixed, because these run
   * from 144 to 260 pixels across and lettering picked for one looks wrong on
   * the other. The margin is whatever the compass letters need, since they are
   * the only thing drawn outside the horizon.
   */
  bool wide = bounds.size.w >= WIDE_SCREEN;
  s_compass_font = fonts_get_system_font(wide ? FONT_KEY_GOTHIC_24_BOLD
                                              : FONT_KEY_GOTHIC_14);
  s_time_font = fonts_get_system_font(wide ? FONT_KEY_BITHAM_42_BOLD
                                           : FONT_KEY_GOTHIC_28_BOLD);
  s_date_font = fonts_get_system_font(wide ? FONT_KEY_GOTHIC_18
                                           : FONT_KEY_GOTHIC_14);
  s_compass_box = wide ? 26 : 16;
  s_date_height = wide ? 22 : 17;
  s_time_box = wide ? GSize(120, 48) : GSize(80, 34);

  int16_t across = bounds.size.w < bounds.size.h ? bounds.size.w : bounds.size.h;
  s_layout.centre_x = bounds.size.w / 2;
  s_layout.centre_y = bounds.size.h / 2;
  s_layout.horizon_radius = across / 2 - s_compass_box / 2 - 3;

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
