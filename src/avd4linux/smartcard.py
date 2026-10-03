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


class _SCARD_READERSTATE(C.Structure):
    _fields_ = [
        ("szReader", C.c_char_p),
        ("pvUserData", C.c_void_p),
        ("dwCurrentState", C.c_ulong),
        ("dwEventState", C.c_ulong),
        ("cbAtr", C.c_ulong),
        ("rgbAtr", C.c_ubyte * 36),
    ]


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
            self._lib.SCardGetStatusChange.argtypes = [
                C.c_ulong, C.c_ulong, C.POINTER(_SCARD_READERSTATE), C.c_ulong
            ]
            self._lib.SCardReleaseContext.argtypes = [C.c_ulong]
        except Exception as e:
            logger.error("Failed to load libpcsclite bindings: %s", e)
            self._lib = None

    def check_status(self) -> SmartCardStatus:
        """Polls current status of PC/SC reader and card without connecting or interrupting transactions."""
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
            # Use non-intrusive SCardGetStatusChange to query card presence.
            # Never use SCardConnect/Disconnect during polling as it interrupts active
            # cryptographic transactions in OpenSC / GnuTLS and causes "PKCS #11 error in key".
            rs = _SCARD_READERSTATE()
            rs.szReader = reader.encode("utf-8")
            rs.dwCurrentState = 0
            rv = self._lib.SCardGetStatusChange(ctx, 0, C.byref(rs), 1)
            has_card = (rv == 0) and bool(rs.dwEventState & SCARD_STATE_PRESENT)

            if has_card:
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


# The PIV Authentication certificate lives on slot 9A with the object ID 0x01
# (NIST SP 800-73-4, "PIV Authentication Key / Certificate"). Note that PKCS#11
# treats `id=%01` as a *prefix* match, so it also matches unrelated objects whose
# ID merely begins with 0x01 -- for example the DER-encoded certificate IDs in the
# p11-kit system trust store. Every match below is therefore required to be an
# exact ID and to live on a hardware token.
PIV_AUTH_OBJECT_ID = "01"

# Token attributes that identify a software/system-trust PKCS#11 store rather than
# the user's CAC. Objects from these modules have no private key, so they can never
# satisfy client-certificate authentication and must never be offered to WebKit.
_SOFTWARE_TOKEN_MARKERS = (
    "model=p11-kit-trust",
    "model=p11-kit",
    "model=gnutls%20trust",
    "manufacturer=pkcs%2311%20kit",
    "token=system%20trust",
    "token=gnutls%20trust",
)

# Candidate locations of the OpenSC PKCS#11 provider. Pinning p11tool to this
# module keeps the system trust store out of the enumeration entirely.
_OPENSC_PROVIDER_PATHS = (
    "/app/lib/opensc-pkcs11.so",  # Flatpak
    "/usr/lib/opensc-pkcs11.so",
    "/usr/lib/x86_64-linux-gnu/opensc-pkcs11.so",
    "/usr/lib64/opensc-pkcs11.so",
)


def _find_opensc_provider() -> Optional[str]:
    import os

    for path in _OPENSC_PROVIDER_PATHS:
        if os.path.exists(path):
            return path
    return None


def _uri_object_id(uri: str) -> str:
    """Returns the normalised hex object ID encoded in a PKCS#11 URI, or ''."""
    import re

    match = re.search(r"(?:^|;)id=([^;]+)", uri)
    if not match:
        return ""
    return re.sub(r"[^0-9a-fA-F]", "", match.group(1)).upper()


def _uri_is_hardware_token(uri: str) -> bool:
    """Rejects URIs that point at a software/system-trust PKCS#11 store."""
    lowered = uri.lower()
    return not any(marker in lowered for marker in _SOFTWARE_TOKEN_MARKERS)


def _is_piv_labelled(record) -> bool:
    """True when an object's own metadata identifies it as PIV Authentication."""
    haystack = f"{record['label']} {record['usage']}".lower()
    return "piv" in haystack and "authentication" in haystack


def _parse_p11tool_certificates(output: str) -> list:
    """Parses `p11tool --list-all-certs` output into per-object records.

    Each record is a dict with the object's ``label``, ``id``, ``usage`` and
    ``url``. Parsing per block (instead of scanning line by line) is what keeps a
    URL from being attributed to a neighbouring object.
    """
    import re

    records = []
    current = None

    def flush():
        if current and current.get("url"):
            records.append(current)

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Certificate:") or line.startswith("Object "):
            flush()
            current = {"label": "", "id": "", "usage": "", "url": ""}
            continue
        if current is None:
            continue
        for field in ("URL", "Label", "ID", "Usage"):
            prefix = field + ":"
            if line.startswith(prefix):
                current[field.lower()] = line[len(prefix):].strip()
                break
        else:
            # Older p11tool builds print "Certificate for PIV Authentication".
            match = re.match(r"Certificate for (.+)", line)
            if match and not current["label"]:
                current["label"] = match.group(1).strip()

    flush()
    return records


def get_piv_certificate_uri() -> Optional[str]:
    """Finds the PKCS#11 URI for the PIV Authentication certificate on the CAC."""
    import shutil
    import subprocess

    p11tool_path = shutil.which("p11tool")
    if not p11tool_path or not p11tool_path.startswith(("/usr/bin", "/bin", "/usr/local/bin")):
        logger.error("p11tool not found in secure system paths: %s", p11tool_path)
        return None

    provider = _find_opensc_provider()
    if provider:
        logger.info("Enumerating PIV certificates via OpenSC provider: %s", provider)

    # Query specifically for the PIV Authentication certificate (slot 9A / ID %01)
    queries = [
        [p11tool_path, "--list-certs", "pkcs11:id=%01"],
        [p11tool_path, "--list-all-certs", "pkcs11:model=PKCS%2315%20emulated;type=cert"],
        [p11tool_path, "--list-all-certs", "pkcs11:type=cert"],
    ]

    for base in queries:
        cmd = ([base[0], f"--provider={provider}"] if provider else []) + base[1:]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        except Exception as e:
            logger.error("Error finding PIV certificate URI: %s", e)
            continue

        records = _parse_p11tool_certificates(res.stdout)
        if not records:
            continue

        candidates = [r for r in records if _uri_is_hardware_token(r["url"])]
        if len(candidates) != len(records):
            logger.info(
                "Ignoring %d certificate(s) from software/system-trust PKCS#11 modules",
                len(records) - len(candidates),
            )

        # A DoD CAC's slot 9A holds several objects that all share object ID 0x01
        # (CAC Authentication, PIV Authentication, ...). Entra ID certauth expects
        # the PIV Authentication certificate, so a PIV-labelled object wins over a
        # bare ID match, and label/usage only ever corroborate -- they never select
        # an object on their own, because the trust store reuses similar wording
        # for unrelated roots.
        exact = [r for r in candidates if _uri_object_id(r["url"]) == PIV_AUTH_OBJECT_ID]
        for record in exact:
            if _is_piv_labelled(record):
                logger.info(
                    "Found PIV Authentication certificate: label=%r id=%s url=%s",
                    record["label"], record["id"] or PIV_AUTH_OBJECT_ID, record["url"],
                )
                return record["url"]

        if exact:
            logger.info(
                "Found slot 9A certificate by exact object ID %s: label=%r url=%s",
                PIV_AUTH_OBJECT_ID, exact[0]["label"], exact[0]["url"],
            )
            return exact[0]["url"]

        # Some middlewares expose a longer ID for slot 9A. Only trust that on a
        # hardware token whose own metadata says PIV Authentication.
        for record in candidates:
            if _is_piv_labelled(record):
                logger.info(
                    "Found PIV Authentication certificate by label: label=%r url=%s",
                    record["label"], record["url"],
                )
                return record["url"]

    logger.error(
        "No PIV Authentication certificate (id=%s) found on a hardware token", PIV_AUTH_OBJECT_ID
    )
    return None


def get_piv_private_key_uri(cert_uri: Optional[str] = None) -> Optional[str]:
    """Derives the PKCS#11 private key URI specifically targeting the PIV Authentication key (slot 9A)."""
    import re
    if not cert_uri:
        cert_uri = get_piv_certificate_uri()
    if not cert_uri:
        return None

    uri = re.sub(r";object=[^;]+", "", cert_uri).replace("type=cert", "type=private")
    # Reuse the certificate's exact ID so the key lookup stays as narrow as the
    # certificate lookup. Appending a bare `id=%01` would widen it back into a
    # prefix match, which is what previously picked up the system trust store.
    object_id = _uri_object_id(uri)
    if not object_id:
        uri += ";id=%01"
    return uri


def get_piv_tls_certificate():
    """Loads the PIV certificate with private key URI as a Gio.TlsCertificate."""
    import gi
    from gi.repository import Gio

    cert_uri = get_piv_certificate_uri()
    if not cert_uri:
        return None
    key_uri = get_piv_private_key_uri(cert_uri)
    if not key_uri:
        return None

    try:
        return Gio.TlsCertificate.new_from_pkcs11_uris(cert_uri, key_uri)
    except Exception as e:
        logger.error("Failed to load Gio.TlsCertificate from %s: %s", cert_uri, e)
        return None
