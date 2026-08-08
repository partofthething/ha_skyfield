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

/* how much night to leave around the time and date */
#define TIME_PAD_X 5
#define TIME_PAD_Y 2

/* how far the corner readings sit from the edge of the screen */
#define STATUS_MARGIN 4

/* between an icon and the number it belongs to */
#define ICON_GAP 3

/* the little drawn icons, in pixels. No resources: a walking figure at this
 * size is a dozen lines of arithmetic, and a PNG of it is a file to keep. */
#define ICON_H 11
#define WALK_W 9
#define HEART_W 11
#define WEATHER_W 15
#define WEATHER_H 13

/* below this the battery reading turns red */
#define BATTERY_LOW 20

/*
 * How old a temperature may get before it stops being shown.
 *
 * Weather is the one reading here that the watch cannot take for itself, so it
 * is also the only one that can go quietly wrong -- a number from yesterday
 * looks exactly like a number from just now.
 */
#define WEATHER_STALE_SECONDS (4 * 60 * 60)

/* what the phone boils a forecast down to, so the watch need not know the
 * vocabulary of whatever service it came from */
enum {
  WEATHER_UNKNOWN = 0,
  WEATHER_CLEAR_DAY = 1,
  WEATHER_CLEAR_NIGHT = 2,
  WEATHER_PARTLY = 3,
  WEATHER_CLOUDY = 4,
  WEATHER_RAIN = 5,
  WEATHER_SNOW = 6,
  WEATHER_THUNDER = 7,
  WEATHER_FOG = 8,
};

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
  MESSAGE_SHOW_BATTERY = 4,
  MESSAGE_SHOW_STEPS = 5,
  MESSAGE_SHOW_HEART = 6,
  MESSAGE_SHOW_WEATHER = 7,
  MESSAGE_WEATHER_TEMPERATURE = 8,
  MESSAGE_WEATHER_CONDITION = 9,
};

enum {
  SETTING_NORTH_UP = 1,
  SETTING_HORIZONTAL_FLIP = 2,
  SETTING_SHOW_STARS = 3,
  SETTING_SHOW_BATTERY = 4,
  SETTING_SHOW_STEPS = 5,
  SETTING_SHOW_HEART = 6,
  SETTING_SHOW_WEATHER = 7,
  SETTING_WEATHER_TEMPERATURE = 8,
  SETTING_WEATHER_CONDITION = 9,
  SETTING_WEATHER_TAKEN = 10,
};

/* worked out once from whatever screen this turns out to be on */
static GFont s_compass_font;
static GFont s_time_font;
static GFont s_date_font;
static int16_t s_compass_box;
static int16_t s_status_height;

static Window *s_window;
static Layer *s_chart;
static SkyData s_sky;
static SkyLayout s_layout;
static bool s_show_stars = true;
static bool s_show_battery = true;
static bool s_show_steps = true;
static bool s_show_heart = true;
/* off until asked for: it is the one reading that costs a fetch, and the phone
   has to be told where you are to make it */
static bool s_show_weather = false;

/* the last thing the phone said about the weather, and when it said it */
static int16_t s_temperature;
static uint8_t s_condition = WEATHER_UNKNOWN;
static int32_t s_weather_taken;

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

  Tuple *battery = dict_find(received, MESSAGE_SHOW_BATTERY);
  if (battery) {
    s_show_battery = battery->value->int32 != 0;
    persist_write_bool(SETTING_SHOW_BATTERY, s_show_battery);
    layer_mark_dirty(s_chart);
  }

  Tuple *steps = dict_find(received, MESSAGE_SHOW_STEPS);
  if (steps) {
    s_show_steps = steps->value->int32 != 0;
    persist_write_bool(SETTING_SHOW_STEPS, s_show_steps);
    layer_mark_dirty(s_chart);
  }

  Tuple *heart = dict_find(received, MESSAGE_SHOW_HEART);
  if (heart) {
    s_show_heart = heart->value->int32 != 0;
    persist_write_bool(SETTING_SHOW_HEART, s_show_heart);
    layer_mark_dirty(s_chart);
  }

  Tuple *weather = dict_find(received, MESSAGE_SHOW_WEATHER);
  if (weather) {
    s_show_weather = weather->value->int32 != 0;
    persist_write_bool(SETTING_SHOW_WEATHER, s_show_weather);
    layer_mark_dirty(s_chart);
  }

  /*
   * A temperature and a condition arrive together or not at all, and the clock
   * reading is the watch's own: the phone's idea of the time is no use for
   * deciding whether what it just sent has gone stale.
   */
  Tuple *degrees = dict_find(received, MESSAGE_WEATHER_TEMPERATURE);
  Tuple *condition = dict_find(received, MESSAGE_WEATHER_CONDITION);
  if (degrees && condition) {
    s_temperature = (int16_t)degrees->value->int32;
    s_condition = (uint8_t)condition->value->int32;
    s_weather_taken = (int32_t)time(NULL);
    persist_write_int(SETTING_WEATHER_TEMPERATURE, s_temperature);
    persist_write_int(SETTING_WEATHER_CONDITION, s_condition);
    persist_write_int(SETTING_WEATHER_TAKEN, s_weather_taken);
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
    /* all three the same weight: today's track is told apart by its color, and
       a fatter line only smudged the one curve worth reading closely */
    graphics_context_set_stroke_color(ctx, color);
    graphics_context_set_stroke_width(ctx, 1);

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
  graphics_context_set_stroke_color(ctx,
                                    PBL_IF_COLOR_ELSE(GColorDarkGray, GColorWhite));
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

  /* grey rather than white, on a screen that can tell the difference: the stars
     are the background of this chart and the planets are the subject, and white
     dots everywhere left nothing for the Sun and the planets to stand out from.
     The darker of the two greys, which is as far down as sixty-four colours go
     before black. */
  graphics_context_set_fill_color(ctx,
                                  PBL_IF_COLOR_ELSE(GColorDarkGray, GColorWhite));
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

/* the patch of night a piece of lettering sits on */
static GRect night_behind(GRect text) {
  return GRect(text.origin.x - TIME_PAD_X, text.origin.y + TIME_PAD_Y,
               text.size.w + 2 * TIME_PAD_X, text.size.h - 2 * TIME_PAD_Y);
}

static void draw_time(GContext *ctx, GRect bounds) {
  static char clock[8];
  static char date[16];
  time_t now = time(NULL);
  struct tm *local = localtime(&now);
  strftime(clock, sizeof(clock), clock_is_24h_style() ? "%H:%M" : "%I:%M", local);
  strftime(date, sizeof(date), "%a %e %b", local);

  /*
   * Measured, not guessed at. Digits are not all one width, so a box cut to fit
   * 08:20 loses the minutes off 18:44 to an ellipsis. Asking the layout engine
   * costs a few microseconds once a minute and fits whatever the hour is, and
   * it means the patch of night behind the numbers is only as wide as they are.
   */
  GSize clock_size = graphics_text_layout_get_content_size(
      clock, s_time_font, bounds, GTextOverflowModeWordWrap, GTextAlignmentCenter);
  GSize date_size = graphics_text_layout_get_content_size(
      date, s_date_font, bounds, GTextOverflowModeWordWrap, GTextAlignmentCenter);

  /*
   * Below the middle rather than on it. The middle is the zenith, and the Sun
   * spends the day across the top of the chart in the northern hemisphere, so
   * the time sat there was in the way of the one line most worth seeing.
   */
  GRect box = GRect(s_layout.centre_x - clock_size.w / 2, s_layout.centre_y,
                    clock_size.w, clock_size.h);
  GRect under = GRect(s_layout.centre_x - date_size.w / 2,
                      box.origin.y + clock_size.h - 2, date_size.w, date_size.h);

  /* a patch of night behind them, so the stars do not read through the numbers */
  graphics_context_set_fill_color(ctx, GColorBlack);
  graphics_fill_rect(ctx, night_behind(box), 4, GCornersAll);
  graphics_fill_rect(ctx, night_behind(under), 4, GCornersAll);

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

/* --------------------------------------------------------------------- icons */

#ifdef PBL_RECT

/*
 * A walking figure, in a WALK_W by ICON_H box with its top left at `at`.
 *
 * The head is a three pixel dot rather than a five pixel one. At five it is
 * nearly half the height of the whole figure, and what the eye makes of that is
 * not a person walking but a smudge with legs. The limbs are deliberately
 * uneven -- one arm forward and low, one back and high, one leg mid-stride --
 * because a symmetrical figure at this size reads as a star, not a stride.
 */
static void draw_walk_icon(GContext *ctx, GPoint at) {
  GColor color = PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite);
  graphics_context_set_fill_color(ctx, color);
  graphics_context_set_stroke_color(ctx, color);
  graphics_context_set_stroke_width(ctx, 1);

  graphics_fill_circle(ctx, GPoint(at.x + 4, at.y + 1), 1);        /* head */
  graphics_draw_line(ctx, GPoint(at.x + 4, at.y + 3),
                     GPoint(at.x + 4, at.y + 6));                  /* body */
  graphics_draw_line(ctx, GPoint(at.x + 4, at.y + 4),
                     GPoint(at.x + 1, at.y + 5));                  /* back arm */
  graphics_draw_line(ctx, GPoint(at.x + 4, at.y + 4),
                     GPoint(at.x + 7, at.y + 6));                  /* front arm */
  graphics_draw_line(ctx, GPoint(at.x + 4, at.y + 6),
                     GPoint(at.x + 1, at.y + 10));                 /* trailing leg */
  graphics_draw_line(ctx, GPoint(at.x + 4, at.y + 6),
                     GPoint(at.x + 6, at.y + 8));                  /* leading thigh */
  graphics_draw_line(ctx, GPoint(at.x + 6, at.y + 8),
                     GPoint(at.x + 7, at.y + 10));                 /* and its shin */
}

/*
 * A heart: two lobes and a point.
 *
 * The point is five rows of line, each a pixel shorter at each end than the one
 * above, which is what a filled triangle is when the SDK will not fill one for
 * you without a GPath to keep.
 */
static void draw_heart_icon(GContext *ctx, GPoint at) {
  GColor color = PBL_IF_COLOR_ELSE(GColorRed, GColorWhite);
  graphics_context_set_fill_color(ctx, color);
  graphics_context_set_stroke_color(ctx, color);
  graphics_context_set_stroke_width(ctx, 1);

  graphics_fill_circle(ctx, GPoint(at.x + 3, at.y + 4), 2);
  graphics_fill_circle(ctx, GPoint(at.x + 7, at.y + 4), 2);
  for (int16_t row = 0; row < 5; row++) {
    graphics_draw_line(ctx, GPoint(at.x + 1 + row, at.y + 5 + row),
                       GPoint(at.x + 9 - row, at.y + 5 + row));
  }
}

/* The cloud the wet conditions are all built on, low in a WEATHER_W box. */
static void draw_cloud(GContext *ctx, GPoint at) {
  graphics_context_set_fill_color(ctx,
                                  PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite));
  graphics_fill_circle(ctx, GPoint(at.x + 4, at.y + 6), 3);
  graphics_fill_circle(ctx, GPoint(at.x + 8, at.y + 5), 4);
  graphics_fill_circle(ctx, GPoint(at.x + 11, at.y + 6), 3);
  graphics_fill_rect(ctx, GRect(at.x + 4, at.y + 6, 8, 3), 0, GCornerNone);
}

/*
 * Whatever the phone made of the forecast, in a WEATHER_W by WEATHER_H box.
 *
 * Eight of them, which is as many as can be told apart at this size. Anything
 * finer -- light rain against heavy -- is a distinction the pixels cannot make.
 */
static void draw_weather_icon(GContext *ctx, GPoint at, uint8_t condition) {
  GColor sun = PBL_IF_COLOR_ELSE(GColorYellow, GColorWhite);
  GColor wet = PBL_IF_COLOR_ELSE(GColorPictonBlue, GColorWhite);
  GColor pale = PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite);

  graphics_context_set_stroke_width(ctx, 1);

  switch (condition) {
    case WEATHER_CLEAR_DAY:
      graphics_context_set_fill_color(ctx, sun);
      graphics_fill_circle(ctx, GPoint(at.x + 7, at.y + 6), 4);
      graphics_context_set_stroke_color(ctx, sun);
      graphics_draw_line(ctx, GPoint(at.x + 7, at.y), GPoint(at.x + 7, at.y + 1));
      graphics_draw_line(ctx, GPoint(at.x + 7, at.y + 11),
                         GPoint(at.x + 7, at.y + 12));
      graphics_draw_line(ctx, GPoint(at.x, at.y + 6), GPoint(at.x + 1, at.y + 6));
      graphics_draw_line(ctx, GPoint(at.x + 13, at.y + 6),
                         GPoint(at.x + 14, at.y + 6));
      break;

    case WEATHER_CLEAR_NIGHT:
      /* a crescent is a disc with a second disc taken out of it, and taking it
         out is drawing it again in the colour of the night behind */
      graphics_context_set_fill_color(ctx, pale);
      graphics_fill_circle(ctx, GPoint(at.x + 7, at.y + 6), 5);
      graphics_context_set_fill_color(ctx, GColorBlack);
      graphics_fill_circle(ctx, GPoint(at.x + 10, at.y + 4), 5);
      break;

    case WEATHER_PARTLY:
      graphics_context_set_fill_color(ctx, sun);
      graphics_fill_circle(ctx, GPoint(at.x + 5, at.y + 4), 3);
      draw_cloud(ctx, GPoint(at.x + 2, at.y + 2));
      break;

    case WEATHER_CLOUDY:
      draw_cloud(ctx, at);
      break;

    case WEATHER_RAIN:
      draw_cloud(ctx, at);
      graphics_context_set_stroke_color(ctx, wet);
      for (int16_t drop = 0; drop < 3; drop++) {
        int16_t x = at.x + 4 + drop * 4;
        graphics_draw_line(ctx, GPoint(x, at.y + 9), GPoint(x - 1, at.y + 12));
      }
      break;

    case WEATHER_SNOW:
      draw_cloud(ctx, at);
      graphics_context_set_fill_color(ctx, PBL_IF_COLOR_ELSE(GColorWhite, GColorWhite));
      for (int16_t flake = 0; flake < 3; flake++) {
        graphics_fill_circle(ctx, GPoint(at.x + 4 + flake * 4, at.y + 11), 1);
      }
      break;

    case WEATHER_THUNDER:
      draw_cloud(ctx, at);
      graphics_context_set_stroke_color(ctx, sun);
      graphics_draw_line(ctx, GPoint(at.x + 8, at.y + 9), GPoint(at.x + 6, at.y + 11));
      graphics_draw_line(ctx, GPoint(at.x + 6, at.y + 11), GPoint(at.x + 9, at.y + 10));
      graphics_draw_line(ctx, GPoint(at.x + 9, at.y + 10), GPoint(at.x + 6, at.y + 13));
      break;

    case WEATHER_FOG:
      graphics_context_set_stroke_color(ctx, pale);
      for (int16_t bar = 0; bar < 3; bar++) {
        int16_t y = at.y + 3 + bar * 3;
        graphics_draw_line(ctx, GPoint(at.x + 1 + (bar & 1) * 2, y),
                           GPoint(at.x + 12 - (bar & 1) * 2, y));
      }
      break;

    default:
      break; /* nothing worth drawing; the temperature stands on its own */
  }
}

/* ------------------------------------------------------------- the corners */

typedef void (*IconDraw)(GContext *ctx, GPoint at);

/*
 * An icon and the number it belongs to, pinned to one end of a slot.
 *
 * The icon leads on the outside of the pair, against the edge of the screen,
 * because that is the end the eye arrives at on that side of the face.
 */
static void draw_reading(GContext *ctx, GRect slot, IconDraw icon, int16_t icon_w,
                         int16_t icon_h, const char *text, GColor color,
                         GTextAlignment side) {
  GSize size = graphics_text_layout_get_content_size(
      text, s_date_font, slot, GTextOverflowModeWordWrap, GTextAlignmentLeft);

  int16_t width = icon_w + ICON_GAP + size.w;
  int16_t left = (side == GTextAlignmentLeft)
                     ? slot.origin.x
                     : slot.origin.x + slot.size.w - width;
  int16_t icon_x = (side == GTextAlignmentLeft) ? left : left + size.w + ICON_GAP;
  int16_t text_x = (side == GTextAlignmentLeft) ? left + icon_w + ICON_GAP : left;

  icon(ctx, GPoint(icon_x, slot.origin.y + (slot.size.h - icon_h) / 2));

  graphics_context_set_text_color(ctx, color);
  graphics_draw_text(ctx, text, s_date_font,
                     GRect(text_x, slot.origin.y, size.w + 2, slot.size.h),
                     GTextOverflowModeTrailingEllipsis, GTextAlignmentLeft, NULL);
}

/* draw_reading wants a plain icon function, and the weather's takes a condition */
static void draw_current_weather_icon(GContext *ctx, GPoint at) {
  draw_weather_icon(ctx, at, s_condition);
}

#endif /* PBL_RECT */

/*
 * Steps and battery along the top, heart rate and weather along the bottom.
 *
 * Only on a screen with corners. The horizon is a circle drawn as large as the
 * screen will take, so on a rectangular one the corners are the only space that
 * costs nothing to write in -- and on a round one there is no such space at all.
 *
 * Every one of these is read rather than asked for. Nothing here subscribes to
 * anything or sets a sampling rate; the face redraws once a minute for the sky
 * anyway, and takes whatever the watch happens to already know at that moment.
 */
static void draw_status(GContext *ctx, GRect bounds) {
#ifdef PBL_RECT
  GRect top =
      GRect(bounds.origin.x + STATUS_MARGIN, bounds.origin.y + STATUS_MARGIN,
            bounds.size.w - 2 * STATUS_MARGIN, s_status_height);
  GRect bottom = GRect(top.origin.x,
                       bounds.origin.y + bounds.size.h - STATUS_MARGIN -
                           s_status_height,
                       top.size.w, s_status_height);
  GColor pale = PBL_IF_COLOR_ELSE(GColorLightGray, GColorWhite);

#ifdef PBL_HEALTH
  if (s_show_steps &&
      (health_service_metric_accessible(HealthMetricStepCount,
                                        time_start_of_today(), time(NULL)) &
       HealthServiceAccessibilityMaskAvailable)) {
    static char steps[8];
    int count = (int)health_service_sum_today(HealthMetricStepCount);
    /* five digits do not fit beside the compass, so past ten thousand it counts
       in thousands instead */
    if (count >= 10000) {
      snprintf(steps, sizeof(steps), "%d.%dk", count / 1000, (count % 1000) / 100);
    } else {
      snprintf(steps, sizeof(steps), "%d", count);
    }
    draw_reading(ctx, top, draw_walk_icon, WALK_W, ICON_H, steps, pale,
                 GTextAlignmentLeft);
  }

  /*
   * The last heart rate the watch took of its own accord.
   *
   * peek_current_value only reads what is already there. The call that would
   * make the sensor run more often is health_service_set_heart_rate_sample_period,
   * and this face deliberately never makes it: a watch face is not worth a
   * shortened day of battery, and the firmware's own rate is what the wearer
   * chose in the health settings.
   */
  if (s_show_heart) {
    int bpm = (int)health_service_peek_current_value(HealthMetricHeartRateBPM);
    if (bpm > 0) {
      static char beats[8];
      snprintf(beats, sizeof(beats), "%d", bpm);
      draw_reading(ctx, bottom, draw_heart_icon, HEART_W, ICON_H, beats, pale,
                   GTextAlignmentLeft);
    }
  }
#endif

  if (s_show_battery) {
    static char charge[8];
    BatteryChargeState battery = battery_state_service_peek();
    snprintf(charge, sizeof(charge), "%d%%", battery.charge_percent);

    GColor color = pale;
#ifdef PBL_COLOR
    if (battery.is_charging || battery.is_plugged) {
      color = GColorScreaminGreen;
    } else if (battery.charge_percent <= BATTERY_LOW) {
      color = GColorRed;
    }
#endif
    graphics_context_set_text_color(ctx, color);
    graphics_draw_text(ctx, charge, s_date_font, top,
                       GTextOverflowModeTrailingEllipsis, GTextAlignmentRight,
                       NULL);
  }

  if (s_show_weather && s_weather_taken != 0 &&
      (int32_t)time(NULL) - s_weather_taken < WEATHER_STALE_SECONDS) {
    static char degrees[8];
    snprintf(degrees, sizeof(degrees), "%d°", s_temperature);
    draw_reading(ctx, bottom, draw_current_weather_icon, WEATHER_W, WEATHER_H,
                 degrees, pale, GTextAlignmentRight);
  }
#else
  (void)ctx;
  (void)bounds;
#endif
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
  draw_time(ctx, bounds);
  draw_status(ctx, bounds);
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
  /* Bitham 34 rather than 42: the larger one is only digits and a colon wide
     enough that half the hours of the day overran the middle of the chart */
  s_time_font = fonts_get_system_font(wide ? FONT_KEY_BITHAM_34_MEDIUM_NUMBERS
                                           : FONT_KEY_GOTHIC_28_BOLD);
  s_date_font = fonts_get_system_font(wide ? FONT_KEY_GOTHIC_18
                                           : FONT_KEY_GOTHIC_14);
  s_compass_box = wide ? 26 : 16;
  s_status_height = wide ? 22 : 17;

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
  s_show_battery = persist_exists(SETTING_SHOW_BATTERY)
                       ? persist_read_bool(SETTING_SHOW_BATTERY)
                       : true;
  s_show_steps = persist_exists(SETTING_SHOW_STEPS)
                     ? persist_read_bool(SETTING_SHOW_STEPS)
                     : true;
  s_show_heart = persist_exists(SETTING_SHOW_HEART)
                     ? persist_read_bool(SETTING_SHOW_HEART)
                     : true;
  s_show_weather = persist_exists(SETTING_SHOW_WEATHER)
                       ? persist_read_bool(SETTING_SHOW_WEATHER)
                       : false;

  /* the last temperature the phone sent, so a restart is not blank in that
     corner until the next hour comes round. It ages out on its own. */
  if (persist_exists(SETTING_WEATHER_TAKEN)) {
    s_temperature = (int16_t)persist_read_int(SETTING_WEATHER_TEMPERATURE);
    s_condition = (uint8_t)persist_read_int(SETTING_WEATHER_CONDITION);
    s_weather_taken = persist_read_int(SETTING_WEATHER_TAKEN);
  }

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
