/*
 * The phone's half of the watch face.
 *
 * Fetches the sky from a skyfield server -- either `skyfield-sky serve` or Home
 * Assistant itself -- and passes it to the watch in pieces small enough for one
 * message. It does as little as it can and as rarely as it can: the watch asks
 * only when what it has is half a day old, because waking the radio is the
 * expensive part of the whole arrangement.
 */

var page = require("./config");

// must match SKY_CHUNK_SIZE in src/c/sky_data.h and pebble.CHUNK_SIZE in Python
var CHUNK_SIZE = 512;

var MESSAGE_PAYLOAD = "PAYLOAD";
var MESSAGE_NORTH_UP = "NORTH_UP";
var MESSAGE_HORIZONTAL_FLIP = "HORIZONTAL_FLIP";
var MESSAGE_SHOW_STARS = "SHOW_STARS";
var MESSAGE_SHOW_BATTERY = "SHOW_BATTERY";
var MESSAGE_SHOW_STEPS = "SHOW_STEPS";
var MESSAGE_SHOW_HEART = "SHOW_HEART";
var MESSAGE_SHOW_WEATHER = "SHOW_WEATHER";
var MESSAGE_WEATHER_TEMPERATURE = "WEATHER_TEMPERATURE";
var MESSAGE_WEATHER_CONDITION = "WEATHER_CONDITION";

var SETTINGS_KEY = "skyfield-settings";

// how long to wait for the phone to work out where it is before giving up and
// letting the server draw wherever it was set up for
var LOCATION_TIMEOUT = 15000;

// how often to ask what the weather is doing. The sky is fetched twice a day
// because it does not change; a temperature does, so it gets a timer of its own
// rather than riding along with the sky.
var WEATHER_INTERVAL = 60 * 60 * 1000;

// Open-Meteo: no key, no account, no terms to agree to, which is why half the
// weather watchfaces on any Pebble store are pointed at it.
var WEATHER_HOST = "https://api.open-meteo.com/v1/forecast";

// the eight conditions the watch knows how to draw, matching the enum at the
// top of src/c/main.c
var WEATHER_UNKNOWN = 0;
var WEATHER_CLEAR_DAY = 1;
var WEATHER_CLEAR_NIGHT = 2;
var WEATHER_PARTLY = 3;
var WEATHER_CLOUDY = 4;
var WEATHER_RAIN = 5;
var WEATHER_SNOW = 6;
var WEATHER_THUNDER = 7;
var WEATHER_FOG = 8;

/*
 * A WMO present-weather code, boiled down to something drawable.
 *
 * The WMO has ninety-nine of these and the watch has eight icons, so this is
 * mostly a flattening: every grade of drizzle, rain, freezing rain and shower
 * lands on one raincloud, because at fifteen pixels the difference between
 * light and heavy rain is a difference that cannot be drawn.
 */
function conditionFor(code, isDay) {
  if (code <= 1) {
    return isDay ? WEATHER_CLEAR_DAY : WEATHER_CLEAR_NIGHT;
  }
  if (code === 2) return WEATHER_PARTLY;
  if (code === 3) return WEATHER_CLOUDY;
  if (code === 45 || code === 48) return WEATHER_FOG;
  if (code >= 95) return WEATHER_THUNDER; // 95, 96, 99: with and without hail
  if ((code >= 71 && code <= 77) || code === 85 || code === 86) return WEATHER_SNOW;
  if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return WEATHER_RAIN;
  return WEATHER_UNKNOWN;
}

function settings() {
  try {
    return JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {};
  } catch (error) {
    return {};
  }
}

function saveSettings(values) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(values));
}

/*
 * Where to fetch from, with whatever is known about the observer.
 *
 * Left to itself the server draws the place it was started for, so coordinates
 * only go on when there are some.
 */
function skyUrl(where) {
  var config = settings();
  var url = (config.serverUrl || "http://127.0.0.1:8099").replace(/\/+$/, "");
  url += "/sky.pebble";

  var query = [];
  if (where && where.latitude !== undefined) {
    query.push("lat=" + encodeURIComponent(where.latitude));
    query.push("lon=" + encodeURIComponent(where.longitude));
  }
  if (config.constellations) {
    query.push("constellations=" + encodeURIComponent(config.constellations));
  }
  return query.length ? url + "?" + query.join("&") : url;
}

/* Hand the watch one piece at a time, each waiting for the last to land. */
function sendPieces(bytes, index) {
  var total = Math.ceil(bytes.length / CHUNK_SIZE);
  if (index >= total) {
    return;
  }

  var piece = [index, total].concat(
    Array.prototype.slice.call(
      bytes,
      index * CHUNK_SIZE,
      (index + 1) * CHUNK_SIZE
    )
  );

  var message = {};
  message[MESSAGE_PAYLOAD] = piece;
  Pebble.sendAppMessage(
    message,
    function () {
      sendPieces(bytes, index + 1);
    },
    function (error) {
      console.log("could not send piece " + index + ": " + JSON.stringify(error));
    }
  );
}

function request(where) {
  var config = settings();
  var http = new XMLHttpRequest();
  http.open("GET", skyUrl(where), true);
  http.responseType = "arraybuffer";

  // Home Assistant wants a long-lived access token; a bare skyfield-sky server
  // wants nothing at all
  if (config.token) {
    http.setRequestHeader("Authorization", "Bearer " + config.token);
  }

  http.onload = function () {
    if (http.status !== 200) {
      console.log("the sky came back as " + http.status);
      return;
    }
    sendPieces(new Uint8Array(http.response), 0);
  };
  http.onerror = function () {
    console.log("could not reach the sky");
  };
  http.send();
}

/* Whatever was typed into the settings page, if anything was. */
function typedPlace() {
  var config = settings();
  var latitude = parseFloat(config.latitude);
  var longitude = parseFloat(config.longitude);
  if (isNaN(latitude) || isNaN(longitude)) {
    return null;
  }
  return { latitude: latitude, longitude: longitude };
}

/*
 * Work out where the observer is, then get on with it.
 *
 * The phone's own fix if it has been allowed one, the typed coordinates if not,
 * and null if neither -- which the sky server takes as "draw your own place"
 * and the weather takes as "do not bother".
 *
 * A refused or slow fix falls back to the typed coordinates rather than giving
 * up, because a chart of roughly the right sky beats no chart at all.
 */
function withPlace(then) {
  var typed = typedPlace();
  if (!settings().useLocation || !navigator.geolocation) {
    then(typed);
    return;
  }

  var asked = false;
  var once = function (where) {
    if (!asked) {
      asked = true;
      then(where);
    }
  };

  navigator.geolocation.getCurrentPosition(
    function (position) {
      once({
        latitude: position.coords.latitude.toFixed(4),
        longitude: position.coords.longitude.toFixed(4),
      });
    },
    function (error) {
      console.log("no location: " + error.message);
      once(typed);
    },
    { timeout: LOCATION_TIMEOUT, maximumAge: 60 * 60 * 1000 }
  );
}

function fetchSky() {
  withPlace(request);
}

/*
 * The current weather, from Open-Meteo.
 *
 * This is the one reading on the face the watch cannot take for itself: a
 * Pebble exposes 547 calls to a watchface and not one of them is about the
 * weather, whatever the system weather app shows. So it costs a radio wake an
 * hour, and it is the only thing here that talks to anyone but your own server.
 * Turning the corner off in the settings stops the fetch entirely.
 */
function requestWeather(where) {
  if (!where) {
    console.log("no coordinates, so no weather");
    return;
  }

  var url =
    WEATHER_HOST +
    "?latitude=" + encodeURIComponent(where.latitude) +
    "&longitude=" + encodeURIComponent(where.longitude) +
    "&current=temperature_2m,weather_code,is_day";
  if (settings().fahrenheit) {
    url += "&temperature_unit=fahrenheit";
  }

  var http = new XMLHttpRequest();
  http.open("GET", url, true);

  http.onload = function () {
    if (http.status !== 200) {
      console.log("the weather came back as " + http.status);
      return;
    }
    var current;
    try {
      current = JSON.parse(http.responseText).current;
    } catch (error) {
      console.log("could not read the weather: " + error);
      return;
    }
    if (!current || current.temperature_2m === undefined) {
      return;
    }

    var message = {};
    message[MESSAGE_WEATHER_TEMPERATURE] = Math.round(current.temperature_2m);
    message[MESSAGE_WEATHER_CONDITION] = conditionFor(
      current.weather_code,
      current.is_day !== 0
    );
    Pebble.sendAppMessage(message);
  };
  http.onerror = function () {
    console.log("could not reach the weather");
  };
  http.send();
}

function fetchWeather() {
  if (settings().showWeather === false) {
    return;
  }
  withPlace(requestWeather);
}

function sendSettings() {
  var config = settings();
  var message = {};
  message[MESSAGE_NORTH_UP] = config.northUp ? 1 : 0;
  message[MESSAGE_HORIZONTAL_FLIP] = config.horizontalFlip ? 1 : 0;
  message[MESSAGE_SHOW_STARS] = config.showStars === false ? 0 : 1;
  message[MESSAGE_SHOW_BATTERY] = config.showBattery === false ? 0 : 1;
  message[MESSAGE_SHOW_STEPS] = config.showSteps === false ? 0 : 1;
  message[MESSAGE_SHOW_HEART] = config.showHeart === false ? 0 : 1;
  message[MESSAGE_SHOW_WEATHER] = config.showWeather === false ? 0 : 1;
  Pebble.sendAppMessage(message);
}

Pebble.addEventListener("ready", function () {
  // the watch asks when it wants one; this is only for the very first run,
  // when it has nothing at all to draw
  fetchSky();

  // the sky is asked for by the watch, which knows when what it holds has gone
  // stale. The weather cannot be, because the watch has no way of knowing when
  // it last rained, so this end keeps the clock for it.
  fetchWeather();
  setInterval(fetchWeather, WEATHER_INTERVAL);
});

// anything from the watch is a request for the sky
Pebble.addEventListener("appmessage", function () {
  fetchSky();
});

Pebble.addEventListener("showConfiguration", function () {
  Pebble.openURL("data:text/html;charset=utf-8," + encodeURIComponent(page(settings())));
});

Pebble.addEventListener("webviewclosed", function (event) {
  if (!event || !event.response) {
    return; // closed without saving
  }
  try {
    saveSettings(JSON.parse(decodeURIComponent(event.response)));
  } catch (error) {
    console.log("could not read the settings back: " + error);
    return;
  }
  sendSettings();
  // the observer may have moved, so what the watch is holding is wrong rather
  // than merely old
  fetchSky();
  fetchWeather();
});
