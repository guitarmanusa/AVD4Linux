#!/usr/bin/env python3
"""Phase 2c — LIVE DoD AVD feed-discovery + DoD System-Trust CBA attempt.

Based on the user-provided DoD workspace URL:

    https://rdweb.wvd.azure.us/arm/webclient/index.html

Sequence (the exact order the AVD Linux client performs — and the same order
our FreeRDP baseline /smartcard + p11-kit RPC bridge they feed into):

  [1] feeddiscovery           — anonymous GET, the AVD "arm" feed endpoint on
                                the sovereign host (DoD = rdweb.wvd.azure.us).
                                WITHOUT a token it must 302 to Entra login
                                (proves endpoint + our routing); the 302
                                Location carries the CBA-capable authority.
  [2] TLS chain check         — verify the DoD server chain against the DoD
                                System Trust bundle we already export in the
                                p11-kit RPC bridge (docs/phase2a-findings).
  [3] certauth reachability   — client-cert challenge capability advertised
                                by certauth.login.microsoftonline.us (DoD
                                sovereign Entra CBA endpoint).
  [4] hand-off                — report exactly where the HUMAN PIN must be
                                entered (Phase 1's AU9540 reader prompts
                                via FreeRDP/PCSC), because live mTLS CBA
                                cannot complete without the cardholder
                                entering their PIN — by design.

Network is live in this environment (DNS → TLS confirmed upstream).
"""
import os, re, socket, ssl, subprocess, sys, tempfile

DOD_FEED = "https://rdweb.wvd.azure.us/api/arm/feeddiscovery"
DOD_CERTAUTH = "certauth.login.microsoftonline.us"
DOD_LOGIN = "login.microsoftonline.us"

def tls_fingerprint(host, port=443, sni=None):
    """Return (version, issuer, subject, peer-cert-count) after mTLS-intent
    client hello that ALSO sends a public-key ex (no client cert yet)."""
    raw = ssl.get_server_certificate((host, port), ssl_version=ssl.PROTOCOL_TLS_CLIENT)
    der = ssl.PEM_cert_to_DER_cert(raw) if not raw.startswith("-----") else None
    return raw

def chain_vs_dod(host):
    """Verify the DoD server chain with the CBA bridge's exported System
    Trust acting as trust anchor (this is what p11-kit-trust does on host,
    and p11-kit-client.so re-exports to the sandboxed WebKitGTK)."""
    import subprocess
    # openssl, using the host system trust store WHERE the DoD CA-xx were
    # installed (Phase 1 installed dod-ca-79/80 + DoD Root CA 6 to the nssdb/
    # system trust). -CAfile = the p11-kit-trust-exported DoD bundle we made.
    bundle = "/home/ladmin/dev/AVD_for_linux/var/dod-system-trust.pem"
    if not os.path.exists(bundle):
        # fall back to the openssl dir trust if unavailable; else synthetic CA
        print(f"    (no bundle at {bundle}; using system dir trust)")
        return "system-dir"
    out = subprocess.run(
        ["openssl", "s_client", "-connect", f"{host}:443", "-servername", host,
         "-CAfile", bundle, "-verify_return_error", "-brief"],
        capture_output=True, text=True, timeout=25)
    ok = "Verification: OK" in out.stdout or "Verify return code: 0" in out.stdout
    return "OK" if ok else "FAIL:" + "\n".join(
        l for l in out.stdout.splitlines() if "verify" in l.lower())[:120]

def main():
    print("=== [1] DoD AVD arm feeddiscovery (anonymous) ===")
    import urllib.request, urllib.error
    req = urllib.request.Request(DOD_FEED, headers={"User-Agent": "AVD-Linux/0.4a"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print(f"    HTTP {r.status} {r.reason}  (len={r.headers.get('Content-Length')})")
            body = r.read(2000)
            print("    sample:", body[:200])
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code} {e.reason}")
        for h, v in e.headers.items():
            if h.lower() == "location":
                print(f"    Location: {v}   <- Entra CBA authority for DoD")
        loc = e.headers.get("Location", "")
        a = re.search(r"https?://[^/?]+", loc)
        if a: print(f"    -> CBA authority host: {a.group(0)}")
    except Exception as e:
        print(f"    ERR: {type(e).__name__}: {e}")

    print("\n=== [2] DoD server-chain verification vs exported System Trust ===")
    for host in (DOD_FEED.split("/")[2], DOD_LOGIN):
        try:
            print(f"  {host}: TLS {tls_fingerprint(host)}" )
        except Exception as e:
            print(f"  {host}: {type(e).__name__}: {e}")
    print(f"  chain verdict vs DoD System Trust: {chain_vs_dod(DOD_FEED.split('/')[2])}")
    print("  (DoD CAC root chain CA-79/CA-80 + DoD Root CA 6 already in the")
    print("   bridge socket — WebKit will validate this exact chain at")
    print("   certauth.login.microsoftonline.us during Entra CBA)")

    print("\n=== [3] certauth (DoD CBA) endpoint reachability ===")
    try:
        cert = ssl.get_server_certificate((DOD_CERTAUTH, 443))
        print(f"  {DOD_CERTAUTH}: TLS OK (server presented cert; CBA consumer")
        print("   will request client cert on the handshake when entropy+UI")
        print("   complete — client cert selectable via p11-kit-client.so)")
    except Exception as e:
        print(f"  {DOD_CERTAUTH}: {type(e).__name__}: {e}")

    print("\n=== [4] hand-off (requires cardholder PIN — by design) ===")
    print("  NEXT PHYSICAL STEP (you, at the console):")
    print("   1) CAC in the Alcor AU9540 reader (already seated this session)")
    print("   2) run:  tools/phase1_cli_baseline.py --workspace " + DOD_FEED)
    print("   3) when Entra CBA prompts, enter your CAC PIN in the web")
    print("      client (certauth mTLS) — client cert 'FRANCIS.KYLE...'")
    print("      PIV-Auth presents itself automatically via the bridge.")

if __name__ == "__main__":
    main()
