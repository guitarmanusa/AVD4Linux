"""Embedded WebKitGTK 6.0 view for AVD authentication and workspace access."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import GLib, Gtk, WebKit

logger = logging.getLogger(__name__)

USER_DATA_DIR = Path.home() / ".local" / "share" / "avd-linux"
WEB_DATA_DIR = USER_DATA_DIR / "webdata"


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
        self.cached_pin: Optional[str] = None

        WEB_DATA_DIR.mkdir(parents=True, exist_ok=True)

        # Setup WebKit settings
        settings = WebKit.Settings()
        settings.set_enable_developer_extras(True)
        settings.set_enable_smooth_scrolling(True)
        settings.set_enable_webgl(True)
        settings.set_javascript_can_open_windows_automatically(True)

        # Modern Chrome/Edge user agent so Microsoft Entra and AVD accept modern capabilities
        ua = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 Edg/128.0.0.0"
        )
        settings.set_user_agent(ua)

        # Configure network session with persistent storage
        website_mgr = WebKit.WebsiteDataManager(
            base_data_directory=str(WEB_DATA_DIR),
            base_cache_directory=str(WEB_DATA_DIR / "cache"),
        )
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
        """Handles authentication requests, including smartcard client certificates."""
        scheme = request.get_scheme()
        host = request.get_host()
        logger.info("Authentication requested: scheme=%s, host=%s", scheme, host)

        if scheme == WebKit.AuthenticationScheme.CLIENT_CERTIFICATE_REQUESTED:
            from .smartcard import get_piv_tls_certificate
            if self.cached_pin:
                cert = get_piv_tls_certificate(pin=self.cached_pin)
                if cert:
                    logger.info("Providing PIV client certificate with cached PIN for %s", host)
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
        tmp_dir = Path(tempfile.gettempdir()) / "avd-linux-downloads"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        dest = str(tmp_dir / suggested_filename)
        logger.info("Saving downloaded file to: %s", dest)
        download.set_destination(f"file://{dest}")
        download.set_allow_overwrite(True)
        return True

    def _on_download_finished(self, download: WebKit.Download) -> None:
        dest_uri = download.get_destination()
        if not dest_uri:
            return
        dest_path = dest_uri.replace("file://", "")
        logger.info("Download completed: %s", dest_path)
        if dest_path.endswith(".rdp") and self.on_rdp_file_ready:
            # Deliver to RDP launcher
            GLib.idle_add(self.on_rdp_file_ready, dest_path)
