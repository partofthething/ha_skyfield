/*
 * The settings page, built by hand.
 *
 * This used to be Clay, which is the usual way to do it, but Clay 1.0.4 does
 * not build for flint or gabbro -- the watches Core Devices shipped in 2025 --
 * and it is those this is mostly for. What Clay actually does is hand the phone
 * a `data:text/html` URL with the whole page in it, so doing the same by hand
 * costs a page of HTML and works everywhere.
 *
 * The page hands its answers back the way every Pebble settings page does: by
 * navigating to pebblejs://close# with the settings encoded after the hash.
 */

function escapeHtml(value) {
  return String(value === undefined || value === null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function field(name, label, value, options) {
  options = options || {};
  return (
    '<label for="' + name + '">' + label + "</label>" +
    '<input id="' + name + '" name="' + name + '"' +
    ' type="' + (options.type || "text") + '"' +
    ' value="' + escapeHtml(value) + '"' +
    (options.placeholder ? ' placeholder="' + escapeHtml(options.placeholder) + '"' : "") +
    (options.inputmode ? ' inputmode="' + options.inputmode + '"' : "") +
    ">" +
    (options.note ? '<p class="note">' + options.note + "</p>" : "")
  );
}

function toggle(name, label, checked, note) {
  return (
    '<div class="row"><label for="' + name + '">' + label + "</label>" +
    '<input id="' + name + '" name="' + name + '" type="checkbox"' +
    (checked ? " checked" : "") + "></div>" +
    (note ? '<p class="note">' + note + "</p>" : "")
  );
}

/* The whole settings page, with whatever is already set filled in. */
module.exports = function page(settings) {
  settings = settings || {};
  return [
    "<!doctype html>",
    '<html><head><meta charset="utf-8">',
    '<meta name="viewport" content="width=device-width, initial-scale=1">',
    "<title>Skyfield</title>",
    "<style>",
    ":root { color-scheme: dark; }",
    "body { margin: 0; padding: 20px; background: #101318; color: #e3e3e3;",
    "  font-family: system-ui, -apple-system, sans-serif; font-size: 16px; }",
    "h1 { font-size: 20px; margin: 0 0 4px; }",
    "h2 { font-size: 15px; text-transform: uppercase; letter-spacing: .08em;",
    "  color: #9b9b9b; margin: 28px 0 8px; }",
    "label { display: block; margin: 14px 0 4px; }",
    "input[type=text], input[type=password], input[type=number] {",
    "  width: 100%; box-sizing: border-box; padding: 10px;",
    "  background: #1b2029; color: #e3e3e3; border: 1px solid #3a3a3a;",
    "  border-radius: 8px; font-size: 16px; }",
    ".row { display: flex; align-items: center; justify-content: space-between; }",
    ".row label { margin: 14px 0 4px; }",
    "input[type=checkbox] { width: 22px; height: 22px; }",
    ".note { color: #9b9b9b; font-size: 13px; margin: 4px 0 0; }",
    "button { width: 100%; margin: 28px 0 0; padding: 14px; font-size: 17px;",
    "  background: #3f7fd0; color: #fff; border: 0; border-radius: 10px; }",
    "</style></head><body>",

    "<h1>Skyfield</h1>",
    '<p class="note">A chart of the Sun, Moon, planets and constellations, ',
    "fetched from a skyfield server and turned by the watch itself.</p>",

    "<h2>Where to fetch it from</h2>",
    toggle(
      "usePublicServer",
      "Use the public server",
      settings.usePublicServer === true,
      "Off, and yours is the only machine involved. On, and the chart comes " +
        "from skyfield.partofthething.com instead &mdash; which means your " +
        "coordinates are sent to a server somebody else runs, and your IP " +
        "address is visible to it, as it is to any site you visit. It needs " +
        "the location below, having none of its own, and it is never sent " +
        "the token."
    ),
    field("serverUrl", "Server", settings.serverUrl || "", {
      placeholder: "http://host:8099",
      note:
        "A <code>skyfield-sky serve</code> address, or a Home Assistant one " +
        "ending in /api/ha_skyfield. Ignored while the public server is on.",
    }),
    field("token", "Access token", settings.token || "", {
      type: "password",
      note:
        "Only for Home Assistant, which wants a long-lived access token. " +
        "Leave empty for a plain skyfield server.",
    }),

    "<h2>Where you are</h2>",
    toggle(
      "useLocation",
      "Use the phone's location",
      settings.useLocation,
      "Off uses the coordinates below, or the server's own if those are empty " +
        "too. The public server has none, and the weather cannot look one up, " +
        "so either of those needs the phone's fix or something typed here."
    ),
    field("latitude", "Latitude", settings.latitude, {
      type: "number",
      placeholder: "47.608",
      inputmode: "decimal",
    }),
    field("longitude", "Longitude", settings.longitude, {
      type: "number",
      placeholder: "-122.335",
      inputmode: "decimal",
    }),

    "<h2>The chart</h2>",
    toggle("showStars", "Constellations", settings.showStars !== false),
    toggle(
      "northUp",
      "North at the top",
      settings.northUp,
      "Off puts south at the top, which is how a sky chart usually reads in " +
        "the northern hemisphere."
    ),
    toggle("horizontalFlip", "Mirror it", settings.horizontalFlip),
    field("constellations", "Only these", settings.constellations || "", {
      placeholder: "Orion,UrsaMajor",
      note:
        "Comma separated. Fewer of them means a smaller download, which is " +
        "the part that costs battery.",
    }),

    "<h2>In the corners</h2>",
    '<p class="note">Only on a watch with corners to put them in; a round ' +
      "screen has none, and ignores all four of these.</p>",
    toggle("showBattery", "Battery, top right", settings.showBattery !== false),
    toggle(
      "showSteps",
      "Steps, top left",
      settings.showSteps !== false,
      "Needs a watch that counts them. Past ten thousand it counts in " +
        "thousands, so 12.3k."
    ),
    toggle(
      "showHeart",
      "Heart rate, bottom left",
      settings.showHeart !== false,
      "Whatever the watch last measured by itself. This never asks the sensor " +
        "to run more often than your health settings already have it running, " +
        "so it costs no battery and can be a few minutes old."
    ),
    toggle(
      "showWeather",
      "Weather, bottom right",
      settings.showWeather === true,
      "Off unless you turn it on, because it is the one reading here that " +
        "leaves: the phone fetches it hourly from open-meteo.com and has to " +
        "send your coordinates to ask. Nothing but your own server hears " +
        "from this watchface otherwise."
    ),
    toggle("fahrenheit", "Fahrenheit", settings.fahrenheit, "Off is Celsius."),

    '<button id="save">Save</button>',


    "<script>",
    'document.getElementById("save").addEventListener("click", function () {',
    "  var out = {};",
    '  var text = ["serverUrl", "token", "latitude", "longitude", "constellations"];',
    "  text.forEach(function (name) {",
    "    out[name] = document.getElementById(name).value.trim();",
    "  });",
    '  var flags = ["usePublicServer", "useLocation", "showStars", "northUp",',
    '    "horizontalFlip", "showBattery", "showSteps", "showHeart",',
    '    "showWeather", "fahrenheit"];',
    "  flags.forEach(function (name) {",
    "    out[name] = document.getElementById(name).checked;",
    "  });",
    '  document.location = "pebblejs://close#" + encodeURIComponent(JSON.stringify(out));',
    "});",
    "</script>",
    "</body></html>",
  ].join("\n");
};
