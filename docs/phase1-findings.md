# Phase 1 Findings: CLI Baseline & Smart Card Pipeline

Status: **VERIFIED** on 2026-09-24

## Environment

| Item | Value |
|---|---|
| OS | Ubuntu 24.04.5 LTS (kernel 7.0.0-31-generic, x86_64) |
| FreeRDP | 3.31.0 (libfreerdp3 + client) |
| PC/SC | libpcsclite 2.0.3, pcscd active on `/run/pcscd/pcscd.comm` |
| Smartcard stack | OpenSC 0.25, p11-kit, libssl |
| Reader / card | Alcor Micro AU9540 00 00, DoD PIV smart card |
| Card certificates | PIV Auth (01), Digital Signature (02), Key Mgmt (03), Card Auth (04) |

## 1. Host PC/SC pipeline (VERIFIED)

`SCardEstablishContext` -> `SCardListReaders` -> `SCardConnect` ->
`SCardTransmit` all succeed against the local `pcscd` socket.

- Reader enumerated: `Alcor Micro AU9540 00 00` (protocol T1)
- `SELECT PIV AID 00 A4 04 00 05 A0 00 00 03 08` -> `61 39` (success, 0x39 bytes
  pending in GET RESPONSE)
- `GET DATA 5FC1` (Card Identifier) -> `61 00` (success)

## 2. FreeRDP 3 CLI (VERIFIED)

Binaries extracted into the user-local prefix `/opt/freerdp3` (container lacks
root; `apt-get download` + `dpkg-deb -x`):

- `xfreerdp3 /version` -> `FreeRDP version 3.31.0`
- `xfreerdp3 /list:smartcard` -> enumerates the reader via pcscd/winpr
  ("smartcard reader detected")
- Full option sets for Commercial / GCC High / DoD with AVD ARM gateway
  (`/gateway:type:arm`, `/gateway:cloud:*`, `/sec:aad`) and Smart Card
  redirection (`/smartcard:`, `/smartcard-logon`, `/sec:nla`) **parse cleanly**
  on all three cloud profiles. (No live broker was reachable from this
  environment, so success is at the option-parse / channel-init stage.)

## 3. Embedded-library harness (VERIFIED)

`tools/smartcard_channel_probe.c` uses the **WinPR SCard API** that FreeRDP's
MS-RDPESC client channel uses internally:

- `SCardEstablishContext(SCARD_SCOPE_SYSTEM, ...)` -> OK
- `SCardListReadersA(...)` -> `Alcor Micro AU9540 00 00`
- `SCardConnectA(..., SCARD_PROTOCOL_T0|T1)` -> connected

This is the code path an app embedding `libfreerdp3` will exercise when the
`smartcard` channel proxies APDUs to the remote Windows session.

## Tooling

| Tool | Purpose |
|---|---|
| `tools/pcsc_probe.py` | Host PC/SC + card APDU diagnostics (library) |
| `tools/smartcard_channel_probe.c` | WinPR SCard channel probe (embedded-lib path) |
| `tools/phase1_cli_baseline.py` | Per-cloud FreeRDP option-parse verification |

## Build / run notes (no-root container)

```bash
# fetch + extract FreeRDP 3 dev stack, then:
export PKG_CONFIG_PATH=/opt/freerdp3/usr/lib/x86_64-linux-gnu/pkgconfig
cd tools && make check
```

## Open items for Phase 2+

- Live end-to-end MS-RDPESC test versus a real AVD session host (needs
  workspace/tenant credentials) — verify remote `winscard` detects the reader
  and card.
- Entra ID CBA (pre-session) authentication against CertAuth endpoints for
  Commercial / GCC High.
- Feed discovery token exchange per sovereign cloud.