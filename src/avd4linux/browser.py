"""Embedded WebKitGTK 6.0 view for AVD4Linux authentication and workspace access."""
from __future__ import annotations

import logging
import os
import stat
import tempfile
from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import GLib, Gtk, WebKit

logger = logging.getLogger(__name__)

USER_DATA_DIR = Path.home() / ".local" / "share" / "avd4linux"
WEB_DATA_DIR = USER_DATA_DIR / "webdata"
DOWNLOADS_DIR = USER_DATA_DIR / "downloads"

# Ensure secure application storage directories exist with user-only permissions (0o700)
for _d in (USER_DATA_DIR, WEB_DATA_DIR, DOWNLOADS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(_d, stat.S_IRWXU)
    except Exception:
        pass


ALLOWED_NAVIGATION_DOMAINS = (
    "microsoft.com",
    "microsoftonline.com",
    "msauth.net",
    "msftauth.net",
    "azure.us",
    "microsoftonline.us",
    "azure.com",
    "live.com",
    "windows.net",
    "windowsazure.us",
    "windowsazure.com",
)

ALLOWED_MTLS_DOMAINS = (
    "certauth.login.microsoftonline.us",
    "certauth.login.microsoftonline.com",
)

FORBIDDEN_RDP_DIRECTIVES_NORMALIZED = {
    "drivestoredirect",
    "redirectdrives",
    "usbdevicestoredirect",
    "devicestoredirect",
    "alternateshell",
    "initialprogram",
    "remoteapplicationcmdline",
    "remoteapplicationfile",
    "drives",
    "gatewayusageargument",
    "redirectclipboard",
    "redirectcomports",
    "redirectprinters",
    "redirectposdevices",
    "shellworkingdirectory",
    "exec",
    "disablerail",
}


def is_safe_rdp_directive(line: str) -> bool:
    """Validates an individual RDP directive line against security rules using normalized key matching."""
    import re
    line_clean = line.strip()
    if not line_clean or line_clean.startswith(("#", ";")):
        return True

    parts = line_clean.split(":", 2)
    raw_key = parts[0].strip().lower()
    key_norm = re.sub(r"[^a-z0-9]", "", raw_key)

    if key_norm in FORBIDDEN_RDP_DIRECTIVES_NORMALIZED:
        logger.warning("Stripping forbidden RDP directive: %s", raw_key)
        return False

    if key_norm == "remoteapplicationprogram":
        val = parts[-1].strip() if len(parts) > 1 else ""
        if not val or not re.fullmatch(r"\|\|[0-9a-zA-Z\-_]+", val):
            logger.warning("Stripping unsafe remoteapplicationprogram: %s", val)
            return False

    return True


def prepare_rdp_file(dest_path: str | Path) -> str:
    """Ensures the downloaded file is a valid, sanitized .rdp file for FreeRDP (Fail-Closed, Atomic)."""
    p = Path(dest_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"RDP file not found: {dest_path}")

    rdp_out = p.with_suffix(".rdp")
    if rdp_out.is_symlink():
        rdp_out.unlink()

    try:
        raw = p.read_bytes()
        text = None
        for enc in ["utf-8", "utf-16", "latin1"]:
            try:
                text = raw.decode(enc)
                break
            except Exception:
                continue

        if not text:
            raise ValueError(f"Could not decode text encoding for RDP file: {dest_path}")

        import json
        if text.strip().startswith("{") and "}" in text:
            try:
                data = json.loads(text)
                for key in ["rdp", "connectionString", "rdpFile", "content"]:
                    if key in data and isinstance(data[key], str):
                        text = data[key]
                        break
            except Exception:
                pass

        import base64
        if not any(k in text.lower() for k in ["full address", "gatewayhostname", "loadbalanceinfo"]):
            try:
                decoded = base64.b64decode(text.strip()).decode("utf-8", errors="replace")
                if any(k in decoded.lower() for k in ["full address", "gateway", "loadbalanceinfo"]):
                    text = decoded
            except Exception:
                pass

        # Handle XML-wrapped RDP content (e.g. <RDP>...</RDP>) and decode XML/HTML entities
        import html
        import xml.etree.ElementTree as ET
        if text.strip().startswith("<"):
            try:
                root = ET.fromstring(text)
                # Extract all text content from XML nodes
                extracted = "".join(root.itertext())
                if extracted.strip():
                    text = extracted
            except Exception:
                # If XML parsing fails, unescape entities directly
                pass

        # Unescape XML/HTML entities (e.g. &#x0a;, &#10;) so encoded newlines expand before line splitting
        text = html.unescape(text)

        # Structured key-value directive sanitization
        clean_lines = [
            line for line in text.splitlines()
            if is_safe_rdp_directive(line)
        ]

        # Fail-closed: ensure file contains valid RDP directives
        valid_directives = [l for l in clean_lines if ":" in l and not l.strip().startswith(("#", ";"))]
        if not valid_directives:
            raise ValueError(f"RDP file {dest_path} contains no valid configuration directives")

        text = "\r\n".join(clean_lines) + "\r\n"

        # Atomic write via temporary file in DOWNLOADS_DIR to prevent race conditions / symlink replacement
        fd, tmp_swap = tempfile.mkstemp(dir=str(DOWNLOADS_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f_tmp:
                f_tmp.write(text)
            os.chmod(tmp_swap, stat.S_IRUSR | stat.S_IWUSR)
            os.replace(tmp_swap, rdp_out)
        finally:
            if os.path.exists(tmp_swap):
                try:
                    os.unlink(tmp_swap)
                except Exception:
                    pass

        logger.info("Prepared sanitized RDP file for FreeRDP: %s", rdp_out)
        return str(rdp_out)
    except Exception as e:
        logger.error("Security/Sanitization Error: Failed to process RDP file %s: %s", dest_path, e)
        # Fail closed: never return the raw or unsanitized file path
        raise ValueError(f"Failed to safely sanitize RDP file {dest_path}: {e}") from e


class AVDBrowserView(Gtk.Box):
    """Encapsulates WebKit.WebView with AVD-specific handlers."""

    def __init__(
        self,
        on_rdp_file_ready: Optional[Callable[[str], None]] = None,
        on_title_changed: Optional[Callable[[str], None]] = None,
        on_load_changed: Optional[Callable[[float, bool], None]] = None,
        on_pin_requested: Optional[Callable[[WebKit.AuthenticationRequest], bool]] = None,
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.on_rdp_file_ready = on_rdp_file_ready
        self.on_title_changed = on_title_changed
        self.on_load_changed = on_load_changed
        self.on_pin_requested = on_pin_requested

        # Secure application storage directories with user-only permissions
        for d in [USER_DATA_DIR, WEB_DATA_DIR, DOWNLOADS_DIR]:
            d.mkdir(parents=True, exist_ok=True)
            os.chmod(d, stat.S_IRWXU)

        # Setup WebKit settings
        settings = WebKit.Settings()
        settings.set_enable_developer_extras(False)
        settings.set_enable_smooth_scrolling(True)
        settings.set_enable_webgl(False)
        settings.set_javascript_can_open_windows_automatically(False)
        settings.set_allow_file_access_from_file_urls(False)
        settings.set_allow_universal_access_from_file_urls(False)
        settings.set_enable_html5_local_storage(True)

        # Modern Chrome/Edge user agent with AVD4Linux client identifier
        ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0 AVD4Linux/0.9.0"
        )
        settings.set_user_agent(ua)

        # Configure network session with persistent storage
        self.network_session = WebKit.NetworkSession.new(
            data_directory=str(WEB_DATA_DIR),
            cache_directory=str(WEB_DATA_DIR / "cache"),
        )
        self.network_session.connect("download-started", self._on_download_started)

        # Create WebView
        self.web_view = WebKit.WebView(
            network_session=self.network_session,
            settings=settings,
        )
        self.web_view.set_hexpand(True)
        self.web_view.set_vexpand(True)

        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        self.append(self.progress_bar)
        self.append(self.web_view)

        # Connect signals
        self.web_view.connect("notify::estimated-load-progress", self._on_progress)
        self.web_view.connect("notify::title", self._on_title)
        self.web_view.connect("load-changed", self._on_load_state_changed)
        self.web_view.connect("authenticate", self._on_authenticate)
        self.web_view.connect("decide-policy", self._on_decide_policy)

    def load_url(self, url: str) -> None:
        """Navigates to the specified URL."""
        logger.info("Navigating to: %s", url)
        self.web_view.load_uri(url)

    def reload(self) -> None:
        self.web_view.reload()

    def go_back(self) -> None:
        if self.web_view.can_go_back():
            self.web_view.go_back()

    def go_forward(self) -> None:
        if self.web_view.can_go_forward():
            self.web_view.go_forward()

    def _on_progress(self, web_view: WebKit.WebView, pspec: object) -> None:
        progress = web_view.get_estimated_load_progress()
        self.progress_bar.set_fraction(progress)
        if self.on_load_changed:
            self.on_load_changed(progress, self.progress_bar.get_visible())

    def _on_title(self, web_view: WebKit.WebView, pspec: object) -> None:
        title = web_view.get_title() or "Azure Virtual Desktop"
        if self.on_title_changed:
            self.on_title_changed(title)

    def _on_load_state_changed(
        self, web_view: WebKit.WebView, load_event: WebKit.LoadEvent
    ) -> None:
        if load_event == WebKit.LoadEvent.STARTED:
            self.progress_bar.set_visible(True)
            self.progress_bar.set_fraction(0.1)
        elif load_event == WebKit.LoadEvent.FINISHED:
            self.progress_bar.set_visible(False)

    def _on_authenticate(
        self, web_view: WebKit.WebView, request: WebKit.AuthenticationRequest
    ) -> bool:
        """Handles authentication requests, providing PIV client certificate and delegating PIN to OS."""
        scheme = request.get_scheme()
        host = request.get_host()
        logger.info("Authentication requested: scheme=%s, host=%s", scheme, host)

        req_host = (host or "").lower()
        is_trusted_mtls = any(req_host == d or req_host.endswith("." + d) for d in ALLOWED_MTLS_DOMAINS)
        if not is_trusted_mtls:
            logger.warning("Security violation: Rejected client certificate/PIN request from untrusted host: %s", host)
            request.cancel()
            return True

        if scheme == WebKit.AuthenticationScheme.CLIENT_CERTIFICATE_REQUESTED:
            from .smartcard import get_piv_tls_certificate
            cert = get_piv_tls_certificate()
            if cert:
                logger.info("Supplying PIV client certificate for %s: %s", host, cert.get_subject_name())
                cred = WebKit.Credential.new_for_certificate(
                    cert, WebKit.CredentialPersistence.FOR_SESSION
                )
                request.authenticate(cred)
                return True
            else:
                logger.warning("No PIV certificate available on hardware token for %s", host)
                return False

        elif scheme == WebKit.AuthenticationScheme.CLIENT_CERTIFICATE_PIN_REQUESTED:
            logger.info("Smart card PIN requested for host: %s", host)
            if self.on_pin_requested:
                return self.on_pin_requested(request)
            return False

        return False

    def _on_decide_policy(
        self,
        web_view: WebKit.WebView,
        decision: WebKit.PolicyDecision,
        decision_type: WebKit.PolicyDecisionType,
    ) -> bool:
        """Intercepts navigation and response policy decisions to capture RDP files and restrict domains."""
        if decision_type == WebKit.PolicyDecisionType.RESPONSE:
            response = decision.get_response()
            mime = (response.get_mime_type() or "").lower()
            suggested = (response.get_suggested_filename() or "").lower()
            uri = (response.get_uri() or "").lower()
            if "rdp" in mime or suggested.endswith((".rdp", ".rdpw")) or "rdp" in uri:
                logger.info(
                    "Intercepting RDP response for FreeRDP launch: mime=%s, file=%s",
                    mime,
                    suggested,
                )
                decision.download()
                return True
        elif decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
            action = decision.get_navigation_action()
            uri = (action.get_request().get_uri() or "").lower()

            import urllib.parse
            parsed = urllib.parse.urlparse(uri)
            if parsed.scheme in ("http", "https"):
                hostname = (parsed.hostname or "").lower()
                if not any(hostname == d or hostname.endswith("." + d) for d in ALLOWED_NAVIGATION_DOMAINS):
                    logger.warning("Blocked navigation to unapproved domain: %s", hostname)
                    decision.ignore()
                    return True
            elif parsed.scheme == "blob":
                # Parse the inner URL origin (e.g. blob:https://rdweb.wvd.azure.us/uuid)
                inner_parsed = urllib.parse.urlparse(parsed.path)
                if inner_parsed.scheme in ("http", "https"):
                    hostname = (inner_parsed.hostname or "").lower()
                    if any(hostname == d or hostname.endswith("." + d) for d in ALLOWED_NAVIGATION_DOMAINS):
                        pass  # Allow trusted blob origins
                    else:
                        logger.warning("Blocked navigation to unauthorized blob origin: %s", parsed.path[:60])
                        decision.ignore()
                        return True
                else:
                    decision.ignore()
                    return True
            elif parsed.scheme == "about" and parsed.path == "blank":
                pass
            elif uri.startswith("ms-rd:") or uri.endswith((".rdp", ".rdpw")):
                logger.info("Intercepting RDP navigation: %s", uri)
                decision.download()
                return True
            else:
                logger.warning("Security violation: Blocked navigation to unauthorized scheme: %s (uri: %s)", parsed.scheme, uri[:60])
                decision.ignore()
                return True

            # If it passed http/https/blob domain checks, check if it's an RDP download navigation
            if uri.startswith("ms-rd:") or uri.endswith((".rdp", ".rdpw")):
                logger.info("Intercepting RDP navigation: %s", uri)
                decision.download()
                return True
        return False

    def _on_download_started(
        self, session: WebKit.NetworkSession, download: WebKit.Download
    ) -> None:
        """Intercepts downloads from the web client (e.g. .rdp files)."""
        logger.info("Download started from AVD web client")
        download.connect("decide-destination", self._on_decide_destination)
        download.connect("finished", self._on_download_finished)

    def _on_decide_destination(
        self, download: WebKit.Download, suggested_filename: str
    ) -> bool:
        # Prevent Path Traversal
        safe_filename = os.path.basename(suggested_filename)
        if not safe_filename:
            safe_filename = "session.rdp"

        # Secure user-specific downloads directory (never shared /tmp)
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(DOWNLOADS_DIR, stat.S_IRWXU)

        # Non-destructive collision handling: do not overwrite existing files
        dest_file = DOWNLOADS_DIR / safe_filename
        if dest_file.is_symlink():
            dest_file.unlink()

        stem = dest_file.stem
        suffix = dest_file.suffix
        counter = 1
        while dest_file.exists() or dest_file.is_symlink():
            if dest_file.is_symlink():
                dest_file.unlink()
                break
            dest_file = DOWNLOADS_DIR / f"{stem}_{counter}{suffix}"
            counter += 1

        dest = str(dest_file)
        logger.info("Saving downloaded file to: %s", dest)
        # WebKit requires an absolute filesystem path, NOT a URI
        download.set_destination(dest)
        download.set_allow_overwrite(False)
        return True

    def _on_download_finished(self, download: WebKit.Download) -> None:
        dest_path = download.get_destination()
        if not dest_path:
            return
        if dest_path.startswith("file://"):
            dest_path = dest_path[7:]
        import urllib.parse
        dest_path = urllib.parse.unquote(dest_path)
        logger.info("Download completed: %s", dest_path)
        if dest_path.endswith((".rdp", ".rdpw")) and self.on_rdp_file_ready:
            ready_file = prepare_rdp_file(dest_path)
            # Deliver to RDP launcher
            GLib.idle_add(self.on_rdp_file_ready, ready_file)
