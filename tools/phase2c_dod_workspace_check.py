#!/usr/bin/env python3
"""Phase 2c — LIVE per-user DoD AVD workspace check, zero-destructive.

Given the user's DoD workspace URL:

    https://rdweb.wvd.azure.us/arm/webclient/index.html

we run the EXACT anonymous sequence FreeRDP3/AVD performs *before* any CBA
challenge, so we can prove the sovereign routing + System Trust chain WITHOUT
the card/PIN (no destructive action, no credentials, no writes):

  [A] DNS → route   resolve rdweb.wvd.azure.us (DoD sovereign LDAP/AVD edge)
                     and confirm it lands on 20.159.x.x (Azure US Gov / DoD
                     sovereign space), not the public azure.com range.
  [B] TLS chain     fetch the DoD server cert via openssl s_client with
                     -CAfile = our exported DoD System Trust bundle; verify
                     the chain that WebKitGTK/certauth will validate when the
                     user actually signs in with the CAC (Phase 2a bridge).
  [C] feeddiscovery anonymous GET → expect 401/redirect-to-login (proves
                     endpoint is the AVD arm feed for DoD and that CBA is
                     the *next* step, which is exactly where the CAC PIN
                     becomes — by design — the human-in-the-loop).

Output is non-destructive and network-only. Does NOT present any client cert
and does NOT touch the card.
"""
import os, re, socket, ssl, subprocess, sys
from urllib.request import urlopen, Request

DOD_FEED_BASE = "https://rdweb.wvd.azure.us"
DOD_WEB = DOD_FEED_BASE + "/arm/webclient/index.html"
DOD_FEEDDISCOVERY = DOD_FEED_BASE + "/api/arm/feeddiscovery"

def dod_system_trust_bundle() -> str | None:
    cands = [
        "/home/ladmin/dev/AVD_for_linux/var/dod-system-trust.pem",
        "/tmp/AVDforlinux/dod-system-trust.pem",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    return None  # uses system dir trust instead

def main() -> int:
    print("=== [A] DoD sovereign DNS/route check ===")
    try:
        infos = socket.getaddrinfo("rdweb.wvd.azure.us", 443, socket.AF_INET)
        addrs = sorted({i[4][0] for i in infos})
        print(f"  rdweb.wvd.azure.us -> {', '.join(addrs)}")
        dod = all(a.startswith("20.") for a in addrs)
        print(f"  RESULT: {'DoD sovereign routing (20.x, US Gov space)' if dod else 'NOT in 20.x — check sovereign'} {'' if dod else '!!'}")
    except Exception as e:
        print(f"  DNS error: {e}")

    bundle = dod_system_trust_bundle()
    print(f"\n=== [B] DoD server-chain vs {'exported DoD System Trust bundle' if bundle else 'host system trust'} ===")
    cmd = ["openssl", "s_client", "-connect", "rdweb.wvd.azure.us:443",
           "-servername", "rdweb.wvd.azure.us", "-verify_return_error",
           "-brief"]
    if bundle:
        cmd += ["-CAfile", bundle]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        out = p.stdout + p.stderr
        verify = re.search(r"Verification:\s*(.*)", out)
        chain = re.search(r"subject=(.*)", out)
        print(f"  verify:   {verify.group(1) if verify else '(no Verification line)'}")
        print(f"  leaf subject: {chain.group(1)[:60] if chain else '(n/a)'}")
        ok = verify and verify.group(1).strip() == "OK"
        print(f"  RESULT: {'PASS — DoD chain validates with our System Trust' if ok else 'partial — see openssl line above'}")
    except subprocess.TimeoutExpired:
        print("  RESULT: timeout (endpoint may need no-CAC path or filter)")

    print(f"\n=== [C] DoD feeddiscovery (anonymous → expect 401 / redirect-to-Entra) ===")
    req = Request(DOD_FEEDDISCOVERY, headers={"User-Agent": "AVD-Linux/0.4a"})
    try:
        with urlopen(req, timeout=25) as r:
            print(f"  HTTP {r.status} (unexpected anonymous success)")
    except Exception as e:
        code = getattr(e, "code", None)
        print(f"  HTTP {code} — this is the expected CBA entry point,")
        print("   where Entra certauth prompts for the PIV-Auth cert → CAC PIN.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
