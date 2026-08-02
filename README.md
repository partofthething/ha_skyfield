# Live Sun, Moon, and Planets for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/partofthething/ha_skyfield)

This is a custom component for [Home Assistant ](https://www.home-assistant.io/) 
that makes a live polar sun path chart for your location. Besides the Sun, it
also shows the Moon and a few major planets. Plus, it shows the Winter and Summer solstice sun paths so you can see where you are in the seasons!

![Screenshot of the skyfield](screenshot.png)

This uses the [skyfield library](https://rhodesmill.org/skyfield/) to do the computations. 

## To use

* Install this in your `custom_components` folder
* Download the prerequisites: `pip3 install skyfield matplotlib numpy` (no longer
  necessary with hassio!)
* Add the following to your home assistant config and restart:
```yaml
ha_skyfield:
```
* Add this card to your dashboard:
```yaml
type: custom:skyfield-card
```

The card registers itself as a dashboard resource, so there is normally nothing to
add by hand. It draws itself as SVG, so it stays sharp at any size and takes its
colours from your theme, dark mode included.

If your dashboard resources are managed in YAML rather than through the UI, Home
Assistant will not let the integration add to them, and you will see a warning in
the log saying so. Add it yourself in that case:

```yaml
lovelace:
  resources:
    - url: /ha_skyfield/skyfield-card.js
      type: module
```

If a dashboard ever reports `Custom element doesn't exist: skyfield-card`, look in
the browser console for a `skyfield-card loaded` line. If it is absent the file is
not reaching the browser; if it is present the card is loaded and the dashboard
simply asked for it too early, which the resource registration above fixes.

The chart is drawn in your browser from the sky coordinates Home Assistant sends
it. Those only change slowly, so the browser can turn the sky itself as the
minutes pass — it redraws twice a minute and only asks the server for new
positions every ten minutes.

Optional card configuration:

* `title` a heading for the card
* `show_time` show a timestamp under the chart
* `show_legend` show a legend of the bodies
* `show_constellations` draw the constellations
* `north_up` (boolean) puts North at the top (useful in the Southern Hemisphere)
* `horizontal_flip` (boolean) flips projection horizontally
* `refresh_interval` seconds between asking the server for new positions (default 600)
* `redraw_interval` seconds between redraws (default 30)

Anything you leave out follows the `ha_skyfield:` configuration below. The
solstice path colours can be restyled with the `--skyfield-winter-color` and
`--skyfield-summer-color` theme variables.

Optional configuration under `ha_skyfield:`:

* `show_constellations` enable or disable the constellations (default is True).
* `show_time` and `show_legend` defaults for the card
* `planet_list` customize which planets are shown
* `constellations_list` customize which constellations are shown (use names from
  [here](https://github.com/partofthething/ha_skyfield/blob/master/custom_components/ha_skyfield/constellations_by_RA_Dec.dat))
* `north_up` (boolean) puts North at the top (useful in the Southern Hemisphere)
* `horizontal_flip` (boolean) flips projection horizontally
* `latitude` and `longitude` if you want somewhere other than your home

## The image version

The original matplotlib camera is still here and still works, if you would rather
have an image, or want to send the chart somewhere that cannot run a dashboard:

```yaml
camera:
  platform: ha_skyfield
  show_constellations: false
```

Then add a picture entity to your GUI with this camera. It takes the same options
as `ha_skyfield:` above, plus:

* `image_type` (string) Optional - provide image format extension.  Tested options are `png` (default) and `jpg`.

It does not follow your theme, and rendering an image costs a good deal more than
letting the browser draw one; the card is the better option unless you need a file.

Known Issues:

* More (maybe) at [Issues](https://github.com/partofthething/ha_skyfield/issues)

Inspiration comes from the University of Oregon 
[Solar Radiation Monitoring Lab](http://solardat.uoregon.edu/PolarSunChartProgram.html).


