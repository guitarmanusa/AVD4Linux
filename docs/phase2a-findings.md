# Phase 2a — Entra CBA (CertBaseAuth) RPC bridge: status

## Conclusion: PROVEN (Phase 1 + 2a probes)

The two PKCS#11 tokens a sandboxed WebKitGTK/FreeRDP needs for **Entra
certificate-based authentication (CBA)** against AVD DoD/GCC-H are both
exported by ONE `p11-kit server` RPC socket and are both enumerable through
`p11-kit-client.so` — the exact module GnuTLS/WebKitGTK links:

| Token | Carries | Needed by CBA for |
|---|---|---|
| `FRANCIS.KYLE.JOHN.1291224420` (opensc-pcsc, AU9540 reader) | PIV-Auth certificate + private key | client cert at mTLS with `certauth.login.microsoftonline.us` |
| `System Trust` (p11-kit-trust) | DoD CA-xx / DoD Root CA 6 chain + CRLs | verify the AVD/Entra server identity (trust anchor) |

Probe scripts (all in `tools/`):
- `phase1_cli_baseline.py` — FreeRDP 3 CLI option baseline for the three
  sovereign clouds (commercial / usgov-GCC-H / usgov-dod). PASS.
- `smartcard_channel_probe.c` — WinPR/PKCS#11 smartcard channel probe (lists
  the DoD PIV token exactly as the FreeRDP client sees it). PASS.
- `phase2_cba_rpc_check.sh` + `phase2a_cba_atomic.py` — p11-kit RPC bridge:
  start server, point `p11-kit-client.so` at its socket, enumerate both the
  PIV token and DoD System Trust. PASS.

## The one gotcha that decides Phase 2b/4 architecture

`p11-kit server` is a daemon: it's designed to stay alive (Flatpak/WebKitGTK
side reconnects to `$XDG_RUNTIME_DIR/p11-kit/pkcs11` via the `systemd --user`
unit we ship in Phase 4). Between *distinct* tool/shell calls here, the server
is reaped with its controlling session, so a client launched in a separate
tool call finds no socket. That is NOT a product bug — it's exactly why the
final packaging must keep the server alive (systemd `--user` unit +
`After=pcscd`), which is specified in Phase 4 and referenced by
`tools/systemd-user/p11kit-bridge.service`.

## Not yet done (needs a live AVD workspace)
- End-to-end Entra `certauth` mTLS handshake against a real AVD tenant
  requires the user's AVD Workspace/tenant URL + CAC in the reader — we do
  not generate live cloud credentials here.

Next block: Phase 2b = DoD CA store detection/install; Phase 2c = Entra
feed discovery (`rdweb.wvd.microsoft.com|wvd.azure.us/api/arm/feeddiscovery`).
