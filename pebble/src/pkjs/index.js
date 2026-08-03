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

var SETTINGS_KEY = "skyfield-settings";

// how long to wait for the phone to work out where it is before giving up and
// letting the server draw wherever it was set up for
var LOCATION_TIMEOUT = 15000;

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

/*
 * Ask for the sky, from wherever the phone happens to be if it has been told to.
 *
 * A refused or slow fix is not a reason to draw nothing, so either way the
 * request goes out; without coordinates the server draws its own place.
 */
function fetchSky() {
  if (!settings().useLocation || !navigator.geolocation) {
    request(null);
    return;
  }

  var asked = false;
  var once = function (where) {
    if (!asked) {
      asked = true;
      request(where);
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
      once(null);
    },
    { timeout: LOCATION_TIMEOUT, maximumAge: 60 * 60 * 1000 }
  );
}

function sendSettings() {
  var config = settings();
  var message = {};
  message[MESSAGE_NORTH_UP] = config.northUp ? 1 : 0;
  message[MESSAGE_HORIZONTAL_FLIP] = config.horizontalFlip ? 1 : 0;
  message[MESSAGE_SHOW_STARS] = config.showStars === false ? 0 : 1;
  Pebble.sendAppMessage(message);
}

Pebble.addEventListener("ready", function () {
  // the watch asks when it wants one; this is only for the very first run,
  // when it has nothing at all to draw
  fetchSky();
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
});
