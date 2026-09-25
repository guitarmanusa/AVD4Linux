"""Adw.Application implementation for AVD4Linux."""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Allow explicit opt-in to disable WebKit sandbox before WebKitGTK C library initialization
if "--disable-webkit-sandbox" in sys.argv:
    os.environ["WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS"] = "1"

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib

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
    app = AVDApplication()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
