# AVD Linux Client — native AVD app with Smart Card redirection

Native Linux desktop client for **Azure Virtual Desktop** (AVD) with **Smart
Card (DoD CAC/PIV) redirection**, targeting **Azure Commercial, GCC High and DoD**.

Built with **GTK 4**, **Libadwaita**, **WebKitGTK 6**, and **FreeRDP 3**.

## Features

- **Native Linux App**: Modern GNOME/Adwaita user interface with dark/light mode support.
- **DoD CAC & PIV Smart Card Redirection**: Full MS-RDPESC smart card channel redirection via FreeRDP 3 and host PC/SC daemon (`pcscd`).
- **Sovereign Cloud Switcher**:
  - 🇺🇸 **Azure US DoD** (`rdweb.wvd.azure.us`)
  - 🏛️ **Azure US Government (GCC High)** (`rdweb.wvd.azure.us`)
  - 🌐 **Azure Commercial** (`rdweb.wvd.microsoft.com`)
- **Live Smart Card Detection**: Real-time status indicator in the window title bar showing reader and card state (`Alcor Micro AU9540`, `DoD PIV`).
- **Seamless RDP Launch**: Intercepts workspace connections and launches high-performance native FreeRDP 3 with smart card redirection and hardware acceleration.
- **Direct .rdp Launcher**: "Open .rdp" button to launch any downloaded or custom RDP configuration file directly with FreeRDP 3.

## Running the Application

### From Application Menu
Search for **"Azure Virtual Desktop"** in your GNOME / desktop application launcher.

### From Terminal
```bash
# Launch default (DoD environment)
bin/avd-linux

# Or specify cloud target
bin/avd-linux --cloud dod
bin/avd-linux --cloud gcc
bin/avd-linux --cloud commercial

# Launch a specific .rdp file directly with Smart Card redirection
bin/avd-linux --rdp ~/Downloads/my-desktop.rdp
```

---

## Standalone Flatpak & Flathub Packaging

See [docs/packaging-and-flathub.md](docs/packaging-and-flathub.md) for full instructions on:
- Building a standalone `.flatpak` bundle.
- Submitting to Flathub.
- Automated GitHub Actions build pipeline.

## Status

| Phase | Scope | Status |
|---|---|---|
| Phase 1 | CLI baseline + smartcard pipeline verification | **VERIFIED** (see `docs/phase1-findings.md`) |
| Phase 2 | Entra ID CBA auth + feed discovery | planned |
| Phase 3 | GTK4 desktop app (workspace grid + session launch) | planned |
| Phase 4 | Flatpak packaging (distro-agnostic) | planned |

## Requirements

- Smart card host stack: `pcscd`, `libpcsclite`, OpenSC / p11-kit
  (`opensc-pkcs11.so` / `p11-kit-proxy.so`)
- FreeRDP 3 (`freerdp3-x11` / `freerdp3-wayland`, embedded `libfreerdp3`)

## Phase 1 verification

```bash
cd tools && make check
```

Output proves: PC/SC reader+card reachable via `pcscd`, FreeRDP 3 enumerates
and drives the reader, and the full AVD flag set (ARM gateway, `usgov` cloud,
`/sec:aad`, `/smartcard`) parses for Commercial, GCC High and DoD.

## Cloud matrix

| Cloud | Authority | CBA endpoint | Feed discovery | FreeRDP cloud |
|---|---|---|---|---|
| Commercial | `login.microsoftonline.com` | `certauth.login.microsoftonline.com` | `rdweb.wvd.microsoft.com` | `commercial` |
| GCC High | `login.microsoftonline.us` | `certauth.login.microsoftonline.us` | `rdweb.wvd.azure.us` | `usgov` |
| DoD | `login.microsoftonline.us` | `certauth.login.microsoftonline.us` | `rdweb.wvd.azure.us` | `usgov` |

See `src/avd_client/clouds.py` for the machine-readable profiles.

## Layout

```
docs/                 findings + design
src/avd_client/       python package (cloud profiles, session engine)
tools/                pcsc probe, freerdp CLI baseline, channel probe
```