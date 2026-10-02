"""Command-line interface definition for AVD4Linux.

Kept free of import-time side effects (no sandbox probing, no GTK initialisation)
so the argument contract can be unit tested without a display server.
"""
from __future__ import annotations

import argparse

CLOUD_CHOICES = ["dod", "gcc", "commercial"]


def build_arg_parser(default_cloud: str = "dod") -> argparse.ArgumentParser:
    """Builds the AVD4Linux command-line parser.

    Device redirection flags are mutually exclusive per device and default to
    None, meaning "leave the persisted setting untouched".
    """
    parser = argparse.ArgumentParser(
        prog="avd4linux",
        description="AVD4Linux — Azure Virtual Desktop Linux Client",
    )
    parser.add_argument(
        "--cloud",
        choices=CLOUD_CHOICES,
        default=default_cloud,
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
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help=(
            "Log at DEBUG level, which includes the FreeRDP client's own output. "
            "Combine with FreeRDP's WLOG_LEVEL/WLOG_FILTER environment variables to "
            "trace individual channels, e.g. the webcam (MS-RDPECAM)."
        ),
    )

    mic_group = parser.add_mutually_exclusive_group()
    mic_group.add_argument(
        "--enable-microphone",
        dest="microphone",
        action="store_const",
        const=True,
        help="Redirect the local microphone (MS-RDPEAI) into the session",
    )
    mic_group.add_argument(
        "--disable-microphone",
        dest="microphone",
        action="store_const",
        const=False,
        help="Do not redirect the local microphone",
    )
    mic_group.set_defaults(microphone=None)

    cam_group = parser.add_mutually_exclusive_group()
    cam_group.add_argument(
        "--enable-webcam",
        dest="webcam",
        action="store_const",
        const=True,
        help="Redirect the local webcam (MS-RDPECAM) into the session",
    )
    cam_group.add_argument(
        "--disable-webcam",
        dest="webcam",
        action="store_const",
        const=False,
        help="Do not redirect the local webcam",
    )
    cam_group.set_defaults(webcam=None)

    return parser
