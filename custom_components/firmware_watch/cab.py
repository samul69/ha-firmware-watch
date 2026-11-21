"""Minimal Microsoft CAB reader (stored + MSZIP), enough for Dell catalogs."""

from __future__ import annotations

import struct
import zlib


class CabError(Exception):
    """Unsupported or broken cabinet."""


def extract_first(data: bytes) -> bytes:
    """Return the contents of the first file in the first folder."""
    if data[:4] != b"MSCF":
        raise CabError("not a cabinet")
    coff_files = struct.unpack_from("<I", data, 16)[0]
    c_folders, c_files, flags = struct.unpack_from("<HHH", data, 26)
    off = 36
    cb_cfheader = cb_cffolder = cb_cfdata = 0
    if flags & 0x0004:  # cfhdrRESERVE_PRESENT
        cb_cfheader, cb_cffolder, cb_cfdata = struct.unpack_from("<HBB", data, off)
        off += 4 + cb_cfheader
    if flags & 0x0001:  # prev cabinet name + disk
        for _ in range(2):
            off = data.index(b"\0", off) + 1
    if flags & 0x0002:  # next cabinet
        for _ in range(2):
            off = data.index(b"\0", off) + 1
    if c_folders < 1 or c_files < 1:
        raise CabError("empty cabinet")
    coff_start, c_cfdata, type_compress = struct.unpack_from("<IHH", data, off)
    method = type_compress & 0x000F

    # first CFFILE -> uncompressed size
    file_size = struct.unpack_from("<I", data, coff_files)[0]

    out = bytearray()
    pos = coff_start
    zdict = b""
    for _ in range(c_cfdata):
        cb_data, cb_uncomp = struct.unpack_from("<HH", data, pos + 4)
        pos += 8 + cb_cfdata
        block = data[pos : pos + cb_data]
        pos += cb_data
        if method == 0:
            out += block
        elif method == 1:
            if block[:2] != b"CK":
                raise CabError("bad MSZIP block")
            d = zlib.decompressobj(-15, zdict=zdict) if zdict else zlib.decompressobj(-15)
            chunk = d.decompress(block[2:]) + d.flush()
            out += chunk
            zdict = bytes(chunk[-32768:])
        else:
            raise CabError(f"compression type {method} not supported")
        if len(out) >= file_size:
            break
    return bytes(out[:file_size])
