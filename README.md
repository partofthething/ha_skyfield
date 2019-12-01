# Live Sun, Moon, and Planets for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/partofthething/ha_skyfield)

This is a custom component for [Home Assistant ](https://www.home-assistant.io/) 
that makes a live polar sun path chart for your location. Besides the Sun, it
also shows the Moon and a few major planets. Plus, it shows the Winter and Summer solstice sun paths so you can see where you are in the seasons!

![Screenshot of the skyfield](screenshot.png)

This uses the [skyfield library](https://rhodesmill.org/skyfield/) to do the computations. 

To use: 

* Install this in your `custom_components` folder
* Download the prerequisides: `pip3 install skyfield matplotlib numpy`
* Add the following to your home assistant config:
```yaml
camera:
    platform: ha_skyfield
```
* Add a picture entity to your GUI with this camera. It will update live.

Inspiration comes from the University of Oregon 
[Solar Radiation Monitoring Lab](http://solardat.uoregon.edu/PolarSunChartProgram.html).


