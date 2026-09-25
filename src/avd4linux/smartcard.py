"""PC/SC Smart Card detector and monitor for AVD4Linux."""
from __future__ import annotations

import ctypes as C
import ctypes.util as U
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

SCARD_SCOPE_USER = 0
SCARD_SCOPE_SYSTEM = 2
SCARD_SHARE_SHARED = 2
SCARD_PROTOCOL_T0 = 1
SCARD_PROTOCOL_T1 = 2
SCARD_STATE_PRESENT = 0x00000020


@dataclass
class SmartCardStatus:
    has_reader: bool = False
    reader_name: str = ""
    has_card: bool = False
    card_name: str = ""
    status_text: str = "No reader detected"


class SmartCardMonitor:
    """Queries PC/SC for readers and smart cards."""

    def __init__(self) -> None:
        self._lib = None
        self._init_lib()

    def _init_lib(self) -> None:
        lib_name = U.find_library("pcsclite")
        if not lib_name:
            logger.warning("libpcsclite not found on system")
            return
        try:
            self._lib = C.CDLL(lib_name)
            # Use c_ulong / c_size_t for 64-bit LP64 SCARDCONTEXT and SCARDHANDLE pointers
            self._lib.SCardEstablishContext.argtypes = [
                C.c_ulong, C.c_void_p, C.c_void_p, C.POINTER(C.c_ulong)
            ]
            self._lib.SCardListReaders.argtypes = [
                C.c_ulong, C.c_void_p, C.c_void_p, C.POINTER(C.c_ulong)
            ]
            self._lib.SCardConnect.argtypes = [
                C.c_ulong, C.c_char_p, C.c_ulong, C.c_ulong,
                C.POINTER(C.c_ulong), C.POINTER(C.c_ulong)
            ]
            self._lib.SCardDisconnect.argtypes = [C.c_ulong, C.c_ulong]
            self._lib.SCardReleaseContext.argtypes = [C.c_ulong]
        except Exception as e:
            logger.error("Failed to load libpcsclite bindings: %s", e)
            self._lib = None

    def check_status(self) -> SmartCardStatus:
        """Polls current status of PC/SC reader and card."""
        if not self._lib:
            return SmartCardStatus(status_text="PC/SC library not available")

        ctx = C.c_ulong(0)
        rv = self._lib.SCardEstablishContext(SCARD_SCOPE_SYSTEM, 0, 0, C.byref(ctx))
        if rv != 0:
            return SmartCardStatus(status_text="PC/SC daemon (pcscd) inactive")

        try:
            buf = C.create_string_buffer(4096)
            sz = C.c_ulong(4096)
            rv = self._lib.SCardListReaders(ctx, None, buf, C.byref(sz))
            if rv != 0:
                return SmartCardStatus(status_text="No Smart Card readers found")

            readers = [
                r.decode(errors="replace")
                for r in buf.raw[:sz.value].rstrip(b"\x00").split(b"\x00")
                if r
            ]
            if not readers:
                return SmartCardStatus(status_text="No Smart Card readers found")

            reader = readers[0]
            # Try to connect to card
            h_card = C.c_ulong(0)
            proto = C.c_ulong(0)
            rv = self._lib.SCardConnect(
                ctx,
                reader.encode("utf-8"),
                SCARD_SHARE_SHARED,
                SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1,
                C.byref(h_card),
                C.byref(proto),
            )

            if rv == 0:
                self._lib.SCardDisconnect(h_card, 0)
                display_reader = reader
                if "AU9540" in reader:
                    display_reader = "Alcor AU9540"
                return SmartCardStatus(
                    has_reader=True,
                    reader_name=reader,
                    has_card=True,
                    card_name="DoD CAC / PIV Smart Card",
                    status_text=f"CAC Inserted ({display_reader})",
                )
            else:
                return SmartCardStatus(
                    has_reader=True,
                    reader_name=reader,
                    has_card=False,
                    status_text=f"Reader ready: Insert CAC ({reader[:20]})",
                )
        finally:
            self._lib.SCardReleaseContext(ctx)


def get_piv_certificate_uri() -> Optional[str]:
    """Finds the PKCS#11 URI for the PIV Authentication certificate."""
    import shutil
    import subprocess

    p11tool_path = shutil.which("p11tool")
    if not p11tool_path or not p11tool_path.startswith(("/usr/bin", "/bin", "/usr/local/bin")):
        logger.error("p11tool not found in secure system paths: %s", p11tool_path)
        return None

    queries = [
        [p11tool_path, "--list-all-certs", "pkcs11:model=PKCS%2315%20emulated;type=cert"],
        [p11tool_path, "--list-all-certs", "pkcs11:type=cert"],
    ]
    for cmd in queries:
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            current_url = None
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("URL:"):
                    current_url = line.split("URL:", 1)[1].strip()
                elif "Certificate for PIV Authentication" in line or "ID: 01" in line:
                    if current_url:
                        return current_url
            if current_url:
                return current_url
        except Exception as e:
            logger.error("Error finding PIV certificate URI: %s", e)
    return None


def get_piv_private_key_uri() -> Optional[str]:
    """Derives the PKCS#11 private key URI matching the PIV Authentication cert."""
    import re
    cert_uri = get_piv_certificate_uri()
    if not cert_uri:
        return None
    return re.sub(r";object=[^;]+", "", cert_uri).replace("type=cert", "type=private")


def get_piv_tls_certificate():
    """Loads the PIV certificate with private key URI as a Gio.TlsCertificate."""
    import gi
    from gi.repository import Gio
    cert_uri = get_piv_certificate_uri()
    if not cert_uri:
        return None
    key_uri = get_piv_private_key_uri()
    try:
        return Gio.TlsCertificate.new_from_pkcs11_uris(cert_uri, key_uri)
    except Exception as e:
        logger.error("Failed to load Gio.TlsCertificate from %s: %s", cert_uri, e)
        return None
