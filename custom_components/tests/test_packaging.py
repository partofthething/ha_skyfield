"""
The repository is two things at once, and both have to keep working.

It is a Home Assistant custom integration, which HACS copies into a
configuration directory as it stands, and it is an installable Python package
pointed at those same files. Nothing here needs either of them installed; these
read what is written down.
"""

import json
import pathlib
import tomllib
import unittest

import ha_skyfield

PACKAGE = pathlib.Path(ha_skyfield.__file__).parent
ROOT = PACKAGE.parent.parent
MANIFEST = json.loads((PACKAGE / "manifest.json").read_text())
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())
HACS = json.loads((ROOT / "hacs.json").read_text())


class TestVersions(unittest.TestCase):
    def test_the_two_version_numbers_agree(self):
        """
        Home Assistant reads one and pip reads the other.

        They are the same release, and the card's URL is cache-busted with the
        manifest's, so a mismatch would ship a new card under an old number.
        """
        self.assertEqual(MANIFEST["version"], PYPROJECT["project"]["version"])


class TestDependencies(unittest.TestCase):
    def test_matplotlib_is_gone(self):
        """
        It was the heaviest thing here by a long way, for one picture.

        Home Assistant installs everything in `requirements` on setup, so this is
        not merely an unused import -- it was a build on every installation that
        did not have a wheel.
        """
        self.assertNotIn("matplotlib", MANIFEST["requirements"])
        self.assertNotIn("matplotlib", str(PYPROJECT["project"]["dependencies"]))

    def test_the_two_dependency_lists_agree(self):
        for requirement in MANIFEST["requirements"]:
            name = requirement.split(">")[0].split("=")[0]
            with self.subTest(requirement=name):
                self.assertIn(name, str(PYPROJECT["project"]["dependencies"]))

    def test_nothing_needs_home_assistant_to_be_installed(self):
        """
        The standalone half has to work on a machine that has never heard of it.

        Importing the package used to run the integration, which imports
        voluptuous and homeassistant; it now asks whether they are there first.
        """
        for module in ("projection", "svg", "pebble", "server", "cli", "bodies"):
            with self.subTest(module=module):
                __import__(f"ha_skyfield.{module}")


class TestPackaging(unittest.TestCase):
    def test_setuptools_is_pointed_at_the_integration(self):
        """One copy of the code, installed two ways."""
        self.assertEqual(
            PYPROJECT["tool"]["setuptools"]["package-dir"][""], "custom_components"
        )

    def test_the_data_files_travel_with_it(self):
        """An installed copy with no constellations would draw an empty sky."""
        included = PYPROJECT["tool"]["setuptools"]["package-data"]["ha_skyfield"]
        self.assertIn("*.dat", included)
        self.assertIn("frontend/*.js", included)

    def test_the_things_it_needs_are_actually_there(self):
        self.assertTrue((PACKAGE / "constellations_by_RA_Dec.dat").is_file())
        self.assertTrue((PACKAGE / "frontend" / "skyfield-card.js").is_file())

    def test_there_is_a_command(self):
        self.assertIn("skyfield-sky", PYPROJECT["project"]["scripts"])

    def test_hacs_advertises_what_is_actually_here(self):
        for domain in HACS["domains"]:
            with self.subTest(domain=domain):
                self.assertTrue((PACKAGE / f"{domain}.py").is_file())


if __name__ == "__main__":
    unittest.main()
