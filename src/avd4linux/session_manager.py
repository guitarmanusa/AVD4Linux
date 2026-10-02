"""FreeRDP 3 session launcher and lifecycle manager for AVD4Linux."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Custom builds installed by this project (Ubuntu). These are compiled with
# CHANNEL_RDPECAM_CLIENT=ON plus the FFmpeg/OpenH264/swscale stack and carry the
# media_type_valid() patch, so they are the only builds that can redirect webcams.
# They are probed for MS-RDPECAM support ahead of the stock locations below.
CUSTOM_FREERDP3_PATHS = [
    "/opt/freerdp3-cam/bin/xfreerdp3",
    # Flatpak: the patched client we ship is installed into the app prefix.
    "/app/bin/xfreerdp3",
]

# Stock/distribution builds, used as a fallback when no custom build is present.
# Note: Ubuntu's freerdp3 packages omit CHANNEL_RDPECAM_CLIENT, so a session
# launched from one of these will not be able to redirect a webcam.
STANDARD_FREERDP3_PATHS = [
    "/usr/local/bin/xfreerdp3",
    "/usr/bin/xfreerdp3",
]

FREERDP3_PATHS = CUSTOM_FREERDP3_PATHS + STANDARD_FREERDP3_PATHS

# FreeRDP emits this literal warning from client/common/file.c when the client was
# compiled without CHANNEL_RDPECAM_CLIENT, i.e. when MS-RDPECAM is unavailable.
RDPECAM_UNSUPPORTED_MARKER = b"does not support [MS-RDPECAM]"

# Audio backends FreeRDP understands for /sound and /microphone (MS-RDPEAI).
AUDIO_BACKEND = "pulse"


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def find_freerdp3() -> Optional[str]:
    """Locates the FreeRDP 3 executable to launch sessions with.

    Resolution order:

    1. A custom build from CUSTOM_FREERDP3_PATHS that actually resolves its own
       client libraries and reports MS-RDPECAM support. This is the only
       combination that can redirect a webcam, so it wins outright.
    2. Any other custom build from CUSTOM_FREERDP3_PATHS that runs, even without
       MS-RDPECAM. Keeps a session possible if the custom prefix is misinstalled.
    3. The stock locations in STANDARD_FREERDP3_PATHS, then ``PATH``.

    Distro packages frequently link against a system libfreerdp-client3 that omits
    the rdpecam channel, so step 1 verifies capability rather than trusting the path.
    """
    for path in CUSTOM_FREERDP3_PATHS:
        if not _is_executable(path):
            continue
        if probe_camera_support(path).supported:
            logger.info("Using custom FreeRDP build with MS-RDPECAM support: %s", path)
            return path

    for path in CUSTOM_FREERDP3_PATHS:
        if _is_executable(path):
            logger.info(
                "Using custom FreeRDP build (no MS-RDPECAM support): %s", path
            )
            return path

    for path in STANDARD_FREERDP3_PATHS:
        if _is_executable(path):
            logger.info("Using distribution FreeRDP build: %s", path)
            return path

    found = shutil.which("xfreerdp3")
    if found:
        logger.info("Using FreeRDP from PATH: %s", found)
        return found
    return None


@dataclass
class CameraSupport:
    """Result of probing the local FreeRDP build for MS-RDPECAM camera redirection."""

    supported: bool
    detail: str


def _read_client_libraries(executable: str) -> list[Path]:
    """Resolves the shared libraries linked by the FreeRDP executable."""
    libs: list[Path] = []
    try:
        res = subprocess.run(
            ["ldd", executable], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug("Could not run ldd on %s: %s", executable, e)
        return libs

    for line in res.stdout.splitlines():
        m = re.search(r"=>\s*(/\S+)", line)
        if not m:
            continue
        candidate = Path(m.group(1))
        try:
            libs.append(candidate.resolve())
        except OSError:
            continue
    return libs


def probe_camera_support(executable: Optional[str] = None) -> CameraSupport:
    """Detects whether the local FreeRDP build supports MS-RDPECAM camera redirection.

    The channel is compiled in when FreeRDP is configured with
    CHANNEL_RDPECAM_CLIENT=ON, which on Linux additionally requires libv4l plus
    the FFmpeg/swscale/OpenH264 stack (see README, "Webcam / MS-RDPECAM
    Requirements"). When the channel is absent, the client library embeds the
    "This build does not support [MS-RDPECAM]" warning, which is a reliable
    negative marker that needs no live RDP connection.

    Inspecting the resolved shared objects (via ldd) rather than the executable
    path matters: a build without RUNPATH silently loads the distro's
    libfreerdp-client3, so the capability has to be read from the library the
    binary will actually dlopen.
    """
    exe = executable or find_freerdp3()
    if not exe or not os.path.isfile(exe):
        return CameraSupport(False, "FreeRDP 3 client not found")

    libs = _read_client_libraries(exe)
    if not libs:
        return CameraSupport(
            False,
            "Could not inspect the FreeRDP client libraries, so MS-RDPECAM "
            "support cannot be confirmed.",
        )

    for lib in libs:
        try:
            with open(lib, "rb") as f:
                if RDPECAM_UNSUPPORTED_MARKER in f.read():
                    return CameraSupport(
                        False,
                        "This FreeRDP build was compiled without MS-RDPECAM support. "
                        "Rebuild FreeRDP with CHANNEL_RDPECAM_CLIENT=ON and libv4l "
                        "to enable webcam redirection.",
                    )
        except OSError as e:
            logger.debug("Could not inspect %s: %s", lib, e)

    return CameraSupport(
        True,
        "MS-RDPECAM camera redirection is available in this FreeRDP build.",
    )


def has_local_camera() -> bool:
    """Returns True when at least one Video4Linux capture device is present."""
    try:
        return any(Path("/dev").glob("video*"))
    except OSError as e:
        logger.debug("Could not enumerate /dev/video*: %s", e)
        return False


def has_local_microphone() -> bool:
    """Returns True when the host has at least one ALSA capture device.

    /proc/asound/cardN/pcmNc marks a capture stream ('c' = capture, 'p' =
    playback). This inspects the kernel's device tree rather than the active
    audio server, so the answer does not depend on whether a session is running.
    """
    try:
        cards = sorted(Path("/proc/asound").glob("card[0-9]*"))
    except OSError as e:
        logger.debug("Could not enumerate /proc/asound: %s", e)
        return False

    for card in cards:
        try:
            if any(card.glob("pcm*c")):
                return True
        except OSError:
            continue
    return False


def log_device_availability(
    microphone_enabled: bool = False,
    webcam_enabled: bool = False,
) -> None:
    """Logs an informational line for each redirectable device class on the host.

    Emitted at startup so a user who cannot redirect a device can tell whether the
    host lacks the hardware, the FreeRDP build lacks the channel, or both.
    """
    camera = has_local_camera()
    microphone = has_local_microphone()

    if not camera:
        logger.info(
            "No webcam detected on this host (no /dev/video* nodes). "
            "Webcam redirection will be unavailable."
        )
    elif not webcam_enabled:
        logger.info("Webcam detected on this host but redirection is turned off.")
    else:
        support = probe_camera_support(executable=find_freerdp3())
        if support.supported:
            logger.info("Webcam detected and will be redirected to the next session.")
        else:
            logger.info("Webcam detected, but the FreeRDP build cannot use it: %s", support.detail)

    if not microphone:
        logger.info(
            "No microphone detected on this host (no ALSA capture devices). "
            "Microphone redirection will be unavailable."
        )
    elif not microphone_enabled:
        logger.info("Microphone detected on this host but redirection is turned off.")
    else:
        logger.info("Microphone detected and will be redirected to the next session.")


def device_redirect_args(
    microphone_enabled: bool = False,
    webcam_enabled: bool = False,
    sound_enabled: bool = True,
) -> List[str]:
    """Builds the FreeRDP CLI flags for optional local device redirection.

    Microphone redirection uses the static MS-RDPEAI audin channel; FreeRDP
    initialises it from /microphone and needs the audio subsystem active, so
    /sound is emitted alongside it.

    Webcam redirection uses the dynamic rdpecam channel (MS-RDPECAM), enabled
    with /dvc:rdpecam. It is only effective on builds compiled with the
    rdpecam channel; see probe_camera_support().
    """
    args: List[str] = []
    if sound_enabled or microphone_enabled:
        args.append(f"/sound:sys:{AUDIO_BACKEND}")
    if microphone_enabled:
        args.append(f"/microphone:sys:{AUDIO_BACKEND}")
    if webcam_enabled:
        args.append("/dvc:rdpecam")
    return args


def strip_ansi_codes(text: str) -> str:
    """Removes ANSI terminal control escape sequences from output streams."""
    import re
    return re.sub(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", text)


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
        self._cert_prompt_pending: bool = False

    def build_rdp_file_args(
        self,
        rdp_path: str | Path,
        extra_args: Optional[List[str]] = None,
        microphone_enabled: bool = False,
        webcam_enabled: bool = False,
        sound_enabled: bool = True,
        allow_untrusted_smartcard: bool = False,
    ) -> List[str]:
        """Builds command line arguments to launch an .rdp file with smart card redirection."""
        if not self.executable:
            raise FileNotFoundError("xfreerdp3 not found on system")

        resolved_path = Path(rdp_path).expanduser().resolve()
        if not resolved_path.is_file():
            raise FileNotFoundError(f"RDP file not found: {resolved_path}")

        rdp_path = str(resolved_path)

        # Extract sovereign tenant, gateway host, and target full address
        tenant_id = None
        gateway_host = ""
        target_host = ""
        try:
            content = Path(rdp_path).read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                line_s = line.strip()
                line_lower = line_s.lower()
                if line_lower.startswith("aadtenantid:s:"):
                    tenant_id = line_s.split(":", 2)[2].strip()
                elif line_lower.startswith("gatewayhostname:s:"):
                    raw_gw = line_s.split(":", 2)[2].strip().lower()
                    gateway_host = raw_gw.split(":", 1)[0]
                elif line_lower.startswith("full address:s:"):
                    raw_target = line_s.split(":", 2)[2].strip().lower()
                    target_host = raw_target.split(":", 1)[0]
        except Exception as e:
            logger.warning("Could not parse directives from .rdp file: %s", e)

        # Validate destination hosts against trusted Microsoft AVD infrastructure
        from .clouds import is_trusted_avd_host, is_usgov_avd_host

        hosts_to_check = [h for h in (gateway_host, target_host) if h]
        all_hosts_trusted = bool(hosts_to_check) and all(is_trusted_avd_host(h) for h in hosts_to_check)

        args = [
            self.executable,
            rdp_path,
            "/network:auto",
            "+fonts",
            "/gfx",
            "/rfx",
            "/f",
            "/floatbar",
        ]

        # Only redirect Smart Card hardware if destination hosts belong to trusted AVD infrastructure
        if all_hosts_trusted or allow_untrusted_smartcard:
            args.insert(2, "/smartcard")
            args.insert(3, "/smartcard-logon")
        else:
            logger.warning(
                "Smart Card (CAC/PIV) redirection disabled for untrusted host(s): gateway='%s', target='%s'",
                gateway_host, target_host
            )

        import re
        if tenant_id and re.fullmatch(r"^[0-9a-fA-F\-]{36}$", tenant_id):
            if all_hosts_trusted:
                is_usgov = is_usgov_avd_host(gateway_host) or is_usgov_avd_host(target_host)
                authority = "login.microsoftonline.us" if is_usgov else "login.microsoftonline.com"
                scope = "https://www.wvd.azure.us/.default" if is_usgov else "https://wvd.microsoft.com/.default"

                args.append(
                    f"/azure:ad:{authority},use-tenantid:on,tenantid:{tenant_id},"
                    f"avd-scope:{scope},"
                    f"avd-access:https://login.microsoftonline.com/common/oauth2/nativeclient"
                )
            else:
                logger.warning(
                    "Refusing to route Entra ID / AVD authentication tokens to untrusted host(s): gateway='%s', target='%s'",
                    gateway_host, target_host
                )
        elif tenant_id:
            logger.warning("Invalid tenant ID format in RDP file, ignoring.")

        if extra_args:
            args.extend(extra_args)

        # Optional local device redirection; appended last so callers can
        # override the defaults above via extra_args ordering.
        args.extend(
            device_redirect_args(
                microphone_enabled=microphone_enabled,
                webcam_enabled=webcam_enabled,
                sound_enabled=sound_enabled,
            )
        )

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
        microphone_enabled: bool = False,
        webcam_enabled: bool = False,
        sound_enabled: bool = True,
        allow_untrusted_smartcard: bool = False,
    ) -> subprocess.Popen:
        """Launches FreeRDP 3 asynchronously using a pseudo-terminal with ECHO disabled."""
        import pty
        import termios
        cmd = self.build_rdp_file_args(
            rdp_path,
            extra_args,
            microphone_enabled=microphone_enabled,
            webcam_enabled=webcam_enabled,
            sound_enabled=sound_enabled,
            allow_untrusted_smartcard=allow_untrusted_smartcard,
        )
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
                text = strip_ansi_codes(data.decode("utf-8", errors="replace"))
                buf += text
                if len(buf) > 4096:
                    buf = buf[-4096:]

                for line in text.splitlines():
                    line_clean = line.strip()
                    if line_clean:
                        # Mask any lines that might contain OAuth authorization codes or tokens (including URL-encoded %3D)
                        if re.search(r"(?i)(code|token|bearer|access_token|refresh_token|id_token)(?:=|%3D)", line_clean):
                            logger.debug("[FreeRDP] [sensitive data masked]")
                        else:
                            logger.debug("[FreeRDP] %s", line_clean)

                if any(prompt in buf for prompt in ["(Y/T/N)", "(y/t/n)", "Do you trust the above certificate"]) and not self._cert_prompt_pending:
                    self._cert_prompt_pending = True
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
                        finally:
                            self._cert_prompt_pending = False

                    if self.on_cert_trust_needed:
                        self.on_cert_trust_needed(cert_info, respond_cert)
                    else:
                        logger.error("No certificate trust handler configured; rejecting untrusted certificate by default")
                        respond_cert("N")
                        self._cert_prompt_pending = False
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
