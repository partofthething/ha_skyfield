/*
 * The phone's half of the watch face.
 *
 * Fetches the sky from a skyfield server -- either `skyfield-sky serve` or Home
 * Assistant itself -- and passes it to the watch in pieces small enough for one
 * message. It does as little as it can and as rarely as it can: the watch asks
 * only when what it has is half a day old, because waking the radio is the
 * expensive part of the whole arrangement.
 */

var Clay = require("pebble-clay");
var clayConfig = require("./config");
var clay = new Clay(clayConfig, null, { autoHandleEvents: false });

// must match SKY_CHUNK_SIZE in src/c/sky_data.h and pebble.CHUNK_SIZE in Python
var CHUNK_SIZE = 512;

var MESSAGE_PAYLOAD = "PAYLOAD";
var MESSAGE_NORTH_UP = "NORTH_UP";
var MESSAGE_HORIZONTAL_FLIP = "HORIZONTAL_FLIP";
var MESSAGE_SHOW_STARS = "SHOW_STARS";

function settings() {
  var stored = localStorage.getItem("clay-settings");
  return stored ? JSON.parse(stored) : {};
}

/*
 * Where to fetch from, with whatever the settings say about the observer.
 *
 * Left to itself the server draws the place it was started for, so the
 * coordinates only go on when somebody has actually set them.
 */
function skyUrl() {
  var config = settings();
  var url = (config.serverUrl || "http://127.0.0.1:8099").replace(/\/+$/, "");
  url += url.indexOf("/api/") === -1 ? "/sky.pebble" : "/sky.pebble";

  var query = [];
  if (config.latitude && config.longitude) {
    query.push("lat=" + encodeURIComponent(config.latitude));
    query.push("lon=" + encodeURIComponent(config.longitude));
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
    Array.prototype.slice.call(bytes, index * CHUNK_SIZE, (index + 1) * CHUNK_SIZE)
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

function fetchSky() {
  var config = settings();
  var request = new XMLHttpRequest();
  request.open("GET", skyUrl(), true);
  request.responseType = "arraybuffer";

  // Home Assistant wants a long-lived access token; a bare skyfield-sky server
  // wants nothing at all
  if (config.token) {
    request.setRequestHeader("Authorization", "Bearer " + config.token);
  }

  request.onload = function () {
    if (request.status !== 200) {
      console.log("the sky came back as " + request.status);
      return;
    }
    sendPieces(new Uint8Array(request.response), 0);
  };
  request.onerror = function () {
    console.log("could not reach the sky");
  };
  request.send();
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

Pebble.addEventListener("showConfiguration", function (event) {
  Pebble.openURL(clay.generateUrl());
});

Pebble.addEventListener("webviewclosed", function (event) {
  if (!event || !event.response) {
    return;
  }
  clay.getSettings(event.response);
  sendSettings();
  // the observer may have moved, so what the watch is holding is wrong rather
  // than merely old
  fetchSky();
});
