"""Main event is to just plot a demo"""

import sys

from ha_skyfield.bodies import Sky

if len(sys.argv) > 1:
    output = sys.argv[1]
else:
    output = None

seattle = (47.608, -122.335)
pacific = "America/Los_Angeles"
sky = Sky(seattle, pacific)
sky.load()
# in Seattle's own time, whatever this machine's clock happens to be set to
when = sky.local_time()
sky.plot_sky(when=when, output=output)

# timelapse

# import datetime
# when = sky.local_time()
# interval = datetime.timedelta(minutes=30)
#
# for frame in range(72*2):
#    print(f"plotting frame {frame}")
#    sky.plot_sky(f'sun_{frame:03d}.png', when=when+interval*frame)
