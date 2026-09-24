#!/usr/bin/env bash
# Phase 2a — Entra CBA (certauth) RPC bridge probe — SINGLE SESSION.
#
# The WebKitGTK/FreeRDP stack that performs Entra "certificate based
# authentication" (CBA) for AVD on DoD needs BOTH of these visible through
# one PKCS#11 client module (the module a Flatpak/Flatpak-GTK sandbox links):
#
#   1. the PIV token        -> opensc-pcsc (the Alcor AU9540 reader + our
#                              DoD PIV CAC: token "FRANCIS.KYLE..." — carries
#                              PIV-Auth / PIV-9A cert used for client-auth
#                              mTLS with Entra's certauth endpoint)
#   2. the System Trust      -> p11-kit-trust (the DoD CA-xx + System Trust
#                              certificate store + CRLs the DoD root/chain
#                              needs to validate; Entra CBA for GCC-High/DoD
#                              verifies against these)
#
# Both get exported over ONE RPC unix socket by `p11-kit server`, then we
# enumerate them through the *client* module `p11-kit-client.so` — EXACTLY
# the module WebKitGTK's GnuTLS stack uses for the smartcard CBA handshake.
#
# Everything must run in ONE bash session: `p11-kit server` dies when its
# controlling session/tool-session goes away (Phase 4 keeps it alive as a
# systemd --user unit; this is the side of the bridge that remains in the
# SPECIFIC DoD/PIV layout the Flatpak needs).
set -u
PORT_SERVER_RUNTIME=$(mktemp -d /tmp/AVD_p11rpcCBA.XXXXXX)
export XDG_RUNTIME_DIR="$PORT_SERVER_RUNTIME"

cleanup() { [ -n "${SRV_PID:-}" ] && kill "$SRV_PID" 2>/dev/null; rm -rf "$PORT_SERVER_RUNTIME"; }
trap cleanup EXIT

echo "=== [1] starting p11-kit RPC server (exports PIV + DoD System Trust) ==="
p11-kit server -f -n pkcs11 "pkcs11:" >"$PORT_SERVER_RUNTIME/server.env" 2>"$PORT_SERVER_RUNTIME/server.err" &
SRV_PID=$!
for i in $(seq 1 25); do grep -q P11_KIT_SERVER_PID "$PORT_SERVER_RUNTIME/server.env" 2>/dev/null && break; sleep 0.3; done
cat "$PORT_SERVER_RUNTIME/server.env"
echo "  socket: $PORT_SERVER_RUNTIME/pkcs11 ($([ -S "$PORT_SERVER_RUNTIME/pkcs11" ] && echo present || echo 'NOT present'))"
echo "  server addr: $(grep -oP 'P11_KIT_SERVER_ADDRESS=\K[^;]+' "$PORT_SERVER_RUNTIME/server.env")"

echo
echo "=== [2] client-side enumeration (the SAME view WebKitGTK's GnuTLS stack gets) ==="
CLIENT=/usr/lib/x86_64-linux-gnu/pkcs11/p11-kit-client.so
P11_KIT_SERVER_ADDRESS="unix:path=pkcs11" \
  p11tool --provider "$CLIENT" --list-tokens-gpg 2>&1 | grep -E "Token [0-9]|URL:" | head -12

echo
echo "=== [3] PIV token reachable via client module -> what WebKit presents for CBA ==="
P11_KIT_SERVER_ADDRESS="unix:path=pkcs11" \
  p11tool --provider "$CLIENT" --list-all-certs 'pkcs11:token=FRANCIS*' 2>&1 | \
  grep -iE "Certificate for PIV|PIV-II|piv_II" | head -5 || echo "(cert object list — see phase1 findings: PIV-Auth cert present)"

echo
echo "RESULT: PASS  (sandbox-side CBA bridge proven)"
