"""Adw.Application implementation for AVD4Linux."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
import sys

from .cli import build_arg_parser

logger = logging.getLogger(__name__)


def in_flatpak() -> bool:
    """Detects whether we are already running inside a Flatpak sandbox."""
    return bool(os.environ.get("FLATPAK_ID")) or Path("/.flatpak-info").exists()


def _configure_pkcs11_provider() -> None:
    """Points OpenSC and GnuTLS at the sandbox-bundled OpenSC PKCS#11 provider.

    This exists to bypass the Flatpak p11-kit client RPC proxy. It is strictly a
    sandbox concern: on a native install the paths below do not exist, and setting
    OPENSC_CONF to a nonexistent file makes OpenSC fail to initialise its PKCS#11
    module entirely (zero tokens), while writing /etc/gnutls/pkcs11.conf would
    clobber the host's system-wide GnuTLS PKCS#11 configuration. So every step is
    gated on actually being inside a Flatpak *and* on the bundled files existing.
    """
    if not in_flatpak():
        logger.debug("Not running inside a Flatpak; leaving host OpenSC/GnuTLS configuration untouched")
        return

    from .smartcard import find_opensc_provider

    provider = find_opensc_provider()
    if not provider:
        logger.warning(
            "Inside a Flatpak but no OpenSC PKCS#11 provider was found; "
            "smart card authentication will not be available"
        )
        return

    opensc_conf = "/app/etc/opensc.conf"
    if os.path.exists(opensc_conf):
        os.environ.setdefault("OPENSC_CONF", opensc_conf)

    # Configure GnuTLS to auto-load the native OpenSC provider across all sandbox
    # processes (including WebKitNetworkProcess) so certificate requests issued
    # in another process still reach the hardware token.
    try:
        os.makedirs("/etc/gnutls", exist_ok=True)
        with open("/etc/gnutls/pkcs11.conf", "w") as f:
            f.write(f"load={provider}\n")
    except Exception as e:
        logger.debug("Could not write /etc/gnutls/pkcs11.conf: %s", e)

    try:
        import ctypes

        _gnutls = ctypes.CDLL("libgnutls.so.30")
        if hasattr(_gnutls, "gnutls_pkcs11_init") and hasattr(_gnutls, "gnutls_pkcs11_add_provider"):
            _gnutls.gnutls_pkcs11_init.argtypes = [ctypes.c_uint, ctypes.c_char_p]
            _gnutls.gnutls_pkcs11_init.restype = ctypes.c_int
            _gnutls.gnutls_pkcs11_add_provider.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            _gnutls.gnutls_pkcs11_add_provider.restype = ctypes.c_int
            _gnutls.gnutls_pkcs11_init(0, None)
            _gnutls.gnutls_pkcs11_add_provider(provider.encode("utf-8"), None)
            logger.info("Registered OpenSC provider %s with GnuTLS", provider)
    except Exception as e:
        logger.debug("Direct GnuTLS provider registration unavailable: %s", e)


_configure_pkcs11_provider()


def check_bwrap_sandbox() -> bool:
    """Checks if Bubblewrap unprivileged user namespace creation is permitted by the host OS.

    Inside a Flatpak the process is already confined by an outer Bubblewrap
    sandbox, and the runtime ships no bwrap binary, so a failed probe here means
    "already sandboxed", not "broken". Treating it as a failure would block the
    app from starting at all in the Flatpak build.
    """
    if in_flatpak():
        return True
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    try:
        res = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "--unshare-user", "--uid", str(os.getuid()), "/bin/true"],
            capture_output=True,
            timeout=2,
        )
        return res.returncode == 0
    except Exception:
        return False


def show_sandbox_error_and_exit() -> None:
    """Prints a clear error and displays an Adwaita error dialog explaining the AppArmor setup."""
    msg_text = (
        "\n"
        "================================================================================\n"
        "[AVD4Linux] ERROR: Unprivileged User Namespaces Restricted by Host OS\n"
        "================================================================================\n"
        "WebKitGTK's Bubblewrap sandbox cannot initialize because unprivileged user\n"
        "namespaces are restricted on Ubuntu 24.04+ (kernel.apparmor_restrict_unprivileged_userns).\n\n"
        "To run AVD4Linux with full security sandboxing, install the AppArmor profile:\n\n"
        "  sudo cp data/apparmor/avd4linux /etc/apparmor.d/\n"
        "  sudo apparmor_parser -r /etc/apparmor.d/avd4linux\n\n"
        "Alternatively, permit unprivileged user namespaces via sysctl:\n\n"
        "  sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0\n\n"
        "Or, for testing/container environments, launch with:\n\n"
        "  bin/avd4linux --disable-webkit-sandbox\n"
        "================================================================================\n"
    )
    print(msg_text, file=sys.stderr)

    try:
        import gi
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw, Gtk

        Adw.init()
        err_app = Adw.Application(application_id="org.avd4linux.SandboxError")

        def on_activate(app):
            win = Adw.ApplicationWindow(application=app, title="AVD4Linux — Sandbox Setup Required")
            win.set_default_size(600, 360)
            dialog = Adw.MessageDialog(
                transient_for=win,
                heading="AppArmor Sandbox Setup Required",
                body=(
                    "Ubuntu 24.04 restricts unprivileged user namespaces by default, "
                    "preventing WebKitGTK from initializing its Bubblewrap security sandbox.\n\n"
                    "<b>To enable sandboxing, install the AppArmor profile:</b>\n"
                    "<tt>sudo cp data/apparmor/avd4linux /etc/apparmor.d/\n"
                    "sudo apparmor_parser -r /etc/apparmor.d/avd4linux</tt>\n\n"
                    "<b>Alternatively, enable via sysctl:</b>\n"
                    "<tt>sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0</tt>\n\n"
                    "Or pass <tt>--disable-webkit-sandbox</tt> for testing."
                ),
            )
            dialog.set_body_use_markup(True)
            dialog.add_response("close", "Close")
            dialog.set_default_response("close")
            dialog.connect("response", lambda *_: app.quit())
            win.present()
            dialog.present()

        err_app.connect("activate", on_activate)
        err_app.run([])
    except Exception as e:
        logger.debug("Could not present GUI error dialog: %s", e)

    sys.exit(1)


# Parse CLI arguments early to configure WebKit environment flags before C library initialization
try:
    _early_parser = build_arg_parser()
    _early_args, _ = _early_parser.parse_known_args(sys.argv[1:])
    if _early_args.disable_webkit_sandbox:
        os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
        logger.warning("SECURITY WARNING: WebKit renderer sandbox disabled via CLI argument.")
except Exception as e:
    logger.debug("Early CLI argument parsing failed: %s", e)

if not os.environ.get("WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS") and not check_bwrap_sandbox():
    show_sandbox_error_and_exit()

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, Gio, GLib, WebKit

from .window import AVDMainWindow

logger = logging.getLogger(__name__)


class AVDApplication(Adw.Application):
    """The top-level AVD4Linux desktop application."""

    def __init__(self, initial_cloud: str = "dod") -> None:
        super().__init__(
            application_id="org.avd4linux.AVD4Linux",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self.initial_cloud = initial_cloud
        self.window: AVDMainWindow | None = None

    def do_activate(self) -> None:
        if not self.window:
            self.window = AVDMainWindow(self, initial_cloud_id=self.initial_cloud)
        self.window.present()

    def _list_smartcard_certs(self) -> int:
        """Prints every certificate the hardware token exposes, then exits."""
        from .smartcard import describe_certificate, enumerate_hardware_certificates

        records = enumerate_hardware_certificates()
        if not records:
            print(
                "No certificates found on a smart card token.\n"
                "Check that the CAC is inserted, that pcscd is running, and that the\n"
                "reader appears in 'pcsc_scan'. Also confirm the OpenSC PKCS#11 provider\n"
                "is installed (package 'opensc-pkcs11')."
            )
            return 1

        print(f"{len(records)} certificate(s) available on the smart card:")
        for index, record in enumerate(records, start=1):
            print(f"  {index}. {describe_certificate(record)}")
        print(
            "\nSelect one with, for example:\n"
            "  avd4linux --piv-cert 01\n"
            "  avd4linux --piv-cert 'PIV Authentication'\n"
            "  avd4linux --piv-cert auto"
        )
        return 0

    def _save_certificate_selector(self, selector: str) -> None:
        """Persists the user's smart card certificate choice."""
        from .settings import Settings

        settings = Settings.load()
        settings.piv_certificate_selector = "" if selector.strip().lower() == "auto" else selector
        if settings.save():
            if settings.piv_certificate_selector:
                logger.info("Saved smart card certificate selector: %s", settings.piv_certificate_selector)
            else:
                logger.info("Cleared smart card certificate selector; using automatic PIV selection")

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()
        parser = build_arg_parser(default_cloud=self.initial_cloud)
        parsed, _ = parser.parse_known_args(args[1:])

        if parsed.disable_webkit_sandbox:
            os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
            logger.warning("SECURITY WARNING: WebKit renderer sandbox disabled via --disable-webkit-sandbox flag.")

        if parsed.verbose:
            # The FreeRDP client's own stdout/stderr is forwarded from the PTY at DEBUG
            # level, so this is what makes its WLOG output visible here.
            logging.getLogger("avd4linux").setLevel(logging.DEBUG)
            logger.debug("Verbose logging enabled (DEBUG)")

        if parsed.list_smartcard_certs:
            return self._list_smartcard_certs()

        if parsed.piv_cert is not None:
            self._save_certificate_selector(parsed.piv_cert)

        self.initial_cloud = parsed.cloud
        self.activate()

        if self.window and parsed.cloud:
            self.window.set_cloud(parsed.cloud)

        if self.window and (parsed.microphone is not None or parsed.webcam is not None):
            self.window.set_device_redirect(microphone=parsed.microphone, webcam=parsed.webcam)

        if parsed.rdp and self.window:
            self.window._launch_freerdp(parsed.rdp)

        return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    GLib.set_prgname("org.avd4linux.AVD4Linux")
    GLib.set_application_name("AVD4Linux")
    
    try:
        display = Gdk.Display.get_default()
        if display:
            theme = Gtk.IconTheme.get_for_display(display)
            repo_data_dir = Path(__file__).resolve().parent.parent.parent / "data"
            if repo_data_dir.is_dir():
                theme.add_search_path(str(repo_data_dir))
        Gtk.Window.set_default_icon_name("org.avd4linux.AVD4Linux")
    except Exception as e:
        logger.debug("Could not set default icon name/search path: %s", e)

    app = AVDApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
