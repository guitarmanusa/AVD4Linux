"""Tests for the FreeRDP device redirection argument builder."""

import os
import unittest
from unittest import mock

from avd4linux import app
from avd4linux.session_manager import (
    AUDIO_BACKEND,
    device_redirect_args,
    has_local_camera,
    probe_camera_support,
)


class TestDeviceRedirectArgs(unittest.TestCase):
    def test_all_disabled(self):
        args = device_redirect_args(
            microphone_enabled=False, webcam_enabled=False, sound_enabled=False
        )
        self.assertEqual(args, [])

    def test_sound_only(self):
        args = device_redirect_args(sound_enabled=True)
        self.assertEqual(args, [f"/sound:sys:{AUDIO_BACKEND}"])

    def test_microphone_implies_sound(self):
        args = device_redirect_args(microphone_enabled=True, sound_enabled=False)
        self.assertIn(f"/microphone:sys:{AUDIO_BACKEND}", args)
        self.assertIn(f"/sound:sys:{AUDIO_BACKEND}", args)

    def test_webcam_enables_rdpecam_dvc(self):
        args = device_redirect_args(webcam_enabled=True, sound_enabled=False)
        self.assertIn("/dvc:rdpecam", args)
        self.assertNotIn(f"/microphone:sys:{AUDIO_BACKEND}", args)

    def test_both_devices(self):
        args = device_redirect_args(
            microphone_enabled=True, webcam_enabled=True, sound_enabled=True
        )
        self.assertIn(f"/microphone:sys:{AUDIO_BACKEND}", args)
        self.assertIn("/dvc:rdpecam", args)
        self.assertIn(f"/sound:sys:{AUDIO_BACKEND}", args)

    def test_no_duplicate_sound_flag(self):
        args = device_redirect_args(microphone_enabled=True, sound_enabled=True)
        self.assertEqual(args.count(f"/sound:sys:{AUDIO_BACKEND}"), 1)

    def test_defaults_do_not_enable_capture(self):
        args = device_redirect_args()
        self.assertNotIn(f"/microphone:sys:{AUDIO_BACKEND}", args)
        self.assertNotIn("/dvc:rdpecam", args)

    def test_no_sound_backend_leaks_tokens(self):
        for args in (
            device_redirect_args(microphone_enabled=True),
            device_redirect_args(webcam_enabled=True),
            device_redirect_args(),
        ):
            for arg in args:
                self.assertNotIn("token", arg.lower())
                self.assertNotIn("access", arg.lower())


class TestCameraProbe(unittest.TestCase):
    def test_missing_executable_reports_unsupported(self):
        support = probe_camera_support("/nonexistent/xfreerdp3")
        self.assertFalse(support.supported)
        self.assertTrue(support.detail)

    def test_probe_returns_a_detail_message(self):
        support = probe_camera_support()
        self.assertIsInstance(support.supported, bool)
        self.assertTrue(support.detail)

    def test_local_camera_probe_returns_bool(self):
        self.assertIsInstance(has_local_camera(), bool)


class TestBuildRdpFileArgs(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp_dir = tempfile.TemporaryDirectory()
        self.rdp_file = Path(self.temp_dir.name) / "test.rdp"
        self.rdp_file.write_text("full address:s:test.wvd.microsoft.com\n", encoding="utf-8")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_args_include_fullscreen_and_floatbar(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"
        args = mgr.build_rdp_file_args(self.rdp_file)

        self.assertIn("/f", args)
        self.assertIn("/floatbar", args)
        # Verify ordering: floatbar and fullscreen are included in the base flags
        f_idx = args.index("/f")
        floatbar_idx = args.index("/floatbar")
        self.assertLess(f_idx, floatbar_idx + 2)

    def test_extra_args_appended_after_fullscreen(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"
        args = mgr.build_rdp_file_args(self.rdp_file, extra_args=["-f"])

        self.assertIn("-f", args)
        # extra_args should appear after the default /f
        self.assertGreater(args.index("-f"), args.index("/f"))


class TestFreeRdpDiscovery(unittest.TestCase):
    """find_freerdp3() must prefer a custom, webcam-capable build."""

    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _fake_binary(self, name: str) -> str:
        p = self.dir / name
        p.write_text("#!/bin/sh\n", encoding="utf-8")
        p.chmod(0o755)
        return str(p)

    def test_custom_webcam_build_preferred_over_standard(self):
        from avd4linux import session_manager as sm

        cam = self._fake_binary("xfreerdp3")
        std = self._fake_binary("xfreerdp3-std")

        with mock.patch.object(sm, "CUSTOM_FREERDP3_PATHS", [cam]), mock.patch.object(
            sm, "STANDARD_FREERDP3_PATHS", [std]
        ), mock.patch.object(
            sm, "probe_camera_support", return_value=sm.CameraSupport(True, "ok")
        ), mock.patch.object(sm.shutil, "which", return_value=None):
            self.assertEqual(sm.find_freerdp3(), cam)

    def test_standard_used_when_custom_lacks_webcam(self):
        from avd4linux import session_manager as sm

        cam = self._fake_binary("xfreerdp3")
        std = self._fake_binary("xfreerdp3-std")

        with mock.patch.object(sm, "CUSTOM_FREERDP3_PATHS", [cam]), mock.patch.object(
            sm, "STANDARD_FREERDP3_PATHS", [std]
        ), mock.patch.object(
            sm,
            "probe_camera_support",
            return_value=sm.CameraSupport(False, "no channel"),
        ), mock.patch.object(sm.shutil, "which", return_value=None):
            self.assertEqual(sm.find_freerdp3(), cam)

    def test_standard_used_when_no_custom_build_exists(self):
        from avd4linux import session_manager as sm

        std = self._fake_binary("xfreerdp3-std")
        missing = str(self.dir / "absent")

        with mock.patch.object(sm, "CUSTOM_FREERDP3_PATHS", [missing]), mock.patch.object(
            sm, "STANDARD_FREERDP3_PATHS", [std]
        ), mock.patch.object(sm.shutil, "which", return_value=None):
            self.assertEqual(sm.find_freerdp3(), std)

    def test_non_executable_custom_path_is_skipped(self):
        from avd4linux import session_manager as sm

        not_exec = self.dir / "xfreerdp3"
        not_exec.write_text("", encoding="utf-8")
        not_exec.chmod(0o644)
        std = self._fake_binary("xfreerdp3-std")

        with mock.patch.object(sm, "CUSTOM_FREERDP3_PATHS", [str(not_exec)]), mock.patch.object(
            sm, "STANDARD_FREERDP3_PATHS", [std]
        ), mock.patch.object(sm.shutil, "which", return_value=None):
            self.assertEqual(sm.find_freerdp3(), std)


class TestDeviceAvailability(unittest.TestCase):
    def test_has_local_microphone_returns_bool(self):
        from avd4linux.session_manager import has_local_microphone
        self.assertIsInstance(has_local_microphone(), bool)

    def test_log_device_availability_mentions_missing_hardware(self):
        import logging
        from avd4linux import session_manager as sm

        with self.assertLogs("avd4linux.session_manager", level="INFO") as logs:
            with mock.patch.object(sm, "has_local_camera", return_value=False), mock.patch.object(
                sm, "has_local_microphone", return_value=False
            ):
                sm.log_device_availability(microphone_enabled=True, webcam_enabled=True)

        output = "\n".join(logs.output)
        self.assertIn("No webcam detected", output)
        self.assertIn("No microphone detected", output)

    def test_log_device_availability_reports_build_limitation(self):
        from avd4linux import session_manager as sm

        with self.assertLogs("avd4linux.session_manager", level="INFO") as logs:
            with mock.patch.object(sm, "has_local_camera", return_value=True), mock.patch.object(
                sm, "has_local_microphone", return_value=True
            ), mock.patch.object(
                sm, "probe_camera_support", return_value=sm.CameraSupport(False, "no channel")
            ), mock.patch.object(sm, "find_freerdp3", return_value=None):
                sm.log_device_availability(microphone_enabled=True, webcam_enabled=True)

        output = "\n".join(logs.output)
        self.assertIn("no channel", output)
        self.assertNotIn("No webcam detected", output)


if __name__ == "__main__":
    unittest.main()


class TestFlatpakSandboxDetection(unittest.TestCase):
    """Inside a Flatpak the outer sandbox already confines us, so the WebKit
    bubblewrap probe must not be treated as a fatal failure."""

    def test_flatpak_detected_via_env(self):
        with mock.patch.dict(os.environ, {"FLATPAK_ID": "org.avd4linux.AVD4Linux"}):
            self.assertTrue(app.in_flatpak())

    def test_flatpak_not_detected_outside(self):
        env = {k: v for k, v in os.environ.items() if k != "FLATPAK_ID"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(app.Path, "exists", return_value=False):
                self.assertFalse(app.in_flatpak())

    def test_bwrap_check_passes_inside_flatpak_without_bwrap_binary(self):
        env = {k: v for k, v in os.environ.items() if k != "FLATPAK_ID"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(app, "in_flatpak", return_value=True):
                with mock.patch.object(app.shutil, "which", return_value=None):
                    self.assertTrue(app.check_bwrap_sandbox())


class TestSecurityGuards(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_is_trusted_avd_host(self):
        from avd4linux.clouds import is_trusted_avd_host, is_usgov_avd_host

        # Trusted commercial and government hosts
        self.assertTrue(is_trusted_avd_host("g-us-1.wvd.microsoft.com"))
        self.assertTrue(is_trusted_avd_host("g-us-1.wvd.microsoft.com:443"))
        self.assertTrue(is_trusted_avd_host("rdweb.wvd.azure.us"))

        # Generic cloud instance domains must be treated as untrusted
        self.assertFalse(is_trusted_avd_host("myvm.cloudapp.azure.com"))
        self.assertFalse(is_trusted_avd_host("attacker.cloudapp.net"))

        # Malicious or untrusted hosts
        self.assertFalse(is_trusted_avd_host("malicious-usgov.com"))
        self.assertFalse(is_trusted_avd_host("attacker.com"))
        self.assertFalse(is_trusted_avd_host("attacker.azurewebsites.net"))
        self.assertFalse(is_trusted_avd_host("attacker.blob.core.windows.net"))
        self.assertFalse(is_trusted_avd_host(""))
        self.assertFalse(is_trusted_avd_host(None))

        # US Gov detection
        self.assertTrue(is_usgov_avd_host("rdweb.wvd.azure.us"))
        self.assertFalse(is_usgov_avd_host("g-us-1.wvd.microsoft.com"))
        self.assertFalse(is_usgov_avd_host("malicious-usgov.com"))

    def test_case_insensitive_directive_extraction_and_untrusted_bypass(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"

        rdp_path = self.dir / "case_mixed_attack.rdp"
        rdp_path.write_text(
            "AaDTenantId:s:11111111-2222-3333-4444-555555555555\n"
            "Full Address:s:g-us-1.wvd.microsoft.com\n"
            "GatewayHostName:s:attacker.com\n",
            encoding="utf-8"
        )
        args = mgr.build_rdp_file_args(rdp_path)

        # GatewayHostName:s:attacker.com must be parsed case-insensitively and flagged as untrusted
        self.assertFalse(any(a.startswith("/azure:ad:") for a in args))
        self.assertNotIn("/smartcard", args)
        self.assertNotIn("/smartcard-logon", args)

    def test_confused_deputy_prevention_untrusted_gateway(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"

        rdp_path = self.dir / "malicious.rdp"
        rdp_path.write_text(
            "aadtenantid:s:11111111-2222-3333-4444-555555555555\n"
            "gatewayhostname:s:malicious-usgov.com\n",
            encoding="utf-8"
        )
        args = mgr.build_rdp_file_args(rdp_path)

        # Must NOT include Entra ID token routing or Smart Card redirection
        self.assertFalse(any(a.startswith("/azure:ad:") for a in args))
        self.assertNotIn("/smartcard", args)
        self.assertNotIn("/smartcard-logon", args)

    def test_confused_deputy_prevention_untrusted_target(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"

        rdp_path = self.dir / "malicious_target.rdp"
        rdp_path.write_text(
            "aadtenantid:s:11111111-2222-3333-4444-555555555555\n"
            "full address:s:attacker.com\n",
            encoding="utf-8"
        )
        args = mgr.build_rdp_file_args(rdp_path)

        # Must NOT include Entra ID token routing or Smart Card redirection
        self.assertFalse(any(a.startswith("/azure:ad:") for a in args))
        self.assertNotIn("/smartcard", args)
        self.assertNotIn("/smartcard-logon", args)

    def test_trusted_avd_hosts_enable_token_and_smartcard(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"

        rdp_path = self.dir / "valid_avd.rdp"
        rdp_path.write_text(
            "aadtenantid:s:11111111-2222-3333-4444-555555555555\n"
            "gatewayhostname:s:g-us-1.wvd.microsoft.com:443\n"
            "full address:s:c-us-1.wvd.microsoft.com\n",
            encoding="utf-8"
        )
        args = mgr.build_rdp_file_args(rdp_path)

        # Must include Entra ID token routing and Smart Card redirection
        self.assertTrue(any(a.startswith("/azure:ad:login.microsoftonline.com") for a in args))
        self.assertIn("/smartcard", args)
        self.assertIn("/smartcard-logon", args)

    def test_trusted_usgov_avd_hosts_route_to_usgov_authority(self):
        from avd4linux.session_manager import RDPSessionManager
        mgr = RDPSessionManager()
        mgr.executable = "/fake/bin/xfreerdp3"

        rdp_path = self.dir / "usgov_avd.rdp"
        rdp_path.write_text(
            "aadtenantid:s:11111111-2222-3333-4444-555555555555\n"
            "gatewayhostname:s:g-usgov-1.wvd.azure.us:443\n",
            encoding="utf-8"
        )
        args = mgr.build_rdp_file_args(rdp_path)

        # Must route to login.microsoftonline.us authority
        self.assertTrue(any(a.startswith("/azure:ad:login.microsoftonline.us") for a in args))
        self.assertIn("/smartcard", args)

    def test_allowed_navigation_domains_whitelist(self):
        from avd4linux.browser import ALLOWED_NAVIGATION_DOMAINS

        def is_allowed(hostname):
            return any(hostname == d or hostname.endswith("." + d) for d in ALLOWED_NAVIGATION_DOMAINS)

        # Allowed AVD and identity domains
        self.assertTrue(is_allowed("rdweb.wvd.microsoft.com"))
        self.assertTrue(is_allowed("login.microsoftonline.com"))
        self.assertTrue(is_allowed("login.microsoftonline.us"))
        self.assertTrue(is_allowed("login.windows.net"))
        self.assertTrue(is_allowed("aadcdn.msauth.net"))

        # Blocked subdomains and generic cloud domains
        self.assertFalse(is_allowed("attacker.blob.core.windows.net"))
        self.assertFalse(is_allowed("attacker.azurewebsites.net"))
        self.assertFalse(is_allowed("attacker.azure.com"))
        self.assertFalse(is_allowed("attacker.windows.net"))
        self.assertFalse(is_allowed("malicious.com"))
