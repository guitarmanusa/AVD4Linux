"""Main Application Window for AVD4Linux."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from .browser import AVDBrowserView
from .clouds import CLOUDS, CloudProfile, get_cloud
from .session_manager import RDPSessionManager
from .smartcard import SmartCardMonitor, SmartCardStatus

logger = logging.getLogger(__name__)


class AVDMainWindow(Adw.ApplicationWindow):
    """Main window with embedded AVD web client and FreeRDP session launcher."""

    def __init__(self, app: Adw.Application, initial_cloud_id: str = "dod") -> None:
        super().__init__(application=app, title="AVD4Linux")
        self.set_default_size(1280, 850)
        self.set_icon_name("org.avd4linux.AVD4Linux")

        try:
            display = Gdk.Display.get_default()
            if display:
                theme = Gtk.IconTheme.get_for_display(display)
                repo_data_dir = Path(__file__).resolve().parent.parent.parent / "data"
                if repo_data_dir.is_dir():
                    theme.add_search_path(str(repo_data_dir))
        except Exception as e:
            logger.debug("Could not add local icon search path: %s", e)

        self.smartcard_monitor = SmartCardMonitor()
        self.session_manager = RDPSessionManager()
        self.current_cloud_id = initial_cloud_id

        # Root box
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root_box)

        # Header Bar
        self.header_bar = Adw.HeaderBar()
        root_box.append(self.header_bar)

        # Navigation buttons
        nav_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        nav_box.add_css_class("linked")

        self.btn_back = Gtk.Button(icon_name="go-previous-symbolic")
        self.btn_back.set_tooltip_text("Back")
        self.btn_back.connect("clicked", lambda _: self.browser.go_back())
        nav_box.append(self.btn_back)

        self.btn_forward = Gtk.Button(icon_name="go-next-symbolic")
        self.btn_forward.set_tooltip_text("Forward")
        self.btn_forward.connect("clicked", lambda _: self.browser.go_forward())
        nav_box.append(self.btn_forward)

        self.btn_reload = Gtk.Button(icon_name="view-refresh-symbolic")
        self.btn_reload.set_tooltip_text("Reload")
        self.btn_reload.connect("clicked", lambda _: self.browser.reload())
        nav_box.append(self.btn_reload)

        self.header_bar.pack_start(nav_box)

        # Cloud Selector Dropdown
        self.cloud_keys = ["dod", "gcc", "commercial"]
        cloud_names = [
            "🇺🇸  Azure US DoD",
            "🏛️  Azure US Gov (GCC High)",
            "🌐  Azure Commercial",
        ]
        self.cloud_dropdown = Gtk.DropDown.new_from_strings(cloud_names)
        self.cloud_dropdown.set_selected(self.cloud_keys.index(self.current_cloud_id))
        self.cloud_dropdown.connect("notify::selected", self._on_cloud_selected)
        self.cloud_dropdown.set_tooltip_text("Select Azure Cloud Environment")
        self.header_bar.pack_start(self.cloud_dropdown)

        # Smart Card Status Badge in Title/Center
        self.sc_button = Gtk.Button()
        self.sc_button.set_has_frame(False)
        self.sc_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.sc_icon = Gtk.Image(icon_name="channel-secure-symbolic")
        self.sc_label = Gtk.Label(label="Checking Card...")
        self.sc_label.add_css_class("caption")
        self.sc_box.append(self.sc_icon)
        self.sc_box.append(self.sc_label)
        self.sc_button.set_child(self.sc_box)
        self.sc_button.set_tooltip_text("Smart Card / CAC Redirection Status")
        self.header_bar.set_title_widget(self.sc_button)

        # Right side actions
        right_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        self.btn_open_rdp = Gtk.Button(label="Open .rdp", icon_name="document-open-symbolic")
        self.btn_open_rdp.set_tooltip_text("Launch an .rdp file with Smart Card Redirection")
        self.btn_open_rdp.connect("clicked", self._on_open_rdp_clicked)
        right_box.append(self.btn_open_rdp)

        self.header_bar.pack_end(right_box)

        # Toast Overlay
        self.toast_overlay = Adw.ToastOverlay()
        root_box.append(self.toast_overlay)

        # Browser View
        self.browser = AVDBrowserView(
            on_rdp_file_ready=self._on_rdp_downloaded,
            on_title_changed=self._on_title_changed,
            on_pin_requested=self._on_pin_requested,
        )
        self.toast_overlay.set_child(self.browser)

        # Initial Load
        self._load_current_cloud()

        # Start Smart Card status polling
        GLib.timeout_add_seconds(2, self._poll_smartcard)
        self._poll_smartcard()

    def _load_current_cloud(self) -> None:
        profile = get_cloud(self.current_cloud_id)
        logger.info("Loading cloud profile: %s -> %s", profile.label, profile.entry_url)
        self.browser.load_url(profile.entry_url)
        self.show_toast(f"Connected to {profile.label}")

    def _on_cloud_selected(self, dropdown: Gtk.DropDown, pspec: object) -> None:
        idx = dropdown.get_selected()
        if 0 <= idx < len(self.cloud_keys):
            new_cloud = self.cloud_keys[idx]
            if new_cloud != self.current_cloud_id:
                self.current_cloud_id = new_cloud
                self._load_current_cloud()

    def _on_title_changed(self, title: str) -> None:
        pass

    def set_cloud(self, cloud_id: str) -> None:
        """Switches the active sovereign cloud environment programmatically."""
        if cloud_id in self.cloud_keys and cloud_id != self.current_cloud_id:
            self.cloud_dropdown.set_selected(self.cloud_keys.index(cloud_id))

    def _poll_smartcard(self) -> bool:
        """Periodic background check for Smart Card."""
        status = self.smartcard_monitor.check_status()
        if status.has_card:
            self.sc_icon.set_from_icon_name("security-high-symbolic")
            self.sc_icon.add_css_class("success")
            self.sc_label.set_text(status.status_text)
            self.sc_button.set_tooltip_text(
                f"{status.card_name} detected in {status.reader_name}.\n"
                "FreeRDP Smart Card redirection (MS-RDPESC) is active."
            )
        elif status.has_reader:
            self.sc_icon.set_from_icon_name("security-medium-symbolic")
            self.sc_icon.remove_css_class("success")
            self.sc_label.set_text("Insert CAC")
            self.sc_button.set_tooltip_text(f"Reader ready: {status.reader_name}. Please insert CAC.")
        else:
            self.sc_icon.set_from_icon_name("security-low-symbolic")
            self.sc_icon.remove_css_class("success")
            self.sc_label.set_text("No Reader")
            self.sc_button.set_tooltip_text(status.status_text)
        return True

    def show_toast(self, message: str, timeout: int = 4) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def _on_rdp_downloaded(self, rdp_path: str) -> None:
        """Triggered automatically when AVD downloads an .rdp file."""
        self.show_toast("Desktop connection received. Launching FreeRDP 3...", timeout=6)
        self._launch_freerdp(rdp_path)

    def _on_open_rdp_clicked(self, btn: Gtk.Button) -> None:
        """Manual file picker to launch any .rdp file with FreeRDP."""
        from gi.repository import Gio
        dialog = Gtk.FileDialog()
        dialog.set_title("Open RDP Connection File")
        f_filter = Gtk.FileFilter()
        f_filter.set_name("RDP Files (*.rdp, *.rdpw)")
        f_filter.add_pattern("*.rdp")
        f_filter.add_pattern("*.rdpw")
        store = Gio.ListStore.new(Gtk.FileFilter)
        store.append(f_filter)
        dialog.set_filters(store)

        dialog.open(self, None, self._on_file_dialog_finished)

    def _on_file_dialog_finished(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            file_obj = dialog.open_finish(result)
            if file_obj:
                path = file_obj.get_path()
                if path and Path(path).is_file():
                    self.show_toast(f"Launching {Path(path).name}...", timeout=4)
                    self._launch_freerdp(path)
        except Exception as e:
            logger.debug("File dialog canceled or error: %s", e)

    def _launch_freerdp(self, rdp_path: str) -> None:
        """Launches FreeRDP 3 with smart card redirection after sanitizing directives."""
        from .browser import prepare_rdp_file
        try:
            sanitized_path = prepare_rdp_file(rdp_path)
            self.session_manager.launch_rdp_file(
                sanitized_path,
                on_exit=lambda rc: GLib.idle_add(self._on_session_exit, rc),
                on_auth_url_needed=lambda url: GLib.idle_add(self._on_auth_url_needed, url),
                on_cert_trust_needed=lambda info, cb: GLib.idle_add(self._on_cert_trust_needed, info, cb),
            )
        except Exception as e:
            self.show_toast(f"Failed to launch FreeRDP: {e}", timeout=6)

    def _on_cert_trust_needed(self, cert_info: dict[str, str], response_cb: Callable[[str], None]) -> None:
        """Presents an interactive modal dialog showing certificate details before accepting."""
        host = GLib.markup_escape_text(cert_info.get("host", "Remote Gateway"))
        fingerprint = GLib.markup_escape_text(cert_info.get("fingerprint", "Unknown"))
        subject = GLib.markup_escape_text(cert_info.get("subject", ""))
        issuer = GLib.markup_escape_text(cert_info.get("issuer", ""))

        body_lines = [
            f"FreeRDP received an untrusted server certificate for:\n<b>{host}</b>\n",
        ]
        if subject:
            body_lines.append(f"<b>Subject:</b> {subject}")
        if issuer:
            body_lines.append(f"<b>Issuer:</b> {issuer}")
        if fingerprint:
            body_lines.append(f"<b>SHA-256 Fingerprint:</b>\n<tt>{fingerprint}</tt>\n")
        body_lines.append("Do you trust this certificate to establish the remote desktop session?")

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Untrusted Server Certificate",
            body="\n".join(body_lines),
        )
        dialog.set_body_use_markup(True)
        dialog.add_response("reject", "Reject & Disconnect")
        dialog.add_response("trust_once", "Trust Once")
        dialog.add_response("trust_always", "Trust Always")
        dialog.set_response_appearance("reject", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_response_appearance("trust_always", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("reject")
        dialog.set_close_response("reject")

        def on_response(dlg, response):
            if response == "trust_always":
                logger.info("User chose to permanently trust certificate for %s", host)
                response_cb("T")
            elif response == "trust_once":
                logger.info("User chose to trust certificate once for %s", host)
                response_cb("Y")
            else:
                logger.warning("User rejected certificate for %s; disconnecting session", host)
                response_cb("N")
                self.session_manager.terminate_session()
                self.show_toast(f"Connection to {host} rejected (untrusted certificate).", timeout=4)

        dialog.connect("response", on_response)
        dialog.present()

    def _on_auth_url_needed(self, auth_url: str) -> None:
        """Handles FreeRDP's AAD OAuth authorization challenge using the active WebKit session."""
        import urllib.parse
        parsed = urllib.parse.urlparse(auth_url)
        allowed_hosts = {
            "login.microsoftonline.com",
            "login.microsoftonline.us",
            "certauth.login.microsoftonline.com",
            "certauth.login.microsoftonline.us",
        }
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_hosts:
            logger.error("Security violation: Blocked untrusted OAuth authorization URL: %s", auth_url)
            self.show_toast("Security Warning: Blocked untrusted authentication URL!", timeout=6)
            self.session_manager.terminate_session()
            return

        logger.info("Handling FreeRDP AAD challenge: %s", auth_url)
        self.show_toast("Authorizing desktop session with Entra ID...", timeout=6)

        import gi
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit

        auth_win = Adw.Window(transient_for=self, modal=True, title="Authorizing Desktop Session")
        auth_win.set_default_size(520, 640)

        header = Adw.HeaderBar()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(header)

        auth_view = WebKit.WebView(network_session=self.browser.network_session)
        auth_view.set_hexpand(True)
        auth_view.set_vexpand(True)
        box.append(auth_view)
        auth_win.set_content(box)

        # Automatically reuse CAC certificate and cached PIN
        auth_view.connect("authenticate", self.browser._on_authenticate)

        handled = False

        def complete_auth(uri: str):
            nonlocal handled
            if handled:
                return
            handled = True
            logger.info("Captured OAuth redirect code for FreeRDP: %s", uri[:80])
            self.session_manager.feed_auth_url(uri)
            self.show_toast("Opening remote desktop session...", timeout=4)
            GLib.idle_add(auth_win.close)

        def on_auth_policy(view, decision, decision_type):
            if decision_type == WebKit.PolicyDecisionType.NAVIGATION_ACTION:
                action = decision.get_navigation_action()
                uri = action.get_request().get_uri() or ""
                if "nativeclient" in uri and "code=" in uri:
                    decision.ignore()
                    complete_auth(uri)
                    return True

                parsed = urllib.parse.urlparse(uri)
                if parsed.scheme in ("http", "https"):
                    hostname = (parsed.hostname or "").lower()
                    allowed_auth_domains = (
                        "login.microsoftonline.com",
                        "login.microsoftonline.us",
                        "certauth.login.microsoftonline.com",
                        "certauth.login.microsoftonline.us",
                        "msauth.net",
                        "msftauth.net",
                    )
                    if not any(hostname == d or hostname.endswith("." + d) for d in allowed_auth_domains):
                        logger.warning("Security violation in auth window: Blocked navigation to unapproved domain: %s", hostname)
                        decision.ignore()
                        return True
                elif parsed.scheme == "about" and parsed.path == "blank":
                    return False
                else:
                    logger.warning("Security violation in auth window: Blocked navigation to unauthorized scheme: %s", parsed.scheme)
                    decision.ignore()
                    return True
            return False

        def on_auth_load(view, event):
            uri = view.get_uri() or ""
            if "nativeclient" in uri and "code=" in uri:
                complete_auth(uri)

        def on_close_request(win):
            nonlocal handled
            if not handled:
                handled = True
                logger.info("User closed authorization window before completing")
                self.session_manager.terminate_session()
            return False

        auth_win.connect("close-request", on_close_request)
        auth_view.connect("decide-policy", on_auth_policy)
        auth_view.connect("load-changed", on_auth_load)

        auth_win.present()
        auth_view.load_uri(auth_url)

    def _on_session_exit(self, exit_code: int) -> None:
        if exit_code == 0:
            self.show_toast("FreeRDP session completed normally.")
        else:
            self.show_toast(f"FreeRDP session ended (exit code: {exit_code}).")

    def _on_pin_requested(self, request) -> bool:
        """Prompts for the CAC PIN and submits it directly to WebKit with zero caching."""
        try:
            status = self.smartcard_monitor.check_status()
            card_desc = status.card_name
            if status.has_card:
                card_desc = f"{status.card_name} ({status.reader_name})"

            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Smart Card PIN Required",
                body=f"Enter your PIN to authenticate with your CAC ({card_desc}) for Azure Virtual Desktop.",
            )

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            box.set_margin_top(12)
            box.set_margin_bottom(12)

            entry = Gtk.PasswordEntry()
            entry.set_show_peek_icon(True)
            box.append(entry)

            dialog.set_extra_child(box)
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("unlock", "Unlock Card")
            dialog.set_response_appearance("unlock", Adw.ResponseAppearance.SUGGESTED)
            dialog.set_default_response("unlock")
            dialog.set_close_response("cancel")

            def on_response(dlg, response):
                try:
                    import gi
                    gi.require_version("WebKit", "6.0")
                    from gi.repository import WebKit
                    if response == "unlock":
                        pin = entry.get_text()
                        if pin:
                            logger.info("Submitting CAC PIN directly to WebKit (FOR_SESSION)")
                            cred = WebKit.Credential.new_for_certificate_pin(
                                pin, WebKit.CredentialPersistence.FOR_SESSION
                            )
                            del pin
                            request.authenticate(cred)
                        else:
                            request.cancel()
                    else:
                        request.cancel()
                except Exception as e:
                    logger.error("Error submitting PIN credential: %s", e)
                    request.cancel()
                finally:
                    entry.set_text("")
                    dlg.close()

            dialog.connect("response", on_response)
            entry.connect("activate", lambda _: dialog.response("unlock"))
            dialog.present()
            entry.grab_focus()
            return True
        except Exception as e:
            logger.error("Error presenting PIN dialog: %s", e)
            return False
