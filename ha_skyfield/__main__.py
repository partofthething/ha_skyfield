from ha_skyfield.bodies import Sky

seattle = (47.608, -122.335)
pacific = "America/Los_Angeles"
sky = Sky(seattle, pacific)
sky.load()
sky.plot_current_sky()
