#!/usr/bin/env python3
"""PC/SC smartcard pipeline diagnostics for the AVD Linux native client.

Verifies that the local smartcard stack (pcscd -> libpcsclite -> reader -> card)
is operational, which is the host-side prerequisite for FreeRDP's MS-RDPESC
(Smart Card) redirection channel.

Verified against: Ubuntu 24.04, libpcsclite 2.0.3, PIV smartcard on
Alcor Micro AU9540 via the /run/pcscd/pcscd.comm socket.
"""
import argparse
import ctypes as C
import ctypes.util as U
import sys

SCARD_SCOPE_USER = 0
SCARD_SCOPE_SYSTEM = 2
SCARD_SHARE_SHARED = 2
SCARD_PROTOCOL_T0 = 1
SCARD_PROTOCOL_T1 = 2
SCARD_UNPOWER_CARD = 2

SCARD_ERRORS = {
    0x80100001: "SCARD_F_INTERNAL_ERROR",
    0x80100002: "SCARD_E_CANCELLED",
    0x80100003: "SCARD_E_INVALID_HANDLE",
    0x80100004: "SCARD_E_INVALID_PARAMETER",
    0x80100005: "SCARD_E_INVALID_TARGET",
    0x80100006: "SCARD_E_NO_MEMORY",
    0x80100008: "SCARD_F_COMM_ERROR",
    0x80100009: "SCARD_E_UNKNOWN_READER",
    0x8010000A: "SCARD_E_TIMEOUT",
    0x8010000B: "SCARD_E_SHARING_VIOLATION",
    0x8010000C: "SCARD_E_NO_SMARTCARD",
    0x8010000D: "SCARD_E_UNKNOWN_CARD",
    0x8010000E: "SCARD_E_CANT_DISPOSE",
    0x8010000F: "SCARD_E_PROTO_MISMATCH",
    0x80100010: "SCARD_E_NOT_READY",
    0x80100011: "SCARD_E_INVALID_VALUE",
    0x80100012: "SCARD_E_APPLICATION_NOT_FOUND",
    0x80100013: "SCARD_E_INVALID_PASSWORD",
    0x80100016: "SCARD_E_INSUFFICIENT_BUFFER",
    0x8010001A: "SCARD_E_NO_SERVICE",
    0x8010001B: "SCARD_E_SERVICE_STOPPED",
    0x8010001C: "SCARD_E_UNEXPECTED",
    0x8010001D: "SCARD_E_ICC_INSTALLATION",
    0x8010001E: "SCARD_E_ICC_CREATEORDER",
    0x8010002E: "SCARD_E_NO_READERS_AVAILABLE",
    0x8010002D: "SCARD_E_READER_UNAVAILABLE",
}


class SCARD_IO_REQUEST(C.Structure):
    _fields_ = [("dwProtocol", C.c_uint32), ("cbPciLength", C.c_uint32)]


def load_pcsc():
    name = U.find_library("pcsclite")
    if not name:
        sys.exit("ERROR: libpcsclite not found. Install pcsc-lite and pcscd.")
    return C.CDLL(name)


class PCSCProbe:
    def __init__(self, lib):
        self.sc = lib
        self.sc.SCardEstablishContext.argtypes = [
            C.c_uint32, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32)
        ]
        self.sc.SCardListReaders.argtypes = [
            C.c_uint32, C.c_void_p, C.c_void_p, C.POINTER(C.c_uint32)
        ]
        self.sc.SCardConnect.argtypes = [
            C.c_uint32, C.c_char_p, C.c_uint32, C.c_uint32,
            C.POINTER(C.c_uint32), C.POINTER(C.c_uint32)
        ]
        self.sc.SCardTransmit.argtypes = [
            C.c_uint32, C.POINTER(SCARD_IO_REQUEST), C.c_void_p, C.c_uint32,
            C.POINTER(SCARD_IO_REQUEST), C.c_void_p, C.POINTER(C.c_uint32)
        ]
        self.sc.SCardDisconnect.argtypes = [C.c_uint32, C.c_uint32]
        self.sc.SCardReleaseContext.argtypes = [C.c_uint32]
        self.ctx = C.c_uint32(0)

    def err(self, rv):
        return SCARD_ERRORS.get(rv & 0xFFFFFFFF, hex(rv & 0xFFFFFFFF))

    def context(self):
        rv = self.sc.SCardEstablishContext(SCARD_SCOPE_SYSTEM, 0, 0,
                                           C.byref(self.ctx))
        if rv != 0:
            raise RuntimeError(f"SCardEstablishContext: {self.err(rv)}")
        return self.ctx.value

    def readers(self):
        buf = C.create_string_buffer(4096)
        size = C.c_uint32(4096)
        rv = self.sc.SCardListReaders(self.ctx, None, buf, C.byref(size))
        if rv != 0:
            raise RuntimeError(f"SCardListReaders: {self.err(rv)}")
        return [r.decode() for r in
                buf.raw[:size.value].rstrip(b"\x00").split(b"\x00") if r]

    def connect(self, reader):
        h = C.c_uint32(0)
        proto = C.c_uint32(0)
        rv = self.sc.SCardConnect(self.ctx, reader.encode(), SCARD_SHARE_SHARED,
                                  SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1,
                                  C.byref(h), C.byref(proto))
        return rv, h, proto.value

    def transmit(self, h, proto, apdu):
        io = SCARD_IO_REQUEST(proto, 8)
        rio = SCARD_IO_REQUEST(proto, 8)
        recv = C.create_string_buffer(260)
        rlen = C.c_uint32(260)
        rv = self.sc.SCardTransmit(h, C.byref(io), C.c_char_p(apdu), len(apdu),
                                   C.byref(rio), recv, C.byref(rlen))
        return rv, recv.raw[:rlen.value]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apdu", metavar="HEX", default=None,
                   help="Send a raw APDU (hex) to the card after selecting it")
    p.add_argument("--select-piv", action="store_true",
                   help="Issue a PIV AID SELECT (00 A4 04 00 05 A0 00 00 03 08)")
    args = p.parse_args()

    pcsc = PCSCProbe(load_pcsc())
    ctx = pcsc.context()
    print(f"[OK]   PC/SC context established (0x{ctx:x})")

    readers = pcsc.readers()
    if not readers:
        sys.exit("FAIL: no readers configured in pcscd")
    print(f"[OK]   {len(readers)} reader(s): {readers}")

    for reader in readers:
        rv, h, proto = pcsc.connect(reader)
        if rv != 0:
            print(f"[FAIL] {reader}: connect {pcsc.err(rv)}")
            continue
        print(f"[OK]   {reader}: connected (protocol T{proto})")
        cmds = []
        if args.select_piv:
            cmds.append(("SELECT PIV AID", bytes.fromhex("00A4040005A000000308")))
        if args.apdu:
            cmds.append((f"APDU {args.apdu}", bytes.fromhex(args.apdu)))
        for name, apdu in cmds:
            rv, resp = pcsc.transmit(h, proto, apdu)
            if rv != 0:
                print(f"[FAIL] {name}: {pcsc.err(rv)}")
            else:
                print(f"[OK]   {name} -> {resp.hex()}")
        pcsc.sc.SCardDisconnect(h, SCARD_UNPOWER_CARD)

    pcsc.sc.SCardReleaseContext(ctx)
    print("[OK]   PC/SC diagnostics complete")


if __name__ == "__main__":
    main()