"""
The Home Assistant entities, built and asked for a picture.

These exist because of a bug that no amount of testing the drawing would have
found. ``Camera.__init__`` assigns ``self.content_type`` as an ordinary
attribute, so a subclass that declares it as a property gives the base class
nothing to assign to: setup raised, the entity never appeared, and the dashboard
answered 404 for a camera that was never there. The version before that declared
it as a class attribute, which ``__init__`` quietly overwrote, so the chart went
out labelled as a JPEG it was not.

Both are invisible until something builds the entity, which is what these do.
They need Home Assistant installed; it is in requirements_test.txt.
"""

import unittest
from unittest import mock

try:
    from homeassistant.components.camera import Camera
except ImportError:  # pragma: no cover - depends on the install
    Camera = None

SEATTLE = (47.608, -122.335)
PACIFIC = "America/Los_Angeles"


def build_camera(**options):
    from ha_skyfield.camera import SkyFieldCam

    return SkyFieldCam(
        SEATTLE[0],
        SEATTLE[1],
        PACIFIC,
        configdir=".",
        tmpdir=".",
        show_constellations=False,
        show_time=True,
        show_legend=True,
        constellations=None,
        planets=None,
        north_up=False,
        horizontal_flip=False,
        **options,
    )


@unittest.skipUnless(Camera, "the entities need Home Assistant installed")
class TestTheCameraCanBeBuiltAtAll(unittest.TestCase):
    """
    The entity has to survive its own constructor.

    Anything raising here means the platform fails to set up, which shows up
    only as a camera that does not exist -- a 404 from the dashboard, with the
    real complaint buried in the log.
    """

    def test_it_builds(self):
        self.assertIsInstance(build_camera(), Camera)

    def test_it_builds_for_every_format_offered(self):
        from ha_skyfield.camera import CONTENT_TYPES

        for image_type in CONTENT_TYPES:
            with self.subTest(image_type=image_type):
                self.assertIsInstance(build_camera(image_type=image_type), Camera)


@unittest.skipUnless(Camera, "the entities need Home Assistant installed")
class TestTheCameraSaysWhatItIsServing(unittest.TestCase):
    """
    The content type has to survive the base class's constructor too.

    ``Camera.__init__`` sets it to image/jpeg, so anything decided before that
    call is thrown away. A chart served under the wrong type does not render and
    downloads with the wrong extension, and nothing anywhere says why.
    """

    def test_a_png_says_png(self):
        self.assertEqual(build_camera(image_type="png").content_type, "image/png")

    def test_a_jpg_says_jpeg(self):
        self.assertEqual(build_camera(image_type="jpg").content_type, "image/jpeg")

    def test_an_svg_says_svg(self):
        self.assertEqual(build_camera(image_type="svg").content_type, "image/svg+xml")

    def test_the_default_is_not_whatever_the_base_class_chose(self):
        """The base class's default is image/jpeg, and the default here is not."""
        self.assertEqual(build_camera().content_type, "image/png")


@unittest.skipUnless(Camera, "the entities need Home Assistant installed")
class TestTheCameraDrawsSomething(unittest.TestCase):
    """What comes out is what the content type promised."""

    @classmethod
    def setUpClass(cls):
        cls.camera = build_camera()
        cls.camera.sky.load()
        cls.camera._loaded = True

    def test_a_png_really_is_a_png(self):
        self.assertEqual(self.camera.camera_image()[:8], b"\x89PNG\r\n\x1a\n")

    def test_a_jpg_really_is_a_jpeg(self):
        camera = build_camera(image_type="jpg")
        camera.sky = self.camera.sky
        camera._loaded = True
        self.assertEqual(camera.camera_image()[:3], b"\xff\xd8\xff")

    def test_an_svg_really_is_an_svg(self):
        camera = build_camera(image_type="svg")
        camera.sky = self.camera.sky
        camera._loaded = True
        self.assertTrue(camera.camera_image().startswith(b"<svg"))

    def test_a_requested_width_is_honoured(self):
        picture = self.camera.camera_image(width=320)
        self.assertEqual(int.from_bytes(picture[16:20], "big"), 320)

    def test_it_loads_the_sky_before_drawing_it(self):
        """A camera asked for a picture before it is ready has to wait, not fail."""
        camera = build_camera()
        camera.sky = mock.Mock()
        camera.sky.sky_model.return_value = self.camera.sky.sky_model()
        camera.camera_image()
        camera.sky.load.assert_called_once()


@unittest.skipUnless(Camera, "the entities need Home Assistant installed")
class TestTheConfigurationStillValidates(unittest.TestCase):
    """
    A configuration that used to work has to go on working.

    The options are stricter than they were -- image_type is a fixed list now
    rather than any string at all -- and something rejected here is another
    entity that never appears.
    """

    def _validate(self, config):
        from ha_skyfield.camera import PLATFORM_SCHEMA

        return PLATFORM_SCHEMA({"platform": "ha_skyfield", **config})

    def test_the_bare_minimum(self):
        self.assertEqual(self._validate({})["image_type"], "png")

    def test_the_formats_the_old_readme_documented(self):
        for image_type in ("png", "jpg"):
            with self.subTest(image_type=image_type):
                self.assertEqual(
                    self._validate({"image_type": image_type})["image_type"],
                    image_type,
                )

    def test_the_options_that_were_always_here(self):
        config = self._validate(
            {
                "show_constellations": True,
                "show_time": False,
                "show_legend": False,
                "constellations_list": ["Orion"],
                "planet_list": ["Mars"],
                "north_up": True,
                "horizontal_flip": True,
            }
        )
        self.assertEqual(config["constellations_list"], ["Orion"])
        self.assertIs(config["north_up"], True)

    def test_a_format_that_cannot_be_drawn_is_refused_at_the_door(self):
        """Better a complaint in the log at startup than a camera that 404s."""
        import voluptuous as vol

        with self.assertRaises(vol.Invalid):
            self._validate({"image_type": "tiff"})


@unittest.skipUnless(Camera, "the entities need Home Assistant installed")
class TestTheSensor(unittest.TestCase):
    """The other entity, which writes its chart to a file."""

    def test_it_builds_and_writes_a_picture(self):
        import os
        import tempfile

        from ha_skyfield.sensor import IMAGE_FILENAME, SkyField

        with tempfile.TemporaryDirectory() as configdir:
            sensor = SkyField(SEATTLE[0], SEATTLE[1], PACIFIC, configdir, ".")
            sensor.update()

            written = os.path.join(configdir, "www", IMAGE_FILENAME)
            self.assertTrue(os.path.isfile(written), f"{written} was not written")
            with open(written, "rb") as chart:
                self.assertEqual(chart.read(8), b"\x89PNG\r\n\x1a\n")

            self.assertEqual(sensor.entity_picture, f"/local/{IMAGE_FILENAME}")
            self.assertIsInstance(sensor.state, float)


if __name__ == "__main__":
    unittest.main()
