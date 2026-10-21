"""Tests for version reporting and application about action."""

import unittest
from unittest import mock

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

import avd4linux.version
from avd4linux.app import AVDApplication
from avd4linux.version import __version__


class TestVersionAndAbout(unittest.TestCase):
    def test_version_format(self):
        self.assertTrue(__version__)
        self.assertEqual(__version__, "0.2.8.1")

    def test_app_registers_about_action(self):
        Adw.init()
        app = AVDApplication()
        action = app.lookup_action("about")
        self.assertIsNotNone(action)

    def test_on_about_action_presents_window(self):
        Adw.init()
        app = AVDApplication()
        action = app.lookup_action("about")
        with mock.patch("gi.repository.Adw.AboutWindow.present") as mock_present:
            action.activate(None)
            mock_present.assert_called_once()


if __name__ == "__main__":
    unittest.main()
