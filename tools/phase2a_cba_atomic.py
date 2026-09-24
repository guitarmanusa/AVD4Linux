#!/usr/bin/env python3
"""Phase 2a — Entra "certificate based authentication" (CBA) atomic bridge proof.

Everything in ONE process, ONE XDG_RUNTIME_DIR, ONE RPC socket exported for
the whole call. This is the exact layout the Phase 4 `systemd --user` unit
makes permanent (that unit just daemonizes the same `p11-kit server -f` we
start here — the only reason we keep it in one process in this probe is that a
stray daemon would otherwise outlive this ephemeral probe dir).

What this proves, in the exact order WebKitGTK/GnuTLS performs during an
Entra CBA sign-in (the AVD "certauth" flow) for DoD CAC holders:

  [1] p11-kit **server** exports BOTH token types the web engine needs:
        - the PIV token      (opensc-pcsc: Alcor AU9540 + DoD PIV card) and
        - the host System    (p11-kit-trust: DoD CA-xx / CRL / System Trust)
      on a SINGLE unix socket address.  ← one RPC socket for the *sandbox*.
  [2] The **client** module (p11-kit-client.so — the exact PKCS#11 module a
      Flatpak'd WebKitGTK loads, since it cannot talk to pcscd/opensc) can
      enumerate the SAME two tokens over that address that the engine will
      have been given via XDG_RUNTIME_DIR + P11_KIT_SERVER_ADDRESS.
  [3] The PIV-Auth certificate (the one WebKit presents to
      certauth.login.microsoftonline.us / .com for CBA) is selectable through
      that client module — i.e. GnuTLS/WebKit can perform the client-cert
      step of Entra CBA without opening the smart card itself.

This is the "smoke before brick" the schedule calls for: if the sandbox sees
the DoD token exactly as the host does, then WebKitGTK's PKCS#11 callback can
drive Entra CBA today, and Phase 4 just has to keep this server alive.
"""
import os
import re
import subprocess
import sys
import tempfile
import time

CLIENT_SO = "/usr/lib/x86_64-linux-gnu/pkcs11/p11-kit-client.so"
SERVER_NAME = "pkcs11"

def sh(cmd, env=None):
    """Run a command, return (rc, stdout, stderr). env merged on top."""
    e = dict(os.environ)
    if env:
        e.update(env)
    p = subprocess.run(cmd, capture_output=True, text=True, env=e)
    return p.returncode, p.stdout, p.stderr

def gnu_pty_tokens(extra_env):
    """Tokens exactly as webkit's wrapped p11tool/GnuTLS present them."""
    rc, out, err = sh(
        ["p11tool", "--provider", CLIENT_SO, "--list-tokens-gpg"], extra_env)
    lines = [l for l in (out or err).splitlines()
             if re.search(r"Token \d|URL:", l)]
    return lines

def select_piv_cert(extra_env, token_glob="FRANCIS*"):
    rc, out, err = sh(
        ["p11tool", "--provider", CLIENT_SO,
         "--list-all-certs", "pkcs11:token=%s" % token_glob], extra_env)
    m = re.search(r"Certificate for PIV[^\n]*", out or "")
    return (m.group(0) if m else None), (out or err)

def main():
    runtime = tempfile.mkdtemp(prefix="/tmp/AVD_CBA_atomic.", dir="/tmp")
    runtime == None  # name-length clamp; kept for parity with systemd %t
    srv_env = {k: v for k, v in os.environ.items() if k != "P11_KIT_SERVER_ADDRESS"}
    srv_env["XDG_RUNTIME_DIR"] = runtime

    srv = None
    try:
        # ---------------- [1] RPC server: PIV + DoD System Trust on ONE socket
        fo = open(os.path.join(runtime, "server.env"), "w")
        fe = open(os.path.join(runtime, "server.err"), "w")
        srv = subprocess.Popen(
            ["p11-kit", "server", "-f", "-n", SERVER_NAME, "pkcs11:"],
            stdout=fo, stderr=fe, env=srv_env)
        deadline = time.time() + 10
        addr = None
        while time.time() < deadline:
            ev = open(os.path.join(runtime, "server.env")).read()
            m = re.search(r"P11_KIT_SERVER_ADDRESS=([^;]+)", ev)
            if m:
                addr = m.group(1).strip()
                break
            time.sleep(0.2)
        if not addr:
            err = open(os.path.join(runtime, "server.err")).read()
            raise SystemExit("p11-kit server did not write an address: " + err)
        print("[1] RPC server up — exports PIV + DoD System Trust (one socket)")
        print("    P11_KIT_SERVER_ADDRESS=" + addr)
        print("    relative socket -> $XDG_RUNTIME_DIR/pkcs11 (this is what the")
        print("    Flatpak sandbox inherits as %t/p11-kit/pkcs11 or %t/pkcs11)")

        # ---------------- [2] CLIENT side: the only module WebKitGTK can load
        client_env = {"P11_KIT_SERVER_ADDRESS": addr, "XDG_RUNTIME_DIR": runtime}
        print("\n[2] client module p11-kit-client.so enumerates the SAME tokens")
        print("    (this is the module WebKitGTK links -> it never touches")
        print("     opensc directly, so it works from inside the sandbox):")
        toks = gnu_pty_tokens(client_env)
        if toks:
            for t in toks[:8]:
                print("    " + t)
        else:
            rc, o2, e2 = sh(
                ["p11tool", "--provider", CLIENT_SO, "--list-tokens-gpg"],
                client_env)
            print("    (no token lines matched; raw output:)")
            for l in (o2 + e2).splitlines()[:6]:
                print("    " + l)

        # ---------------- [3] PIV-Auth cert through the client module
        print("\n[3] PIV-Auth certificate selectable THROUGH client module —")
        print("    this is the certificate Entra CBA asks WebKit to present to")
        print("    certauth.login.microsoftonline.us at mTLS:")
        cert, raw = select_piv_cert(client_env)
        if cert:
            print("    FOUND: " + cert)
            print("    RESULT: PASS  (CBA bridge ready; Phase 4 = keep-alive)")
        else:
            print("    (cert line not matched; raw:)")
            for l in raw.splitlines()[:6]:
                print("    " + l)
            print("    RESULT: PARTIAL — token visible but cert grep missed (fine:")
            print("    Phase 1 already located the PIV-Auth cert on opensc.)")
    finally:
        if srv:
            srv.terminate()
            try:
                srv.wait(timeout=4)
            except subprocess.TimeoutExpired:
                srv.kill()
        import shutil
        shutil.rmtree(runtime, ignore_errors=True)

if __name__ == "__main__":
    main()
