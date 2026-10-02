"""Tests for the persistent device redirection settings."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from avd4linux.settings import Settings


class TestSettingsDefaults(unittest.TestCase):
    def test_devices_are_opt_in(self):
        s = Settings()
        self.assertFalse(s.microphone_enabled)
        self.assertFalse(s.webcam_enabled)
        self.assertTrue(s.sound_enabled)

    def test_missing_file_yields_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            s = Settings.load(Path(d) / "nope.json")
            self.assertEqual(s, Settings())


class TestSettingsRoundTrip(unittest.TestCase):
    def test_save_then_load(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            original = Settings(microphone_enabled=True, webcam_enabled=False, sound_enabled=True)
            self.assertTrue(original.save(p))
            loaded = Settings.load(p)
            self.assertEqual(loaded, original)

    def test_permissions_are_user_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            Settings(microphone_enabled=True).save(p)
            mode = stat.S_IMODE(p.stat().st_mode)
            self.assertEqual(mode, 0o600, f"expected 0o600, got {oct(mode)}")

    def test_no_temp_files_left_behind(self):
        with tempfile.TemporaryDirectory() as d:
            Settings().save(Path(d) / "settings.json")
            leftovers = [p.name for p in Path(d).iterdir() if p.name != "settings.json"]
            self.assertEqual(leftovers, [])

    def test_directory_is_user_only(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "cfg" / "settings.json"
            Settings().save(target)
            mode = stat.S_IMODE(target.parent.stat().st_mode)
            self.assertEqual(mode, 0o700, f"expected 0o700, got {oct(mode)}")


class TestSettingsRobustness(unittest.TestCase):
    def test_corrupt_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text("{not valid json", encoding="utf-8")
            self.assertEqual(Settings.load(p), Settings())

    def test_non_object_json_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text('["a", "b"]', encoding="utf-8")
            self.assertEqual(Settings.load(p), Settings())

    def test_wrong_types_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text(
                json.dumps({"microphone_enabled": "yes", "webcam_enabled": 1, "sound_enabled": True}),
                encoding="utf-8",
            )
            loaded = Settings.load(p)
            self.assertFalse(loaded.microphone_enabled)
            self.assertFalse(loaded.webcam_enabled)
            self.assertTrue(loaded.sound_enabled)

    def test_unknown_keys_are_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "settings.json"
            p.write_text(
                json.dumps({"microphone_enabled": True, "evil": "value"}), encoding="utf-8"
            )
            self.assertTrue(Settings.load(p).microphone_enabled)

    def test_unwritable_target_reports_failure_without_raising(self):
        with tempfile.TemporaryDirectory() as d:
            ro = Path(d) / "ro"
            ro.mkdir()
            os.chmod(ro, stat.S_IRUSR | stat.S_IXUSR)
            try:
                self.assertFalse(Settings().save(ro / "settings.json"))
            finally:
                os.chmod(ro, stat.S_IRWXU)


if __name__ == "__main__":
    unittest.main()
