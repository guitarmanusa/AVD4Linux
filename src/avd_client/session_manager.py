"""FreeRDP 3 session launcher and lifecycle manager for AVD."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

FREERDP3_PATHS = [
    "/opt/freerdp3/usr/bin/xfreerdp3",
    "/usr/local/bin/xfreerdp3",
    "/usr/bin/xfreerdp3",
]


def find_freerdp3() -> Optional[str]:
    """Locates the FreeRDP 3 executable."""
    for p in FREERDP3_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    found = shutil.which("xfreerdp3")
    if found:
        return found
    return None


class RDPSessionManager:
    """Manages active FreeRDP 3 processes with smart card redirection."""

    def __init__(self) -> None:
        self.executable = find_freerdp3()
        self.active_process: Optional[subprocess.Popen] = None
        self._on_exit_callback: Optional[Callable[[int], None]] = None

    def build_rdp_file_args(self, rdp_path: str | Path, extra_args: Optional[List[str]] = None) -> List[str]:
        """Builds command line arguments to launch an .rdp file with smart card redirection."""
        if not self.executable:
            raise FileNotFoundError("xfreerdp3 not found on system")

        rdp_path = str(Path(rdp_path).expanduser().resolve())
        args = [
            self.executable,
            "/smartcard",
            "/smartcard-logon",
            "/sec:aad",
            "/cert:ignore",
            "/network:auto",
            "+fonts",
            "/gfx",
            "/rfx",
            "/dynamic-resolution",
            rdp_path,
        ]

        if extra_args:
            args.extend(extra_args)

        return args

    def launch_rdp_file(
        self,
        rdp_path: str | Path,
        on_exit: Optional[Callable[[int], None]] = None,
        extra_args: Optional[List[str]] = None,
    ) -> subprocess.Popen:
        """Launches FreeRDP 3 asynchronously with the given .rdp file."""
        cmd = self.build_rdp_file_args(rdp_path, extra_args)
        logger.info("Launching FreeRDP 3: %s", " ".join(cmd))

        # Ensure environment has display
        env = dict(os.environ)
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        self.active_process = proc
        self._on_exit_callback = on_exit

        # Monitor thread
        t = threading.Thread(target=self._monitor_proc, args=(proc,), daemon=True)
        t.start()
        return proc

    def _monitor_proc(self, proc: subprocess.Popen) -> None:
        """Monitors process output and detects termination."""
        try:
            for line in proc.stdout:
                line_str = line.strip()
                if line_str:
                    logger.debug("[FreeRDP] %s", line_str)
        except Exception:
            pass

        rc = proc.wait()
        logger.info("FreeRDP process exited with code %d", rc)
        self.active_process = None
        if self._on_exit_callback:
            try:
                self._on_exit_callback(rc)
            except Exception as e:
                logger.error("Error in on_exit callback: %s", e)

    def terminate_session(self) -> None:
        """Terminates the currently active FreeRDP process if any."""
        if self.active_process and self.active_process.poll() is None:
            try:
                self.active_process.terminate()
            except Exception as e:
                logger.warning("Error terminating FreeRDP: %s", e)
