# AVD4Linux — Native Linux Client for Azure Virtual Desktop

[![Flatpak Build](https://github.com/guitarmanusa/AVD4Linux/actions/workflows/flatpak.yml/badge.svg)](https://github.com/guitarmanusa/AVD4Linux/actions/workflows/flatpak.yml)
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
| **Native C Security Bridge** | **Compiled C Extension** (`_pin_bridge`) | Audit-proof CAC PIN credential bridge transferring secrets directly from GTK to WebKit in C memory with cryptographic zeroing (`OPENSSL_cleanse` + `explicit_bzero`), completely bypassing the Python heap. |
| **Smart Card Subsystem** | **PC/SC Lite** (`libpcsclite.so.1`) | Non-intrusive real-time monitoring of USB smart card readers via `SCardGetStatusChange` without connection resets or bus transaction interruptions. |
| **PKCS#11 Security Bridge** | **OpenSC** & **GnuTLS** | In-process hardware token cryptographic provider auto-registered with GnuTLS (`/etc/gnutls/pkcs11.conf`) exposing PIV Authentication certificates (`id=%01`) and keys for Entra ID Certificate-Based Authentication (CBA). |
| **RDP Protocol Engine** | **FreeRDP 3.x** (`xfreerdp3`) | High-performance remote desktop client providing MS-RDPESC smart card channel redirection, hardware-accelerated graphics (`/gfx /rfx`), X11/Xwayland display support, and automated AAD gateway integration (`/cert:tofu`). |
| **App Packaging** | **Flatpak** (GNOME 47 Runtime) | Sandboxed, distro-agnostic distribution ready for standalone bundling and Flathub deployment. |

---

## How It Works

AVD4Linux bridges modern Linux desktop security standards with Microsoft's Azure Virtual Desktop sovereign cloud infrastructure through a four-phase workflow:

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                    AVD4Linux                                 │
│                                                                              │
│  1. Entra ID CBA Login        2. Workspace Feed        3. Session Handshake  │
│  ┌───────────────────┐        ┌───────────────────┐    ┌─────────────────┐   │
│  │ WebKitGTK 6       │───────>│ Web Client Engine │───>│ Intercept .rdpw │   │
│  │ + Native PIN Box  │        │ (Desktops / Apps) │    │ & Extract Tenant│   │
│  └───────────────────┘        └───────────────────┘    └─────────────────┘   │
│           ▲                                                      │           │
│           │ PKCS#11                                              │           │
│  ┌───────────────────┐                                           ▼           │
│  │ Host PC/SC daemon │                                 ┌─────────────────┐   │
│  │ (DoD CAC / AU9540)│                                 │ FreeRDP 3 PTY   │   │
│  └───────────────────┘                                 │ AAD Token Bridge│   │
│           ▲                                            └─────────────────┘   │
│           │                                                      │           │
└───────────┼──────────────────────────────────────────────────────┼───────────┘
            │ MS-RDPESC Virtual Channel                            │
            ▼                                                      ▼
  ┌────────────────────────────────────────────────────────────────────────┐
  │                      Azure Virtual Desktop Host                        │
  │                  (Remote Windows Desktop Session)                      │
  │   - Full CAC Passthrough to Windows Apps (Edge, Outlook, Teams)        │
  └────────────────────────────────────────────────────────────────────────┘
```

1. **Sovereign Cloud Selection & Web Authentication**:
   - The user selects their Azure environment (DoD, GCC High, or Commercial) from the header dropdown.
   - AVD4Linux loads the designated entry point in the embedded WebKitGTK 6.0 view.
   - When Microsoft Entra ID initiates mutual TLS (`*.certauth.login.microsoftonline.us`), AVD4Linux queries the hardware token via PKCS#11, prompts the user for their CAC PIN in a native Libadwaita modal dialog, and passes the credential directly via the **Native C Extension Bridge** (`_pin_bridge`). The PIN is never allocated on the Python garbage-collected heap and is cryptographically wiped from C stack memory immediately after delivery.
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
   - FreeRDP 3 establishes the session to the remote desktop with hardware acceleration, fullscreen mode, and floatbar (`+fonts /gfx /rfx /network:auto /f /floatbar`).
   - The smart card channel (`/smartcard /smartcard-logon`) connects the local PC/SC reader directly into the remote Windows session via the standard Microsoft MS-RDPESC protocol.

---

## Range of Capabilities

- **Multi-Cloud Support**:
  - 🇺🇸 **Azure US DoD**: `rdweb.wvd.azure.us` with `login.microsoftonline.us`, DoD host pools, and `@mail.mil` authentication.
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
- **Optional Microphone & Webcam Pass-Through**:
  - Two header bar toggles let you opt in to sharing local capture devices with the remote desktop.
  - 🎤 **Microphone** uses the standard MS-RDPEAI (`audin`) audio input channel.
  - 📷 **Webcam** uses the MS-RDPECAM (`rdpecam`) video capture channel.
  - **Privacy by default**: both devices are **off** until you enable them, and choices persist in `~/.config/avd4linux/settings.json` (written with `0600` permissions).
  - **A host pool cannot opt you in**: any `audiocapturemode` or `camerastoredirect` directives supplied by the server are stripped and replaced with your local toggle state.
  - Changes apply to the **next** session; a running FreeRDP session is not reconfigured.
  - **Webcam availability** depends on how FreeRDP was compiled — see below.
- **Audit-Proof CAC PIN Security (Zero Python Heap Exposure)**:
  - High-compliance environments (DoD, NIST, DISA STIG) require that plaintext secrets not persist in garbage-collected application runtimes.
  - A custom C Extension Bridge (`_pin_bridge`) intercepts PIN submission directly from the GTK widget and transfers it to WebKitGTK in C memory.
  - The plaintext PIN is never instantiated as an immutable Python `str` or heap object, bypassing Python's memory allocator and garbage collector completely.
  - The temporary C stack buffer is cryptographically zeroed via `secure_cleanse()` using `OPENSSL_cleanse` (when available), `explicit_bzero`, and a volatile memory wipe loop to guarantee the compiler optimizer cannot strip the erasure.
- **Hardware-Resilient Smart Card Subsystem**:
  - Non-intrusive card polling via `SCardGetStatusChange` queries card presence in 0 ms without establishing exclusive card locks or issuing `SCardConnect`/`SCardDisconnect` calls that could interrupt active cryptographic operations.
  - Auto-configured with universal ISO 7816-4 APDU chunking (`max_send_size = 255`, `max_recv_size = 256`) to ensure stability across all USB CCID readers (including integrated Alcor Micro AU9540 chipsets).
- **Direct `.rdp` File Launcher**:
  - Includes an **"Open .rdp"** button in the header to launch any standalone `.rdp` connection file directly into FreeRDP 3 with smart card redirection and hardware acceleration.

### Webcam / MS-RDPECAM Requirements

Microphone redirection works with any FreeRDP 3 build. Webcam redirection additionally
requires FreeRDP to have been compiled **with** the `rdpecam` client channel. On Linux that
requires `libv4l` plus `CHANNEL_RDPECAM_CLIENT=ON`.

#### Install location

The custom build belongs at **`/opt/freerdp3-cam`**, which is the first location
`find_freerdp3()` searches. AVD4Linux looks for it in this order:

1. `/opt/freerdp3-cam/bin/xfreerdp3` — the custom build, **verified** to have MS-RDPECAM
2. `/app/bin/xfreerdp3` — the same build inside the Flatpak, where the custom prefix
   does not exist
3. `/usr/local/bin/xfreerdp3`, `/usr/bin/xfreerdp3`, then `PATH`

Do not install the custom build into `/opt/freerdp3`. The two prefixes are not
interchangeable: a CMake `CMAKE_INSTALL_PREFIX` produces a flat `bin/` + `lib/` tree,
whereas a packaged or staged install of the same version is `usr/bin` +
`usr/lib/x86_64-linux-gnu`. Sharing a prefix would leave two competing `xfreerdp3`
binaries with different library layouts and no way for a reader to tell which one the
application is meant to launch. The `-cam` suffix also records the one capability that
distinguishes this build from a stock one.

The capability check in step 1 is deliberate: a binary's path does not prove it can
redirect a webcam, because a build without `RUNPATH` silently loads the distro's
`libfreerdp-client3` and loses the channel. AVD4Linux reads MS-RDPECAM support out of the
shared object the executable actually resolves via `ldd`, and only then commits to that
binary. If a custom build exists but lacks the channel, it is still used (so sessions work),
and the missing capability is reported at startup.

#### Build

```bash
sudo apt install build-essential cmake ninja-build pkg-config \
  libssl-dev zlib1g-dev libx11-dev libxext-dev libxinerama-dev libxcursor-dev \
  libxfixes-dev libxrandr-dev libxrender-dev libpulse-dev libpcsclite-dev \
  libcairo2-dev libjansson-dev libv4l-dev \
  libavcodec-dev libavutil-dev libswscale-dev libopenh264-dev

cmake -B build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=/opt/freerdp3-cam \
  -DCMAKE_INSTALL_LIBDIR=lib \
  -DCMAKE_INSTALL_RPATH='$ORIGIN/../lib' \
  -DCMAKE_BUILD_WITH_INSTALL_RPATH=ON \
  -DWITH_CHANNELS=ON -DCHANNEL_RDPECAM_CLIENT=ON \
  -DWITH_PULSE=ON -DWITH_X11=ON -DWITH_SMARTCARD=ON -DWITH_PCSC=ON -DWITH_CAIRO=ON \
  -DWITH_AAD=ON -DWITH_SERVER=OFF -DWITH_WAYLAND=OFF \
  -DWITH_KRB5=OFF -DWITH_CUPS=OFF -DWITH_FUSE=OFF \
  -DWITH_FFMPEG=ON -DWITH_VIDEO_FFMPEG=ON -DWITH_DSP_FFMPEG=ON \
  -DWITH_SWSCALE=ON -DWITH_SWSCALE_LOADING=OFF \
  -DWITH_OPENH264=ON
ninja -C build && ninja -C build install
ln -sf xfreerdp /opt/freerdp3-cam/bin/xfreerdp3
```

Notes on those options, each of which was found the hard way:

- **`WITH_SWSCALE_LOADING=OFF` is required.** The MJPEG decoder is guarded by
  `#if defined(WITH_VIDEO_FFMPEG) && !defined(WITH_SWSCALE_LOADING)`. With runtime loading
  enabled, FreeRDP silently drops MJPEG decode even though ffmpeg is linked in.
- **`WITH_OPENH264=ON` is required** whenever the camera's native format differs from the
  format negotiated on the wire, which is the normal case for a UVC webcam (it captures
  MJPG, the session negotiates H264). Without an H264 encoder the stream cannot start.
- **`RUNPATH` must be set.** A build without it silently loads the distro's
  `libfreerdp-client3`, which lacks `rdpecam`, and the camera then appears unavailable.
- `WITH_KRB5=OFF` / `WITH_CUPS=OFF` / `WITH_FUSE=OFF` merely drop unused features. Printing
  is in fact explicitly blocked by AVD4Linux, so CUPS is redundant.

#### Required patch: `media_type_valid()`

FreeRDP 3.32.0 has a bug in the rdpecam client that prevents the stream from ever starting,
regardless of build options. The camera is enumerated and appears in Windows, but the
session reports *"Camera preview failed to start"*.

`media_type_valid()` (in `channels/rdpecam/client/camera_device_main.c`) rebuilds the list of
media types in order to validate the peer's request, but rebuilds it with values that differ
from the ones actually advertised:

| field | advertised to the peer | used during validation |
| --- | --- | --- |
| `Format` | `outputFormat` (e.g. H264) | `inputFormat` (e.g. MJPG) |
| `Flags` | `DecodingRequired` | left at 0 — the HAL never sets it |

Because the comparison is a `memcmp` over the whole struct, it can never succeed. Apply the
patch in this repository before building:

```bash
cd freerdp-3.32.0
patch -p1 < /path/to/avd4linux/packaging/freerdp-patches/rdpecam-media-type-valid.patch
```

The Flatpak manifest (`packaging/flatpak/org.avd4linux.AVD4Linux.yaml`) builds FreeRDP
3.32.0 from source, applies this same patch, and enables `WITH_OPENH264`, `WITH_V4L`, and
`CHANNEL_RDPECAM_CLIENT`. The GNOME 47 SDK already provides the whole MS-RDPECAM dependency
set — libv4l2 with `linux/videodev2.h`, OpenH264 with `wels/codec_api.h`, and
ffmpeg/libswscale — so none of those are built from source. The manifest therefore also
enables `WITH_FFMPEG` and `WITH_SWSCALE`, which is safe here; the ffmpeg encoder path itself
is restricted to hardware devices (VAAPI, VDPAU, Vulkan) and is not what a webcam uses.

Three dependencies the SDK lacks *are* built from source:

- **PC/SC Lite** and **OpenSC**, for smart card redirection. The host `pcscd` daemon is
  reached over its socket, so the Flatpak needs `--filesystem=/run/pcscd`.
- **json-c**, because `WITH_AAD=ON` (Entra ID / Azure AD sign-in) hard-fails in CMake
  unless `WITH_WINPR_JSON` is on, which needs one of json-c, cJSON or jansson.
- **libusb-1.0**. `channels/rdpecam/client/v4l/CMakeLists.txt` references
  `LIBUSB_1_INCLUDE_DIR` unconditionally, and the SDK ships libusb without headers, so
  without it the CMake generate step aborts with `LIBUSB_1_INCLUDE_DIR-NOTFOUND`.

If your local `xfreerdp3` lacks the channel, AVD4Linux detects it at startup, keeps the
webcam toggle disabled and tells you why instead of silently failing at connect time.
Non-Flatpak installs also need read access to `/dev/video*` (the shipped AppArmor profile
does not restrict device nodes).

#### Host device detection

On startup, AVD4Linux logs the availability of each redirectable device class so it is clear
whether a missing device is a host problem, a FreeRDP build problem, or simply a toggle that
is off:

| Device | Detection method |
| --- | --- |
| Webcam | presence of `/dev/video*` nodes, plus an MS-RDPECAM check on the selected build |
| Microphone | ALSA capture streams (`/proc/asound/cardN/pcmNc`) |
| Smart Card | PC/SC reader enumeration via `SmartCardMonitor`, logged once when no reader is found |

Typical output when everything is present and enabled:

```
INFO: Using custom FreeRDP build with MS-RDPECAM support: /opt/freerdp3-cam/bin/xfreerdp3
INFO: Webcam detected and will be redirected to the next session.
INFO: Microphone detected and will be redirected to the next session.
```

and when a device class is missing:

```
INFO: No webcam detected on this host (no /dev/video* nodes). Webcam redirection will be unavailable.
INFO: No smart card reader detected on this host (PC/SC daemon (pcscd) inactive). Smart Card redirection (MS-RDPESC) will be unavailable.
```

To diagnose redirection problems, run with `--verbose` so FreeRDP's own output is logged,
optionally filtered to one channel:

```bash
WLOG_LEVEL=DEBUG WLOG_FILTER="com.freerdp.channels.rdpecam:TRACE" \
  avd4linux --enable-webcam --verbose 2>&1 | tee /tmp/rdpecam.log
```

> **Note:** AVD host pools must additionally permit audio/video input redirection for the
> camera and microphone to appear inside the remote session.

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

### 3. Ubuntu 24.04 Unprivileged User Namespaces (AppArmor & WebKit Sandbox)
Ubuntu 24.04 LTS restricts unprivileged user namespaces by default (`kernel.apparmor_restrict_unprivileged_userns = 1`), which prevents WebKitGTK's Bubblewrap sandbox from setting up its UID map (`bwrap: setting up uid map: Permission denied`).

**This does not apply to the Flatpak build.** A Flatpak is already confined by an outer
Bubblewrap sandbox, the runtime ships no `bwrap` binary, and the manifest passes
`WEBKIT_DISABLE_SANDBOX_THIS_IS_DANGEROUS=1` to work around it. `check_bwrap_sandbox()`
detects a running Flatpak and treats the probe as satisfied rather than aborting, so no
host configuration is needed there. The steps below are for native (non-Flatpak) installs
only.

You can resolve this at the OS level using either of the following methods:

#### Option A: Dedicated AppArmor Profile (Recommended — Secures Host)
Install the included AVD4Linux AppArmor profile so that **only** AVD4Linux is granted unprivileged user namespace permissions, keeping the rest of your system fully protected:
```bash
sudo cp data/apparmor/avd4linux /etc/apparmor.d/
sudo apparmor_parser -r /etc/apparmor.d/avd4linux
```

#### Option B: System-Wide Sysctl Toggle
Alternatively, you can permit unprivileged user namespaces system-wide:
```bash
# Temporary (active until reboot)
sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0

# Permanent across reboots
echo "kernel.apparmor_restrict_unprivileged_userns = 0" | sudo tee /etc/sysctl.d/60-apparmor-userns.conf
sudo sysctl --system
```
*(For headless test containers or CI/CD environments without AppArmor, pass `--disable-webkit-sandbox` explicitly).*

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

# Override device redirection for a run (also updates the saved setting):
bin/avd4linux --enable-microphone
bin/avd4linux --disable-microphone
bin/avd4linux --enable-webcam
bin/avd4linux --disable-webcam
```

### Running the Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -t .
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

## Roadmap & Future Work

The following items are planned for upcoming releases:

- **GNOME Runtime Upgrade**: Migrate the base Flatpak runtime from `org.gnome.Platform//47` to `org.gnome.Platform//48` (and subsequent versions) to ensure continuous platform support and modern library dependencies.
- **Flathub Submission**: Submit AVD4Linux to the official Flathub public repository for one-click installation across all major Linux distributions.
- **Wayland-Native FreeRDP Client**: Explore integration with FreeRDP's native Wayland client (`wlfreerdp`) as upstream FreeRDP Wayland stabilization matures.
- **Multi-Monitor Layouts**: Provide user controls for selective multi-monitor span and full desktop bounding configurations.

---

## Limitations

- **Host Smart Card Setup**: The application relies on the host's `pcscd` service and USB CCID driver. If your reader is not detected in `pcsc_scan`, verify your USB reader hardware and CCID drivers.
- **DoD CA Trust**: If the host system trust store does not contain the DoD Root and Intermediate CAs, WebKitGTK and FreeRDP will reject the sovereign gateway TLS certificates. Follow the prerequisite instructions above to install the DoD CA certificates.
- **Physical CAC Requirement**: Certificate-Based Authentication and remote desktop smart card redirection require physical presence of the CAC/PIV card in the reader and PIN entry for cryptographic signing operations.

---

## License

This project is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) for details.

Azure Virtual Desktop and Microsoft Entra are registered trademarks of Microsoft Corporation. AVD4Linux is an independent open-source project and is not affiliated with or endorsed by Microsoft Corporation.
