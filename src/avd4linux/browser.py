"""Embedded WebKitGTK 6.0 view for AVD4Linux authentication and workspace access."""
from __future__ import annotations

import logging
import os
import stat
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
        self._cached_pin: Optional[str] = None
        self._pin_timer_id: Optional[int] = None

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

    def set_cached_pin(self, pin: str, timeout_seconds: int = 60) -> None:
        """Temporarily caches the PIN to satisfy consecutive mTLS requests, with strict timeout."""
        self.clear_cached_pin()
        self._cached_pin = pin
        self._pin_timer_id = GLib.timeout_add_seconds(timeout_seconds, self.clear_cached_pin)

    def clear_cached_pin(self) -> bool:
        """Purges the cached PIN from memory."""
        if hasattr(self, "_cached_pin") and self._cached_pin:
            self._cached_pin = None
            logger.info("Cached CAC PIN purged from memory")
        if hasattr(self, "_pin_timer_id") and self._pin_timer_id:
            GLib.source_remove(self._pin_timer_id)
            self._pin_timer_id = None
        return False

    def _on_load_state_changed(
        self, web_view: WebKit.WebView, load_event: WebKit.LoadEvent
    ) -> None:
        if load_event == WebKit.LoadEvent.STARTED:
            self.progress_bar.set_visible(True)
            self.progress_bar.set_fraction(0.1)
        elif load_event == WebKit.LoadEvent.FINISHED:
            self.progress_bar.set_visible(False)
            uri = web_view.get_uri() or ""
            # Once arrived at the AVD workspace, purge the temporary PIN cache
            if "arm/webclient" in uri:
                self.clear_cached_pin()

    def _on_authenticate(
        self, web_view: WebKit.WebView, request: WebKit.AuthenticationRequest
    ) -> bool:
        """Handles authentication requests, including smartcard client certificates."""
        scheme = request.get_scheme()
        host = request.get_host()
        logger.info("Authentication requested: scheme=%s, host=%s", scheme, host)

        if scheme == WebKit.AuthenticationScheme.CLIENT_CERTIFICATE_REQUESTED:
            from .smartcard import get_piv_tls_certificate
            if getattr(self, "_cached_pin", None):
                cert = get_piv_tls_certificate(pin=self._cached_pin)
                if cert:
                    logger.info("Providing PIV client certificate with temporary cached PIN for %s", host)
                    cred = WebKit.Credential.new_for_certificate(
                        cert, WebKit.CredentialPersistence.FOR_SESSION
                    )
                    request.authenticate(cred)
                    return True

            if self.on_pin_requested:
                logger.info("Prompting user for CAC PIN to unlock PIV Authentication key for %s", host)
                return self.on_pin_requested(request)

            cert = get_piv_tls_certificate()
            if cert:
                cred = WebKit.Credential.new_for_certificate(
                    cert, WebKit.CredentialPersistence.FOR_SESSION
                )
                request.authenticate(cred)
                return True
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
        """Intercepts navigation and response policy decisions to capture RDP files."""
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

        dest = str(DOWNLOADS_DIR / safe_filename)
        logger.info("Saving downloaded file to: %s", dest)
        # WebKit requires an absolute filesystem path, NOT a URI
        download.set_destination(dest)
        download.set_allow_overwrite(True)
        return True

    def _on_download_finished(self, download: WebKit.Download) -> None:
        dest_path = download.get_destination()
        if not dest_path:
            return
        dest_path = dest_path.replace("file://", "")
        logger.info("Download completed: %s", dest_path)
        if dest_path.endswith((".rdp", ".rdpw")) and self.on_rdp_file_ready:
            ready_file = self._prepare_rdp_file(dest_path)
            # Deliver to RDP launcher
            GLib.idle_add(self.on_rdp_file_ready, ready_file)

    def _prepare_rdp_file(self, dest_path: str) -> str:
        """Ensures the downloaded file is a valid .rdp file for FreeRDP."""
        p = Path(dest_path)
        if not p.exists():
            return dest_path
        
        rdp_out = p.with_suffix(".rdp")
        try:
            raw = p.read_bytes()
            text = None
            for enc in ["utf-8", "utf-16", "latin1"]:
                try:
                    text = raw.decode(enc)
                    break
                except Exception:
                    continue

            if text:
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
                if not any(k in text for k in ["full address", "gatewayhostname", "loadbalanceinfo"]):
                    try:
                        decoded = base64.b64decode(text.strip()).decode("utf-8", errors="replace")
                        if any(k in decoded for k in ["full address", "gateway", "loadbalanceinfo"]):
                            text = decoded
                    except Exception:
                        pass

                # Sanitize high-risk directives that could mount local drives or execute unauthorized binaries
                FORBIDDEN_PREFIXES = ("drivestoredirect", "alternate shell", "initial program")
                clean_lines = [
                    line for line in text.splitlines()
                    if not any(line.strip().lower().startswith(p) for p in FORBIDDEN_PREFIXES)
                ]
                text = "\r\n".join(clean_lines) + "\r\n"

                rdp_out.write_text(text, encoding="utf-8")
                os.chmod(rdp_out, stat.S_IRUSR | stat.S_IWUSR)
                logger.info("Prepared RDP file for FreeRDP: %s", rdp_out)
                return str(rdp_out)
        except Exception as e:
            logger.error("Failed to process downloaded RDP file %s: %s", dest_path, e)

        return dest_path
