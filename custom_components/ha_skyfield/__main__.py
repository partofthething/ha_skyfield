"""Let ``python -m ha_skyfield`` be the same as the ``skyfield-sky`` command."""

import sys

from .cli import main

sys.exit(main())
