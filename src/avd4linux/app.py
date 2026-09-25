"""Adw.Application implementation for AVD4Linux."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
from pathlib import Path
import sys

logger = logging.getLogger(__name__)


def check_bwrap_sandbox() -> bool:
    """Checks if Bubblewrap unprivileged user namespace creation is permitted by the host OS."""
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


# Allow explicit opt-in to disable WebKit sandbox before WebKitGTK C library initialization
if "--disable-webkit-sandbox" in sys.argv:
    os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
    logger.warning("SECURITY WARNING: WebKit renderer sandbox disabled via --disable-webkit-sandbox flag.")
elif not check_bwrap_sandbox():
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

    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        args = command_line.get_arguments()
        parser = argparse.ArgumentParser(description="AVD4Linux — Azure Virtual Desktop Linux Client")
        parser.add_argument(
            "--cloud",
            choices=["dod", "gcc", "commercial"],
            default=self.initial_cloud,
            help="Sovereign cloud environment to connect to",
        )
        parser.add_argument(
            "--rdp",
            help="Directly launch an .rdp file with FreeRDP and Smart Card redirection",
        )
        parser.add_argument(
            "--disable-webkit-sandbox",
            action="store_true",
            help="Explicitly disable WebKit renderer process sandbox (for testing/restricted containers)",
        )
        parsed, _ = parser.parse_known_args(args[1:])

        if parsed.disable_webkit_sandbox:
            os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"
            logger.warning("SECURITY WARNING: WebKit renderer sandbox disabled via --disable-webkit-sandbox flag.")

        self.initial_cloud = parsed.cloud
        self.activate()

        if self.window and parsed.cloud:
            self.window.set_cloud(parsed.cloud)

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
