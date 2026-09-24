# AVD4Linux — Native Linux Client for Azure Virtual Desktop

**AVD4Linux** is a native, modern Linux desktop client for **Azure Virtual Desktop (AVD)** with first-class **Smart Card (DoD CAC / PIV) redirection**, supporting **Azure US DoD**, **Azure US Government (GCC High)**, and **Azure Commercial**.

Built with **GTK 4**, **Libadwaita**, **WebKitGTK 6**, and **FreeRDP 3**.

---

## Features

- **Native Linux Experience**: Modern GNOME/Adwaita user interface conforming to Linux desktop standards with dark/light mode.
- **DoD CAC & PIV Smart Card Redirection**: Full MS-RDPESC smart card channel redirection via FreeRDP 3 and host PC/SC daemon (`pcscd`).
- **Sovereign Cloud Switcher**:
  - 🇺🇸 **Azure US DoD** (`rdweb.wvd.azure.us`)
  - 🏛️ **Azure US Government (GCC High)** (`rdweb.wvd.azure.us`)
  - 🌐 **Azure Commercial** (`rdweb.wvd.microsoft.com`)
- **Live Smart Card Detection**: Real-time status indicator in the window title bar showing reader and card state (`Alcor Micro AU9540`, `DoD PIV`).
- **Seamless RDP Launch**: Intercepts Azure Virtual Desktop workspace connections and launches high-performance native FreeRDP 3 with smart card redirection and hardware acceleration.
- **Direct .rdp Launcher**: "Open .rdp" button to launch any downloaded or custom RDP configuration file directly with FreeRDP 3.

---

## Running AVD4Linux

### From Application Menu
Search for **"AVD4Linux"** in your GNOME / desktop application launcher.

### From Terminal
```bash
# Launch default (Azure US DoD environment)
bin/avd4linux

# Or specify cloud target
bin/avd4linux --cloud dod
bin/avd4linux --cloud gcc
bin/avd4linux --cloud commercial

# Launch a specific .rdp file directly with Smart Card redirection
bin/avd4linux --rdp ~/Downloads/my-desktop.rdp
```

---

## Standalone Flatpak & Flathub Packaging

See [docs/packaging-and-flathub.md](docs/packaging-and-flathub.md) for full instructions on:
- Building a standalone `.flatpak` bundle.
- Submitting to Flathub.
- Automated GitHub Actions build pipeline.

---

## Architecture

1. **Authentication & Web Client Layer (`src/avd4linux/browser.py`)**:
   - WebKitGTK 6.0 embedded view for Azure Virtual Desktop authentication and feed navigation.
   - Entra ID Certificate-Based Authentication (CBA) supported via host PKCS#11 (`opensc-pkcs11.so`, `p11-kit-trust`).
   - Downloads of `.rdp` session files are intercepted automatically.

2. **Smart Card Monitoring (`src/avd4linux/smartcard.py`)**:
   - Zero-dependency `ctypes` bindings to `libpcsclite.so.1`.
   - Polls PC/SC context, detects card insertion/removal, and notifies the UI.

3. **Session Management (`src/avd4linux/session_manager.py`)**:
   - Executes `/opt/freerdp3/usr/bin/xfreerdp3`.
   - Injects `/smartcard`, `/smartcard-logon`, `/cert:ignore`, `/network:auto`, `+fonts`, `/gfx`, `/rfx`.
   - Manages PTY pseudo-terminals and handles sovereign Azure AD authorization challenges automatically.

4. **Desktop UI (`src/avd4linux/window.py`, `src/avd4linux/app.py`)**:
   - `Adw.ApplicationWindow` with modern Adwaita controls, toasts, and cloud switcher.
