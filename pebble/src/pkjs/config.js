/* The settings page, shown in the Pebble app. */

module.exports = [
  {
    type: "heading",
    defaultValue: "Skyfield",
  },
  {
    type: "text",
    defaultValue:
      "A chart of the Sun, Moon, planets and constellations, fetched from a " +
      "skyfield server and turned by the watch itself.",
  },
  {
    type: "section",
    items: [
      { type: "heading", defaultValue: "Where to fetch it from" },
      {
        type: "input",
        messageKey: "serverUrl",
        label: "Server",
        defaultValue: "http://127.0.0.1:8099",
        attributes: { placeholder: "http://host:8099" },
        description:
          "A `skyfield-sky serve` address, or a Home Assistant one ending in " +
          "/api/ha_skyfield",
      },
      {
        type: "input",
        messageKey: "token",
        label: "Access token",
        attributes: { type: "password" },
        description:
          "Only for Home Assistant, which wants a long-lived access token. " +
          "Leave this empty for a plain skyfield server.",
      },
    ],
  },
  {
    type: "section",
    items: [
      { type: "heading", defaultValue: "Where you are" },
      {
        type: "text",
        defaultValue:
          "Leave these empty to draw wherever the server was set up for.",
      },
      {
        type: "input",
        messageKey: "latitude",
        label: "Latitude",
        attributes: { placeholder: "47.608", type: "number", step: "any" },
      },
      {
        type: "input",
        messageKey: "longitude",
        label: "Longitude",
        attributes: { placeholder: "-122.335", type: "number", step: "any" },
      },
    ],
  },
  {
    type: "section",
    items: [
      { type: "heading", defaultValue: "The chart" },
      {
        type: "toggle",
        messageKey: "showStars",
        label: "Constellations",
        defaultValue: true,
      },
      {
        type: "toggle",
        messageKey: "northUp",
        label: "North at the top",
        defaultValue: false,
        description:
          "Off puts south at the top, which is how a sky chart usually reads " +
          "in the northern hemisphere.",
      },
      {
        type: "toggle",
        messageKey: "horizontalFlip",
        label: "Mirror it",
        defaultValue: false,
      },
      {
        type: "input",
        messageKey: "constellations",
        label: "Only these",
        attributes: { placeholder: "Orion,UrsaMajor" },
        description:
          "Comma separated. Fewer of them means a smaller download, which is " +
          "the part that costs battery.",
      },
    ],
  },
  { type: "submit", defaultValue: "Save" },
];
