"""FreeRDP 3 session launcher and lifecycle manager for AVD4Linux."""
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


def parse_cert_trust_prompt(buf: str) -> dict[str, str]:
    """Extracts server certificate details from FreeRDP certificate trust prompt output."""
    import re
    details = {"host": "Unknown Gateway", "subject": "", "issuer": "", "fingerprint": ""}
    m_host = re.search(r"Certificate details for ([^\s:]+)", buf) or re.search(r"The hostname used for this connection \(([^)]+)\)", buf)
    if m_host:
        details["host"] = m_host.group(1).strip()
    m_sub = re.search(r"Subject:\s*([^\n]+)", buf)
    if m_sub:
        details["subject"] = m_sub.group(1).strip()
    m_iss = re.search(r"Issuer:\s*([^\n]+)", buf)
    if m_iss:
        details["issuer"] = m_iss.group(1).strip()
    m_fp = re.search(r"(?:fingerprint|Thumbprint):\s*([0-9a-fA-F:]{20,})", buf) or re.search(r"is ([0-9a-fA-F:]{20,})", buf)
    if m_fp:
        details["fingerprint"] = m_fp.group(1).strip()
    return details


class RDPSessionManager:
    """Manages active FreeRDP 3 processes with smart card redirection."""

    def __init__(self) -> None:
        self.executable = find_freerdp3()
        self.active_process: Optional[subprocess.Popen] = None
        self.master_fd: Optional[int] = None
        self._on_exit_callback: Optional[Callable[[int], None]] = None
        self.on_auth_url_needed: Optional[Callable[[str], None]] = None
        self.on_cert_trust_needed: Optional[Callable[[dict[str, str], Callable[[str], None]], None]] = None

    def build_rdp_file_args(self, rdp_path: str | Path, extra_args: Optional[List[str]] = None) -> List[str]:
        """Builds command line arguments to launch an .rdp file with smart card redirection."""
        if not self.executable:
            raise FileNotFoundError("xfreerdp3 not found on system")

        resolved_path = Path(rdp_path).expanduser().resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"RDP file not found: {resolved_path}")

        rdp_path = str(resolved_path)
        args = [
            self.executable,
            rdp_path,
            "/smartcard",
            "/smartcard-logon",
            "/network:auto",
            "+fonts",
            "/gfx",
            "/rfx",
        ]

        # Extract sovereign tenant if present
        try:
            content = Path(rdp_path).read_text(encoding="utf-8", errors="replace")
            tenant_id = None
            for line in content.splitlines():
                if line.startswith("aadtenantid:s:"):
                    tenant_id = line.split(":", 2)[2].strip()
                    break

            import re
            if tenant_id and re.fullmatch(r"^[0-9a-fA-F\-]{36}$", tenant_id):
                # Use sovereign DoD login.microsoftonline.us authority with use-tenantid:on
                # and specify avd-access redirect URI to https://login.microsoftonline.com/common/oauth2/nativeclient
                # which is the exact registered redirect URI for client a85cf173-4192-42f8-81fa-777a763e6e2c.
                # Note: Pass as literal URL without % escapes because FreeRDP treats avd-access as a C printf format string.
                args.append(
                    f"/azure:ad:login.microsoftonline.us,use-tenantid:on,tenantid:{tenant_id},"
                    f"avd-scope:https://www.wvd.azure.us/.default,"
                    f"avd-access:https://login.microsoftonline.com/common/oauth2/nativeclient"
                )
            elif tenant_id:
                logger.warning("Invalid tenant ID format in RDP file, ignoring.")
        except Exception as e:
            logger.warning("Could not parse tenant from .rdp file: %s", e)

        if extra_args:
            args.extend(extra_args)

        return args

    def feed_auth_url(self, redirect_url: str) -> None:
        """Sends the OAuth redirect URL response into FreeRDP's stdin."""
        if self.master_fd is not None:
            try:
                # Sanitize to strictly a single line to prevent terminal control injection
                clean_url = redirect_url.splitlines()[0].strip() if redirect_url else ""
                msg = clean_url + "\n"
                logger.info("Feeding OAuth redirect URL to FreeRDP")
                os.write(self.master_fd, msg.encode())
            except Exception as e:
                logger.error("Failed to write to FreeRDP PTY: %s", e)

    def launch_rdp_file(
        self,
        rdp_path: str | Path,
        on_exit: Optional[Callable[[int], None]] = None,
        on_auth_url_needed: Optional[Callable[[str], None]] = None,
        on_cert_trust_needed: Optional[Callable[[dict[str, str], Callable[[str], None]], None]] = None,
        extra_args: Optional[List[str]] = None,
    ) -> subprocess.Popen:
        """Launches FreeRDP 3 asynchronously using a pseudo-terminal with ECHO disabled."""
        import pty
        import termios
        cmd = self.build_rdp_file_args(rdp_path, extra_args)
        safe_cmd = [
            arg if not arg.startswith(("/azure:ad:", "/access-token:", "/gateway:"))
            else arg.split(":")[0] + ":***"
            for arg in cmd
        ]
        logger.info("Launching FreeRDP 3: %s", " ".join(safe_cmd))

        env = dict(os.environ)
        if "DISPLAY" not in env:
            env["DISPLAY"] = ":0"
        if "WAYLAND_DISPLAY" not in env:
            env["WAYLAND_DISPLAY"] = "wayland-0"

        master, slave = pty.openpty()
        # Disable ECHO on the slave PTY so fed credentials/OAuth codes are not echoed back to logs
        try:
            attr = termios.tcgetattr(slave)
            attr[3] = attr[3] & ~termios.ECHO
            termios.tcsetattr(slave, termios.TCSANOW, attr)
        except Exception as e:
            logger.warning("Could not disable ECHO on PTY slave: %s", e)

        proc = subprocess.Popen(
            cmd,
            env=env,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        self.active_process = proc
        self.master_fd = master
        self._on_exit_callback = on_exit
        self.on_auth_url_needed = on_auth_url_needed
        self.on_cert_trust_needed = on_cert_trust_needed

        t = threading.Thread(target=self._monitor_pty, args=(proc, master), daemon=True)
        t.start()
        return proc

    def _monitor_pty(self, proc: subprocess.Popen, master_fd: int) -> None:
        """Monitors PTY output from FreeRDP, extracting any OAuth authorization prompts or certificate challenges."""
        import re
        buf = ""
        while proc.poll() is None:
            try:
                data = os.read(master_fd, 1024)
                if not data:
                    break
                text = data.decode("utf-8", errors="replace")
                buf += text
                if len(buf) > 4096:
                    buf = buf[-4096:]

                for line in text.splitlines():
                    line_clean = line.strip()
                    if line_clean:
                        # Mask any lines that might contain OAuth authorization codes or tokens
                        if any(k in line_clean.lower() for k in ["code=", "token=", "bearer", "access_token"]):
                            logger.debug("[FreeRDP] [sensitive data masked]")
                        else:
                            logger.debug("[FreeRDP] %s", line_clean)

                if any(prompt in buf for prompt in ["(Y/T/N)", "(y/t/n)", "Do you trust the above certificate"]):
                    cert_info = parse_cert_trust_prompt(buf)
                    logger.warning(
                        "FreeRDP received untrusted TLS certificate challenge for host: %s (fingerprint: %s)",
                        cert_info.get("host"),
                        cert_info.get("fingerprint"),
                    )

                    def respond_cert(choice: str) -> None:
                        try:
                            val = (choice.strip()[:1].upper() or "N") + "\n"
                            os.write(master_fd, val.encode())
                        except Exception as e:
                            logger.error("Failed to write certificate trust response to PTY: %s", e)

                    if self.on_cert_trust_needed:
                        self.on_cert_trust_needed(cert_info, respond_cert)
                    else:
                        logger.error("No certificate trust handler configured; rejecting untrusted certificate by default")
                        respond_cert("N")
                        self.terminate_session()
                    buf = ""

                if "Browse to:" in buf and "Paste redirect URL here:" in buf:
                    match = re.search(r"Browse to:\s*(https://\S+)", buf)
                    if match and self.on_auth_url_needed:
                        auth_url = match.group(1).strip()
                        logger.info("FreeRDP requested AAD OAuth authorization: %s", auth_url)
                        self.on_auth_url_needed(auth_url)
                        buf = ""
            except OSError:
                break
            except Exception as e:
                logger.error("Error reading PTY: %s", e)
                break

        rc = proc.wait()
        logger.info("FreeRDP process exited with code %d", rc)
        try:
            os.close(master_fd)
        except Exception:
            pass
        self.active_process = None
        self.master_fd = None
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
                try:
                    self.active_process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.active_process.kill()
            except Exception as e:
                logger.warning("Error terminating FreeRDP: %s", e)
