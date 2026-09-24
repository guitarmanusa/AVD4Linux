# AVD4Linux — Native Linux Client for Azure Virtual Desktop

[![Flatpak Build](https://github.com/avd4linux/AVD4Linux/actions/workflows/flatpak.yml/badge.svg)](https://github.com/avd4linux/AVD4Linux/actions/workflows/flatpak.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey.svg)](https://www.kernel.org)
[![FreeRDP](https://img.shields.io/badge/FreeRDP-3.x-red.svg)](https://www.freerdp.com)

**AVD4Linux** is an open-source, native Linux desktop application for accessing **Azure Virtual Desktop (AVD)** workspaces with first-class **Smart Card (DoD CAC / PIV) redirection**. 

Designed for mission-critical and enterprise environments, AVD4Linux provides seamless access across **Azure US DoD**, **Azure US Government (GCC High)**, and **Azure Commercial** sovereign clouds with hardware token pass-through out of the box.

---

## Technology Stack

AVD4Linux is built using modern, distro-agnostic Linux desktop technologies:

| Component | Technology | Role |
|---|---|---|
| **User Interface** | **GTK 4** & **Libadwaita 1** | Native GNOME/Linux desktop interface with system styling, adaptive layout, and dark/light mode support. |
| **Authentication & Web** | **WebKitGTK 6.0** (WebKit2) | Embedded web engine for Azure Virtual Desktop workspace navigation and Microsoft Entra ID authentication. |
| **Smart Card Subsystem** | **PC/SC Lite** (`libpcsclite.so.1`) | Real-time monitoring of USB smart card readers (e.g. Alcor Micro AU9540, Identiv SCR3310, SCM SCR) and card insertion events via zero-dependency `ctypes`. |
| **PKCS#11 Security Bridge** | **OpenSC** & **p11-kit** | Hardware token cryptographic provider exposing PIV Authentication certificates (`id=%01`) and keys for Entra ID Certificate-Based Authentication (CBA). |
| **RDP Protocol Engine** | **FreeRDP 3.x** (`xfreerdp3`) | High-performance remote desktop client providing MS-RDPESC smart card channel redirection, hardware-accelerated graphics (`/gfx /rfx`), and Azure AD gateway integration. |
| **App Packaging** | **Flatpak** (GNOME 47 Runtime) | Sandboxed, distro-agnostic distribution ready for standalone bundling and Flathub deployment. |

---

## How It Works

AVD4Linux bridges modern Linux desktop security standards with Microsoft's Azure Virtual Desktop sovereign cloud infrastructure through a four-phase workflow:

```
┌────────────────────────────────────────────────────────────────────────┐
│                              AVD4Linux                                 │
│                                                                        │
│  1. Entra ID CBA Login        2. Workspace Feed        3. Session Handshake  │
│  ┌───────────────────┐        ┌───────────────────┐    ┌─────────────────┐ │
│  │ WebKitGTK 6       │───────>│ Web Client Engine │───>│ Intercept .rdpw │ │
│  │ + Native PIN Box  │        │ (Desktops / Apps) │    │ & Extract Tenant│ │
│  └───────────────────┘        └───────────────────┘    └─────────────────┘ │
│           ▲                                                      │         │
│           │ PKCS#11                                              │         │
│  ┌───────────────────┐                                           ▼         │
│  │ Host PC/SC daemon │                                 ┌─────────────────┐ │
│  │ (DoD CAC / AU9540)│                                 │ FreeRDP 3 PTY   │ │
│  └───────────────────┘                                 │ AAD Token Bridge│ │
│           ▲                                            └─────────────────┘ │
│           │                                                      │         │
└───────────┼──────────────────────────────────────────────────────┼─────────┘
            │ MS-RDPESC Virtual Channel                            │
            ▼                                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │                      Azure Virtual Desktop Host                        │
  │                  (Remote Windows Desktop Session)                      │
  │   - Full CAC Passthrough to Windows Apps (Edge, Outlook, Teams)       │
  └────────────────────────────────────────────────────────────────────────┘
```

1. **Sovereign Cloud Selection & Web Authentication**:
   - The user selects their Azure environment (DoD, GCC High, or Commercial) from the header dropdown.
   - AVD4Linux loads the designated entry point in the embedded WebKitGTK 6.0 view.
   - When Microsoft Entra ID initiates mutual TLS (`*.certauth.login.microsoftonline.us`), AVD4Linux queries the hardware token via PKCS#11, prompts the user for their CAC PIN in a native Libadwaita modal dialog, and completes the client certificate handshake.
   - Session cookies and state persist securely across application restarts in `~/.local/share/avd4linux/webdata/`.

2. **Workspace Navigation & Launch Interception**:
   - Upon authentication, the Azure Virtual Desktop workspace renders the user's assigned host pools, remote desktops, and published applications.
   - When the user launches a remote resource, AVD4Linux intercepts the `.rdpw`/`.rdp` download stream.
   - The application parses the connection payload, extracts the sovereign tenant configuration (`aadtenantid`, `loadbalanceinfo`, `gatewayhostname`), and normalizes it for FreeRDP 3.

3. **Automated Sovereign Token Handshake**:
   - FreeRDP 3 is spawned on a dedicated pseudo-terminal (PTY) to prevent terminal I/O collisions.
   - AVD4Linux configures the Azure sovereign parameters (`/azure:ad:login.microsoftonline.us,use-tenantid:on,tenantid:...`).
   - When the gateway requests an AAD session authorization code, AVD4Linux handles the exchange in the background using the active authenticated session and pipes the response directly into FreeRDP.

4. **Native Remote Session with Smart Card Passthrough**:
   - FreeRDP 3 establishes the session to the remote desktop with hardware acceleration (`+fonts /gfx /rfx /network:auto`).
   - The smart card channel (`/smartcard /smartcard-logon`) connects the local PC/SC reader directly into the remote Windows session via the standard Microsoft MS-RDPESC protocol.

---

## Range of Capabilities

- **Multi-Cloud Support**:
  - 🇺🇸 **Azure US DoD**: `rdweb.wvd.azure.us` with `login.microsoftonline.us`, DISA host pools, and `@mail.mil` authentication.
  - 🏛️ **Azure US Government (GCC High)**: `rdweb.wvd.azure.us` with US Government compliance boundaries.
  - 🌐 **Azure Commercial**: `rdweb.wvd.microsoft.com` with `login.microsoftonline.com`.
- **Out-of-the-Box Smart Card Redirection**:
  - Automatically redirects physical smart card readers (including Alcor Micro AU9540, Identiv, SCM, and Omnikey) into the remote session.
  - Full support for DoD CAC (Common Access Card) and PIV (Personal Identity Verification) cards.
  - Once connected, your CAC is fully functional inside the remote Windows desktop for:
    - Signing into DoD and government websites in Edge/Chrome.
    - Signing and decrypting emails in Outlook.
    - Authenticating with internal military/government web portals.
- **Live Hardware Status**:
  - The window header bar features a live smart card monitor that displays card reader presence and card insertion status in real time.
- **Direct `.rdp` File Launcher**:
  - Includes an **"Open .rdp"** button in the header to launch any standalone `.rdp` connection file directly into FreeRDP 3 with smart card redirection and hardware acceleration.
- **Developer Tools**:
  - Press **F12** at any time to open the WebKit Developer Inspector (DOM, Console, Network) to diagnose connection flows.

---

## Prerequisites & System Requirements

Before running AVD4Linux, your Linux host must have a working smart card reader driver and the appropriate certificate authority trust store installed.

### 1. Smart Card Reader & PC/SC Daemon
AVD4Linux communicates with your smart card reader through the Linux PC/SC daemon (`pcscd`). Ensure `pcscd` and OpenSC are installed and active:

```bash
# Ubuntu / Debian
sudo apt install pcscd pcsc-tools opensc libpcsclite1
sudo systemctl enable --now pcscd

# Fedora / RHEL
sudo dnf install pcsc-lite pcsc-lite-ccid pcsc-tools opensc
sudo systemctl enable --now pcscd

# Arch Linux
sudo pacman -S pcsclite ccid opensc
sudo systemctl enable --now pcscd
```

Verify your smart card reader is detected by running:
```bash
pcsc_scan
```
*(Your reader name, such as `Alcor Micro AU9540`, and card ATR should be displayed).*

### 2. DoD Root & Intermediate CA Certificates (DoD / US Gov Users)
If connecting to Azure US DoD or GCC High environments, your Linux operating system must trust the DoD Root and Intermediate Certificate Authorities. **You must install the official DoD PKI CA bundle on your host system.**

To install DoD certificates on Ubuntu/Debian:
```bash
# Download and extract the DoD PKI CA bundle (e.g. from DoD Cyber Exchange or militarycac.com)
# Place the DoD .crt files into /usr/local/share/ca-certificates/
sudo cp DoD_CAs/*.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates

# Import certificates into your user's NSS database (required for WebKitGTK and Chrome)
for cert in /usr/local/share/ca-certificates/*.crt; do
    certutil -d sql:$HOME/.pki/nssdb -A -t "TC,C,C" -n "$(basename "$cert")" -i "$cert"
done
```

---

## Installation & Usage

### Running from Source

```bash
# 1. Clone repository
git clone https://github.com/<YOUR_USERNAME>/AVD4Linux.git
cd AVD4Linux

# 2. Run the application
bin/avd4linux

# Or specify a target cloud directly:
bin/avd4linux --cloud dod          # Azure US DoD (default)
bin/avd4linux --cloud gcc          # Azure US Government (GCC High)
bin/avd4linux --cloud commercial   # Azure Commercial

# Or launch an existing .rdp file directly:
bin/avd4linux --rdp ~/Downloads/my-session.rdp
```

### Desktop Menu Integration
To add AVD4Linux to your desktop application launcher:
```bash
ln -sf $(pwd)/bin/avd4linux ~/.local/bin/avd4linux
cp data/org.avd4linux.AVD4Linux.desktop ~/.local/share/applications/
cp data/org.avd4linux.AVD4Linux.svg ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications/ 2>/dev/null || true
gtk-update-icon-cache -f ~/.local/share/icons/hicolor/ 2>/dev/null || true
```

---

## Packaging as Flatpak & Flathub Release

AVD4Linux is structured for Flatpak distribution. The repository includes:
- **Flatpak Manifest**: `packaging/flatpak/org.avd4linux.AVD4Linux.yaml` (configured with sandbox exceptions for PC/SC daemon access: `--device=all`, `--filesystem=/run/pcscd`).
- **AppStream Metainfo**: `data/org.avd4linux.AVD4Linux.metainfo.xml`.
- **GitHub Actions CI/CD**: `.github/workflows/flatpak.yml` (automatically compiles `.flatpak` binary bundles on release tags).

See [docs/packaging-and-flathub.md](docs/packaging-and-flathub.md) for full instructions on building standalone `.flatpak` bundles and submitting to Flathub.

---

## Limitations

- **Host Smart Card Setup**: The application relies on the host's `pcscd` service and USB CCID driver. If your reader is not detected in `pcsc_scan`, verify your USB reader hardware and CCID drivers.
- **DoD CA Trust**: If the host system trust store does not contain the DoD Root and Intermediate CAs, WebKitGTK and FreeRDP will reject the sovereign gateway TLS certificates. Follow the prerequisite instructions above to install the DoD CA certificates.
- **Physical CAC Requirement**: Certificate-Based Authentication and remote desktop smart card redirection require physical presence of the CAC/PIV card in the reader and PIN entry for cryptographic signing operations.

---

## License

This project is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for details.

Azure Virtual Desktop and Microsoft Entra are registered trademarks of Microsoft Corporation. AVD4Linux is an independent open-source project and is not affiliated with or endorsed by Microsoft Corporation.
