/**
 * A live sky chart for Home Assistant, drawn as SVG.
 *
 * The integration hands over right ascension and declination, which change only
 * slowly. Everything that changes minute to minute is just the Earth turning
 * underneath them, and that much can be had from the clock alone -- so the chart
 * redraws itself where it stands, crisp at any size, in the colors of whatever
 * theme is in force, without asking the server anything.
 */

const DEG = Math.PI / 180;

const SKY_URL = "ha_skyfield/sky";

// how often to redraw, and how often to ask for fresh positions. The sky turns a
// degree every four minutes, so a redraw every half minute is already smoother
// than an eye can follow, and the planets barely move between refreshes.
const DEFAULT_REDRAW_SECONDS = 30;
const DEFAULT_REFRESH_SECONDS = 600;

// the drawing is laid out in these units and scaled to fit by the viewBox
const SIZE = 400;
const CENTRE = SIZE / 2;
const HORIZON_RADIUS = 165;

// a circle of sky 90 degrees from overhead is the horizon
const HORIZON = 90;

// matplotlib sizes its markers by area in square points; this brings those
// numbers over to a radius in our units, so the card and the image agree
const MARKER_SCALE = 0.048;

const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

// how far apart to place the rings, in degrees of altitude
const RING_STEP = 10;

// points to draw along each constellation line, so it curves with the
// projection instead of cutting straight across it
const POINTS_PER_LINE = 10;

/**
 * Greenwich mean sidereal time, in degrees.
 *
 * This is the angle the Earth has turned to, reckoned against the stars rather
 * than against the Sun. Treating UTC as UT1 leaves it under a second out, which
 * comes to a hundredth of a pixel here.
 */
export function greenwichSiderealTime(date) {
  const julianDay = date.getTime() / 86400000 + 2440587.5;
  const since2000 = julianDay - 2451545.0;
  const centuries = since2000 / 36525;
  const degrees =
    280.46061837 +
    360.98564736629 * since2000 +
    0.000387933 * centuries * centuries -
    (centuries * centuries * centuries) / 38710000;
  return ((degrees % 360) + 360) % 360;
}

/** Pre-compute the parts of the rotation that every body shares. */
export function observerAt(latitude, longitude, date) {
  return {
    sinLat: Math.sin(latitude * DEG),
    cosLat: Math.cos(latitude * DEG),
    siderealTime: greenwichSiderealTime(date) + longitude,
  };
}

/**
 * Turn right ascension and declination into azimuth and altitude.
 *
 * Azimuth comes back in degrees east of north and altitude in degrees above the
 * horizon. This is called once per star per redraw, so the trigonometry that does
 * not depend on the particular star arrives ready-made in `observer`.
 */
export function altAz(ra, dec, observer) {
  const hourAngle = (observer.siderealTime - ra) * DEG;
  const sinDec = Math.sin(dec * DEG);
  const cosDec = Math.cos(dec * DEG);
  const sinHour = Math.sin(hourAngle);
  const cosHour = Math.cos(hourAngle);

  const altitude = Math.asin(
    sinDec * observer.sinLat + cosDec * observer.cosLat * cosHour,
  );
  const azimuth = Math.atan2(
    -cosDec * sinHour,
    sinDec * observer.cosLat - cosDec * observer.sinLat * cosHour,
  );
  return [(((azimuth / DEG) % 360) + 360) % 360, altitude / DEG];
}

/**
 * How far from the middle a given altitude sits.
 *
 * Straight overhead is the middle and the horizon is the rim, so this is the same
 * whichever way round the chart has been turned.
 */
function radiusFor(altitude) {
  return (HORIZON_RADIUS * (HORIZON - altitude)) / HORIZON;
}

/**
 * Places a point of sky on the drawing.
 *
 * The chart reads as though you were lying on your back looking up, which puts
 * east to the left of north: the way round a sky chart goes, and the opposite of
 * a map.
 */
function projector({ north_up, horizontal_flip }) {
  const zero = north_up ? Math.PI / 2 : -Math.PI / 2;
  const direction = horizontal_flip ? 1 : -1;

  return (azimuth, altitude) => {
    const radius = radiusFor(altitude);
    const angle = zero + direction * azimuth * DEG;
    return [
      CENTRE + radius * Math.cos(angle),
      CENTRE - radius * Math.sin(angle),
    ];
  };
}

/** Round to a tenth of a unit; SVG does not need more and the strings get long. */
const round = (value) => Math.round(value * 10) / 10;

// ids have to be unique across the whole page, not just within one card, since
// two of these on one dashboard would otherwise share a clip path
let cardCount = 0;

class SkyfieldCard extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._model = null;
    this._error = null;
    this._clipId = `skyfield-horizon-${cardCount++}`;
    this.innerHTML = "";
  }

  set hass(hass) {
    // this is called on every state change in Home Assistant, so it must stay
    // cheap: hold on to hass and let the timers do the work
    this._hass = hass;
    if (!this._model && !this._fetching) {
      this._refresh();
    }
  }

  connectedCallback() {
    this._redrawTimer = setInterval(
      () => this._draw(),
      (this._config?.redraw_interval ?? DEFAULT_REDRAW_SECONDS) * 1000,
    );
    this._refreshTimer = setInterval(
      () => this._refresh(),
      (this._config?.refresh_interval ?? DEFAULT_REFRESH_SECONDS) * 1000,
    );
    this._draw();
  }

  disconnectedCallback() {
    clearInterval(this._redrawTimer);
    clearInterval(this._refreshTimer);
  }

  getCardSize() {
    return 8;
  }

  getGridOptions() {
    return { columns: 12, rows: 8, min_columns: 6 };
  }

  /** Ask the integration where everything is. */
  async _refresh() {
    if (!this._hass || this._fetching) {
      return;
    }
    this._fetching = true;
    try {
      this._model = await this._hass.callApi("GET", SKY_URL);
      this._error = null;
    } catch (err) {
      this._error =
        "Could not reach the skyfield integration. Is `ha_skyfield:` in your " +
        "configuration.yaml?";
      console.error("skyfield-card could not load the sky", err);
    } finally {
      this._fetching = false;
    }
    this._built = false;
    this._draw();
  }

  /** What to draw, taking the card's config over the integration's. */
  _settings() {
    return { ...this._model, ...this._config };
  }

  _draw() {
    if (this._error) {
      this._showError();
      return;
    }
    if (!this._model) {
      return;
    }
    // rebuilding would throw away the enlarged view mid-look; the parts a rebuild
    // renews only change from one day to the next, so they can wait
    if (!this._built && !this._dialog?.open) {
      this._build();
    }
    this._place();
  }

  _showError() {
    this.innerHTML =
      `<style>${STYLES}</style>` +
      `<ha-card><div class="skyfield-error"></div></ha-card>`;
    this.querySelector(".skyfield-error").textContent = this._error;
  }

  /**
   * Put up the parts of the chart that never move: rings, spokes and labels.
   *
   * Everything that does move gets an empty element here and is filled in on
   * every redraw, so a redraw never builds or discards any DOM.
   */
  _build() {
    const settings = this._settings();
    const project = projector(settings);

    this.innerHTML = `
      <style>${STYLES}</style>
      <ha-card${settings.title ? ` header="${settings.title}"` : ""}>
        <div class="skyfield">
          <svg viewBox="0 0 ${SIZE} ${SIZE}" role="img"
               aria-label="Chart of the sky as it is now">
            <defs>
              <clipPath id="${this._clipId}">
                <circle cx="${CENTRE}" cy="${CENTRE}" r="${HORIZON_RADIUS}"/>
              </clipPath>
            </defs>
            <g class="grid">${this._grid(project)}</g>
            <g clip-path="url(#${this._clipId})">
              ${settings.paths.map((path) => this._sunPath(path, project)).join("")}
              <path class="constellation-lines" d=""/>
              <path class="stars" d=""/>
              <g class="bodies">${this._bodies(settings)}</g>
            </g>
            <circle class="horizon" cx="${CENTRE}" cy="${CENTRE}"
                    r="${HORIZON_RADIUS}"/>
            <g class="labels">${this._labels(project)}</g>
          </svg>
          ${settings.show_time === false ? "" : `<div class="when"></div>`}
          ${settings.show_legend === false ? "" : this._legend(settings)}
        </div>
      </ha-card>
      <dialog class="enlarged"></dialog>`;

    this._project = project;
    this._built = true;
    this._wireUpEnlarging();
  }

  /**
   * Let a click on the chart blow it up to fill the screen.
   *
   * The one chart gets moved into the dialog and back out again rather than a
   * second one being drawn, so it carries on being redrawn on the same timer, and
   * everything that looks it up by selector still finds it.
   */
  _wireUpEnlarging() {
    const chart = this.querySelector(".skyfield");
    const card = this.querySelector("ha-card");
    this._dialog = this.querySelector("dialog.enlarged");

    chart.addEventListener("click", () => {
      if (!this._dialog.open) {
        this._dialog.appendChild(chart);
        this._dialog.showModal();
      }
    });
    // a click anywhere in the enlarged view puts it away again, as does Escape,
    // which a modal dialog gives us for nothing
    this._dialog.addEventListener("click", () => this._dialog.close());
    this._dialog.addEventListener("close", () => {
      card.appendChild(chart);
      // a redraw may have been held off while the dialog was up
      this._draw();
    });
  }

  /** Rings of equal altitude and spokes of equal azimuth. */
  _grid(project) {
    const rings = [];
    for (let altitude = 0; altitude < HORIZON; altitude += RING_STEP) {
      rings.push(
        `<circle cx="${CENTRE}" cy="${CENTRE}" r="${round(radiusFor(altitude))}"/>`,
      );
    }
    const spokes = COMPASS.map((_, index) => {
      const [x, y] = project((index * 360) / COMPASS.length, 0);
      return `<line x1="${CENTRE}" y1="${CENTRE}" x2="${round(x)}" y2="${round(y)}"/>`;
    });
    return rings.join("") + spokes.join("");
  }

  /** The compass points, and the altitude each ring stands for. */
  _labels(project) {
    const compass = COMPASS.map((name, index) => {
      const [x, y] = project((index * 360) / COMPASS.length, -7);
      return `<text class="compass" x="${round(x)}" y="${round(y)}">${name}</text>`;
    });

    // the horizon is labelled by the compass points already, and putting a 0
    // there as well would sit on top of them
    const altitudes = [];
    for (let altitude = RING_STEP; altitude < HORIZON; altitude += RING_STEP) {
      const [x, y] = project(0, altitude);
      altitudes.push(
        `<text class="altitude" x="${round(x)}" y="${round(y)}">${altitude}°</text>`,
      );
    }
    return compass.join("") + altitudes.join("");
  }

  /**
   * One of the Sun's daily paths.
   *
   * These are already fixed curves for the day, so they are drawn once and left
   * alone until the integration sends a new day's worth.
   */
  _sunPath({ name, dashed, azimuth, altitude }, project) {
    const points = azimuth.map((azi, index) => {
      const [x, y] = project(azi, altitude[index]);
      return `${round(x)},${round(y)}`;
    });
    return (
      `<path class="sun-path ${name}${dashed ? " dashed" : ""}" ` +
      `d="M${points.join("L")}"/>`
    );
  }

  /** A circle per body, to be moved into place on each redraw. */
  _bodies({ bodies }) {
    return bodies
      .map(
        ({ label, color, size }) =>
          `<circle class="body" data-label="${label}" fill="${color}" ` +
          `r="${round(Math.sqrt(size) * MARKER_SCALE * HORIZON_RADIUS / 10)}">` +
          `<title>${label}</title></circle>`,
      )
      .join("");
  }

  /** Names beside colors, so nothing is identified by its color alone. */
  _legend({ bodies }) {
    const entries = bodies
      .map(
        ({ label, color }) =>
          `<li><span class="swatch" style="background:${color}"></span>${label}</li>`,
      )
      .join("");
    return `<ul class="legend">${entries}</ul>`;
  }

  /** Work out where everything is now, and move it there. */
  _place() {
    const settings = this._settings();
    const now = new Date();
    const observer = observerAt(settings.latitude, settings.longitude, now);

    if (settings.show_constellations === false) {
      this._setPath(".constellation-lines", "");
      this._setPath(".stars", "");
    } else {
      this._placeConstellations(settings.constellations ?? [], observer);
    }

    const bodies = this.querySelectorAll(".body");
    settings.bodies.forEach(({ ra, dec }, index) => {
      const [azimuth, altitude] = altAz(ra, dec, observer);
      const [x, y] = this._project(azimuth, altitude);
      bodies[index].setAttribute("cx", round(x));
      bodies[index].setAttribute("cy", round(y));
    });

    const when = this.querySelector(".when");
    if (when) {
      when.textContent = now.toLocaleString();
    }
  }

  /**
   * Draw every constellation as two paths: one of lines, one of stars.
   *
   * Doing it in two long paths rather than an element per star keeps a redraw
   * down to a couple of attribute writes however much sky is on show.
   */
  _placeConstellations(constellations, observer) {
    const lines = [];
    const stars = [];

    for (const constellation of constellations) {
      const placed = constellation.stars.map(([ra, dec]) =>
        altAz(ra, dec, observer),
      );

      for (const [azimuth, altitude] of placed) {
        if (altitude < 0) {
          continue;
        }
        const [x, y] = this._project(azimuth, altitude);
        // a line going nowhere, drawn with a round cap, is a dot
        stars.push(`M${round(x)},${round(y)}l0.01,0`);
      }

      for (const [from, to] of constellation.lines) {
        const [azi1, alt1] = placed[from];
        let [azi2, alt2] = placed[to];
        if (alt1 < 0 && alt2 < 0) {
          continue;
        }
        // go the short way round, rather than the wrong way across the chart
        azi2 -= Math.round((azi2 - azi1) / 360) * 360;
        lines.push(this._line(azi1, alt1, azi2, alt2));
      }
    }

    this._setPath(".constellation-lines", lines.join(""));
    this._setPath(".stars", stars.join(""));
  }

  /** A constellation line, bent to follow the projection. */
  _line(azi1, alt1, azi2, alt2) {
    const points = [];
    for (let step = 0; step < POINTS_PER_LINE; step++) {
      const along = step / (POINTS_PER_LINE - 1);
      const [x, y] = this._project(
        azi1 + (azi2 - azi1) * along,
        alt1 + (alt2 - alt1) * along,
      );
      points.push(`${round(x)},${round(y)}`);
    }
    return `M${points.join("L")}`;
  }

  _setPath(selector, d) {
    this.querySelector(selector).setAttribute("d", d);
  }
}

/**
 * Colors come from the theme wherever the theme has an opinion.
 *
 * That is what makes this follow dark mode: the ink, the grid and today's Sun
 * path are all the theme's own tokens, so they are chosen for the background
 * they land on rather than flipped to suit it. The bodies keep the colors they
 * have in the matplotlib image, since those say which planet you are looking at,
 * and they are ringed so that the pale ones stay visible on a pale card.
 */
const STYLES = `
  .skyfield {
    padding: 8px 12px 12px;
    cursor: zoom-in;
  }
  .skyfield svg {
    display: block;
    width: 100%;
    height: auto;
    overflow: visible;
  }
  dialog.enlarged {
    width: 100vw;
    height: 100vh;
    max-width: 100vw;
    max-height: 100vh;
    margin: 0;
    padding: 0;
    border: none;
    background: transparent;
    /* laying the chart out here rather than sizing it, so that a square chart
       fills whichever of the two dimensions runs out first */
    display: none;
    place-items: center;
  }
  dialog.enlarged[open] {
    display: grid;
  }
  dialog.enlarged::backdrop {
    background: var(--card-background-color, #fff);
    opacity: 0.97;
  }
  dialog.enlarged .skyfield {
    cursor: zoom-out;
    width: min(100vw, 100vh);
    padding: 16px;
    box-sizing: border-box;
  }
  .grid circle,
  .grid line {
    fill: none;
    stroke: var(--divider-color, #e0e0e0);
    stroke-width: 1;
  }
  .horizon {
    fill: none;
    stroke: var(--primary-text-color, #212121);
    stroke-width: 2.5;
  }
  text {
    fill: var(--secondary-text-color, #727272);
    font-family: var(--paper-font-body1_-_font-family, system-ui, sans-serif);
    font-size: 11px;
    text-anchor: middle;
    dominant-baseline: middle;
  }
  text.compass {
    fill: var(--primary-text-color, #212121);
    font-size: 12px;
  }
  .sun-path {
    fill: none;
    stroke-width: 1.5;
  }
  .sun-path.today {
    stroke: var(--primary-text-color, #212121);
    opacity: 0.85;
  }
  .sun-path.winter_solstice {
    stroke: var(--skyfield-winter-color, var(--info-color, #3f7fd0));
  }
  .sun-path.summer_solstice {
    stroke: var(--skyfield-summer-color, var(--success-color, #3c8c40));
  }
  .sun-path.dashed {
    stroke-dasharray: 5 4;
    opacity: 0.9;
  }
  .constellation-lines,
  .stars {
    fill: none;
    stroke-linecap: round;
  }
  /* the joins are meant to be a hint, so they stay faint */
  .constellation-lines {
    stroke: var(--primary-text-color, #212121);
    stroke-width: 1;
    opacity: 0.28;
  }
  /* the stars themselves carry the theme's ink at nearly full strength, which
     comes out near-white on a dark theme and near-black on a light one, the way
     the matplotlib chart had them */
  .stars {
    stroke: var(--skyfield-star-color, var(--primary-text-color, #212121));
    stroke-width: 2.6;
    opacity: 0.9;
  }
  .body {
    stroke: var(--skyfield-body-edge-color, rgba(0, 0, 0, 0.55));
    stroke-width: 1;
  }
  .when {
    color: var(--secondary-text-color, #727272);
    font-size: 12px;
    text-align: center;
    font-variant-numeric: tabular-nums;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 2px 12px;
    margin: 6px 0 0;
    padding: 0;
    list-style: none;
    color: var(--secondary-text-color, #727272);
    font-size: 12px;
  }
  .legend li {
    display: flex;
    align-items: center;
    gap: 5px;
  }
  .swatch {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 1px solid var(--skyfield-body-edge-color, rgba(0, 0, 0, 0.55));
  }
  .skyfield-error {
    padding: 16px;
    color: var(--error-color, #db4437);
  }
`;

// A dashboard resource and an extra module URL are different specifiers for the
// same file, so anybody holding both ends up here twice; registering the name a
// second time would throw and leave a confusing error in the console.
if (!customElements.get("skyfield-card")) {
  customElements.define("skyfield-card", SkyfieldCard);

  // says so in the console, the way other cards do, so that "this card does not
  // exist" can be told apart from "this card never loaded"
  console.info("%c skyfield-card loaded", "color: #18bcf2; font-weight: bold");

  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "skyfield-card",
    name: "Skyfield",
    preview: false,
    description: "Live chart of the Sun, Moon, planets and constellations.",
  });
}

export { SkyfieldCard };
