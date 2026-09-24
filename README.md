# AVD Linux Client — native AVD app with Smart Card redirection

Native Linux desktop client for **Azure Virtual Desktop** (AVD) with **Smart
Card (PIV/CAC) redirection**, targeting **Azure Commercial, GCC High and DoD**.

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