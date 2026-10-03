"""Tests for the AVD4Linux command-line interface contract."""

import contextlib
import io
import unittest

from avd4linux.cli import build_arg_parser


@contextlib.contextmanager
def expect_argparse_error():
    """Swallows the usage text argparse writes to stderr before exiting."""
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        yield


class TestDeviceFlags(unittest.TestCase):
    def setUp(self):
        self.parser = build_arg_parser()

    def test_defaults_leave_settings_untouched(self):
        args = self.parser.parse_args([])
        self.assertIsNone(args.microphone)
        self.assertIsNone(args.webcam)

    def test_enable_flags(self):
        args = self.parser.parse_args(["--enable-microphone", "--enable-webcam"])
        self.assertTrue(args.microphone)
        self.assertTrue(args.webcam)

    def test_disable_flags(self):
        args = self.parser.parse_args(["--disable-microphone", "--disable-webcam"])
        self.assertFalse(args.microphone)
        self.assertFalse(args.webcam)

    def test_microphone_flags_are_mutually_exclusive(self):
        with expect_argparse_error(), self.assertRaises(SystemExit):
            self.parser.parse_args(["--enable-microphone", "--disable-microphone"])

    def test_webcam_flags_are_mutually_exclusive(self):
        with expect_argparse_error(), self.assertRaises(SystemExit):
            self.parser.parse_args(["--enable-webcam", "--disable-webcam"])

    def test_devices_are_independent(self):
        args = self.parser.parse_args(["--enable-microphone"])
        self.assertTrue(args.microphone)
        self.assertIsNone(args.webcam)

    def test_devices_can_be_mixed(self):
        args = self.parser.parse_args(["--enable-microphone", "--disable-webcam"])
        self.assertTrue(args.microphone)
        self.assertFalse(args.webcam)


class TestExistingFlagsPreserved(unittest.TestCase):
    def setUp(self):
        self.parser = build_arg_parser()

    def test_cloud_default_and_choices(self):
        self.assertEqual(self.parser.parse_args([]).cloud, "dod")
        self.assertEqual(self.parser.parse_args(["--cloud", "gcc"]).cloud, "gcc")

    def test_default_cloud_is_configurable(self):
        self.assertEqual(build_arg_parser(default_cloud="commercial").parse_args([]).cloud, "commercial")

    def test_invalid_cloud_rejected(self):
        with expect_argparse_error(), self.assertRaises(SystemExit):
            self.parser.parse_args(["--cloud", "nope"])

    def test_rdp_path_passthrough(self):
        self.assertEqual(self.parser.parse_args(["--rdp", "/tmp/a.rdp"]).rdp, "/tmp/a.rdp")

    def test_sandbox_flag(self):
        self.assertTrue(self.parser.parse_args(["--disable-webkit-sandbox"]).disable_webkit_sandbox)
        self.assertFalse(self.parser.parse_args([]).disable_webkit_sandbox)

    def test_unknown_args_tolerated(self):
        args, unknown = self.parser.parse_known_args(["--future-flag", "x"])
        self.assertIn("--future-flag", unknown)

    def test_piv_cert_selector_defaults_to_unset(self):
        self.assertIsNone(self.parser.parse_args([]).piv_cert)

    def test_piv_cert_accepts_any_selector_form(self):
        for value in ("01", "0x01", "PIV Authentication", "pkcs11:token=x;id=%01;type=cert", "auto"):
            self.assertEqual(self.parser.parse_args(["--piv-cert", value]).piv_cert, value)

    def test_empty_piv_cert_forces_auto_selection(self):
        self.assertEqual(self.parser.parse_args(["--piv-cert", ""]).piv_cert, "")

    def test_list_smartcard_certs_flag(self):
        self.assertTrue(self.parser.parse_args(["--list-smartcard-certs"]).list_smartcard_certs)
        self.assertFalse(self.parser.parse_args([]).list_smartcard_certs)


class TestCertificateSelectorPersistence(unittest.TestCase):
    """--piv-cert must round-trip through the settings file."""

    def test_selector_saved_and_reloaded(self):
        import tempfile
        from pathlib import Path

        from avd4linux.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            self.assertEqual(Settings.load(path).piv_certificate_selector, "")

            settings = Settings.load(path)
            settings.piv_certificate_selector = "PIV Authentication"
            self.assertTrue(settings.save(path))

            self.assertEqual(Settings.load(path).piv_certificate_selector, "PIV Authentication")

    def test_non_string_selector_ignored(self):
        import json
        import tempfile
        from pathlib import Path

        from avd4linux.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"piv_certificate_selector": 17}), encoding="utf-8")
            self.assertEqual(Settings.load(path).piv_certificate_selector, "")


if __name__ == "__main__":
    unittest.main()
