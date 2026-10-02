"""Tests for RDP directive sanitization and device directive enforcement."""

import tempfile
import unittest
from pathlib import Path

from avd4linux.browser import (
    enforce_device_directives,
    is_safe_rdp_directive,
    normalize_directive_key,
    prepare_rdp_file,
)

BASE_RDP = "full address:s:host.example.com\r\nusername:s:user\r\n"


class TestNormalizeDirectiveKey(unittest.TestCase):
    def test_strips_punctuation_and_case(self):
        # "camerastoredirect" is FreeRDP's canonical spelling, but the
        # CamelCase spelling normalises to a different string, which is why
        # DEVICE_DIRECTIVE_KEYS lists both.
        self.assertEqual(normalize_directive_key("camerastoredirect:s:*"), "camerastoredirect")
        self.assertEqual(normalize_directive_key("CameraStoreRedirect:s:*"), "camerastoreredirect")
        self.assertEqual(normalize_directive_key("  full address:s:x  "), "fulladdress")

    def test_comments_and_blanks(self):
        self.assertEqual(normalize_directive_key("# comment"), "")
        self.assertEqual(normalize_directive_key(""), "")


class TestIsSafeRdpDirective(unittest.TestCase):
    def test_device_directives_remain_allowed(self):
        self.assertTrue(is_safe_rdp_directive("camerastoredirect:s:*"))
        self.assertTrue(is_safe_rdp_directive("audiocapturemode:i:1"))

    def test_drive_and_usb_still_forbidden(self):
        self.assertFalse(is_safe_rdp_directive("drivestoredirect:s:*"))
        self.assertFalse(is_safe_rdp_directive("usbdevicestoredirect:s:1"))


class TestEnforceDeviceDirectives(unittest.TestCase):
    def test_disabled_strips_server_values(self):
        lines = BASE_RDP.splitlines() + ["camerastoredirect:s:*", "audiocapturemode:i:1"]
        out = enforce_device_directives(lines, microphone_enabled=False, webcam_enabled=False)
        self.assertNotIn("camerastoredirect:s:*", out)
        self.assertNotIn("audiocapturemode:i:1", out)

    def test_enabled_appends_expected_values(self):
        out = enforce_device_directives(
            BASE_RDP.splitlines(), microphone_enabled=True, webcam_enabled=True
        )
        self.assertIn("audiocapturemode:i:1", out)
        self.assertIn("camerastoredirect:s:*", out)

    def test_server_cannot_override_user_opt_out(self):
        """A host pool requesting capture must not defeat the user's toggle."""
        lines = BASE_RDP.splitlines() + ["camerastoredirect:s:*", "audiocapturemode:i:1"]
        out = enforce_device_directives(lines, microphone_enabled=False, webcam_enabled=False)
        joined = "\n".join(out)
        self.assertNotIn("camerastoredirect", joined)
        self.assertNotIn("audiocapturemode", joined)

    def test_no_duplicate_directives(self):
        lines = BASE_RDP.splitlines() + ["audiocapturemode:i:1", "camerastoredirect:s:*"]
        out = enforce_device_directives(lines, microphone_enabled=True, webcam_enabled=True)
        self.assertEqual(out.count("audiocapturemode:i:1"), 1)
        self.assertEqual(out.count("camerastoredirect:s:*"), 1)

    def test_unrelated_directives_preserved(self):
        out = enforce_device_directives(BASE_RDP.splitlines(), microphone_enabled=True)
        self.assertIn("full address:s:host.example.com", out)
        self.assertIn("username:s:user", out)

    def test_case_insensitive_server_key_is_stripped(self):
        lines = BASE_RDP.splitlines() + ["CameraStoreRedirect:s:*"]
        out = enforce_device_directives(lines, webcam_enabled=False)
        self.assertNotIn("CameraStoreRedirect:s:*", out)

    def test_all_casing_variants_of_device_keys_are_stripped(self):
        """FreeRDP matches keys with _stricmp, so every casing must be filtered."""
        variants = [
            "camerastoredirect:s:*",
            "CameraStoreRedirect:s:*",
            "CAMERASTOREDIRECT:s:*",
            "camerastoreDIRECT:s:*",
            "audiocapturemode:i:1",
            "AudioCaptureMode:i:1",
            "AUDIOCAPTUREMODE:i:1",
        ]
        for variant in variants:
            with self.subTest(variant=variant):
                out = enforce_device_directives(
                    BASE_RDP.splitlines() + [variant],
                    microphone_enabled=False,
                    webcam_enabled=False,
                )
                self.assertNotIn(variant, out)


class TestPrepareRdpFile(unittest.TestCase):
    def _write(self, d, text):
        src = Path(d) / "in.rdp"
        src.write_bytes(text.encode("utf-8"))
        return src

    def test_enabled_devices_land_in_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, BASE_RDP)
            out = Path(prepare_rdp_file(src, microphone_enabled=True, webcam_enabled=True))
            text = out.read_text(encoding="utf-8")
            self.assertIn("audiocapturemode:i:1", text)
            self.assertIn("camerastoredirect:s:*", text)

    def test_disabled_devices_absent_from_output_file(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, BASE_RDP + "camerastoredirect:s:*\r\naudiocapturemode:i:1\r\n")
            out = Path(prepare_rdp_file(src))
            text = out.read_text(encoding="utf-8")
            self.assertNotIn("camerastoredirect", text)
            self.assertNotIn("audiocapturemode", text)

    def test_original_file_is_not_overwritten_in_place(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, BASE_RDP)
            out = Path(prepare_rdp_file(src, microphone_enabled=True))
            # The returned sanitized file must be distinct from source
            self.assertNotEqual(out, src)
            self.assertEqual(src.read_bytes(), BASE_RDP.encode("utf-8"))

    def test_output_permissions_are_user_only(self):
        import stat as _stat
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, BASE_RDP)
            out = Path(prepare_rdp_file(src, microphone_enabled=True))
            self.assertEqual(_stat.S_IMODE(out.stat().st_mode), 0o600)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            prepare_rdp_file("/nonexistent/file.rdp")

    def test_file_without_directives_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            src = self._write(d, "no directives here at all\n")
            with self.assertRaises(ValueError):
                prepare_rdp_file(src)


if __name__ == "__main__":
    unittest.main()
