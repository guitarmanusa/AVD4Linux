"""Main Application Window for AVD Linux Client."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("WebKit", "6.0")
from gi.repository import Adw, GLib, Gtk

from .browser import AVDBrowserView
from .clouds import CLOUDS, CloudProfile, get_cloud
from .session_manager import RDPSessionManager
from .smartcard import SmartCardMonitor, SmartCardStatus

logger = logging.getLogger(__name__)


class AVDMainWindow(Adw.ApplicationWindow):
    """Main window with embedded AVD web client and FreeRDP session launcher."""

    def __init__(self, app: Adw.Application, initial_cloud_id: str = "dod") -> None:
        super().__init__(application=app, title="Azure Virtual Desktop")
        self.set_default_size(1280, 850)

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

        # F12 Web Inspector Shortcut
        key_ctrl = Gtk.EventControllerKey()
        def on_key_pressed(controller, keyval, keycode, state):
            from gi.repository import Gdk
            if keyval == Gdk.KEY_F12:
                inspector = self.browser.web_view.get_inspector()
                inspector.show()
                return True
            return False
        key_ctrl.connect("key-pressed", on_key_pressed)
        self.add_controller(key_ctrl)

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
        dialog = Gtk.FileDialog()
        dialog.set_title("Open RDP Connection File")
        f_filter = Gtk.FileFilter()
        f_filter.set_name("RDP Files (*.rdp)")
        f_filter.add_pattern("*.rdp")
        filters = Gtk.FilterListModel()

        dialog.open(self, None, self._on_file_dialog_finished)

    def _on_file_dialog_finished(self, dialog: Gtk.FileDialog, result: object) -> None:
        try:
            file_obj = dialog.open_finish(result)
            if file_obj:
                path = file_obj.get_path()
                if path:
                    self.show_toast(f"Launching {Path(path).name}...", timeout=4)
                    self._launch_freerdp(path)
        except Exception as e:
            logger.debug("File dialog canceled or error: %s", e)

    def _launch_freerdp(self, rdp_path: str) -> None:
        """Launches FreeRDP 3 with smart card redirection."""
        try:
            self.session_manager.launch_rdp_file(
                rdp_path,
                on_exit=lambda rc: GLib.idle_add(self._on_session_exit, rc),
                on_auth_url_needed=lambda url: GLib.idle_add(self._on_auth_url_needed, url),
            )
        except Exception as e:
            self.show_toast(f"Failed to launch FreeRDP: {e}", timeout=6)

    def _on_auth_url_needed(self, auth_url: str) -> None:
        """Handles FreeRDP's AAD OAuth authorization challenge using the active WebKit session."""
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
            return False

        def on_auth_load(view, event):
            uri = view.get_uri() or ""
            if "nativeclient" in uri and "code=" in uri:
                complete_auth(uri)

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
        """Presents a native Libadwaita modal dialog asking for the CAC PIN."""
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
                    from .smartcard import get_piv_tls_certificate
                    if response == "unlock":
                        pin = entry.get_text().strip()
                        if pin:
                            logger.info("Submitting CAC PIN and Certificate to WebKit")
                            self.browser.cached_pin = pin
                            scheme = request.get_scheme()
                            if scheme == WebKit.AuthenticationScheme.CLIENT_CERTIFICATE_PIN_REQUESTED:
                                cred = WebKit.Credential.new_for_certificate_pin(
                                    pin, WebKit.CredentialPersistence.FOR_SESSION
                                )
                            else:
                                cert = get_piv_tls_certificate(pin=pin)
                                if cert:
                                    logger.info("Loaded PIV certificate with private key unlocked by PIN")
                                    cred = WebKit.Credential.new_for_certificate(
                                        cert, WebKit.CredentialPersistence.FOR_SESSION
                                    )
                                else:
                                    logger.error("Could not load PIV certificate with provided PIN")
                                    request.cancel()
                                    dlg.close()
                                    return
                            request.authenticate(cred)
                        else:
                            request.cancel()
                    else:
                        request.cancel()
                except Exception as e:
                    logger.error("Error in PIN response handler: %s", e)
                    request.cancel()
                finally:
                    dlg.close()

            dialog.connect("response", on_response)
            entry.connect("activate", lambda _: dialog.response("unlock"))
            dialog.present()
            entry.grab_focus()
            return True
        except Exception as e:
            logger.error("Error presenting PIN dialog: %s", e)
            return False
