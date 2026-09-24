#!/usr/bin/env bash
# Phase 2d — LIVE DoD AVD CBA session (the real one, on your screen).
#
# Uses ONLY flags that Phase 1 verified parse + the live p11-kit bridge that
# is ALREADY exporting FRANCIS.KYLE.JOHN (PIV-Auth) + DoD System Trust over
# the RPC socket WebKitGTK consumes. The one human step left is the CAC PIN,
# which YOU type into the FreeRDP3 smartcard-logon prompt on your display.
#
set -u
XFR=/opt/freerdp3/usr/bin/xfreerdp3
GATEWAY_HOST=rdweb.wvd.azure.us          # DoD sovereign AVD (verified live: 20.159.80.179)
FEED_HOST=rdweb.wvd.azure.us

# --- Entra DoD CBA / government community: the exact / gateway + sec set that
# --- Phase 1 validated. /gateway:type:arm + /gateway:cloud:usgov is the KEY
# --- pair that tells FreeRDP to run the sovereign ARM feeddiscovery + then
# --- present the PIV-Auth cert to Entra certauth (CBA PIN prompt).
ARGS=(
  /v:"${GATEWAY_HOST}"
  /gateway:type:arm
  /gateway:cloud:usgov
  /gateway:host:"${GATEWAY_HOST}"
  /gateway:cloud:usgov
  /sec:aad
  /smartcard
  /smartcard-logon
  /sec:nla
  /cert:ignore
  /kbd:us
  +fonts
  /gfx
  /rfx
  /network:auto
  /scale:auto
)

echo "=== launching DoD CBA session on ${DISPLAY:-:0} ==="
echo "  (your CAC is seated; the PIN prompt is FreeRDP3's — that's yours)"
echo
"$XFR" "${ARGS[@]}" &>/tmp/AVD_sess_$$.log &
echo "  xfreerdp3 launcher pid: $!"
sleep 4
echo "--- live session log (first ~10 lines) ---"
head -10 /tmp/AVD_sess_$$.log
echo
echo ">>> LOOK AT YOUR SCREEN NOW: if a PIN prompt appeared, enter your CAC PIN."
echo ">>> If you instead see a black/blank window, tell me and I'll adjust the"
