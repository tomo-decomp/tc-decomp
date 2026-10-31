"""Minimal PNG writer (no third-party dependencies).

The DS graphics tools all emit indexed images as RGBA PNG, so this module only
needs to write plain 8-bit RGB/RGBA files: one IDAT of zlib-compressed rows,
filter type 0 on every row.  Keeping it here means the asset tooling stays
standard-library only, like tools/ndsrom.py.
"""

from __future__ import annotations

import struct
import zlib

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def _header(width: int, height: int, alpha: bool) -> bytes:
    color_type = 6 if alpha else 2
    return _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color_type, 0, 0, 0))


def write(path, width: int, height: int, pixels, alpha: bool = True) -> None:
    """Writes an 8-bit PNG.

    `pixels` is a flat sequence of bytes: 4 per pixel when `alpha`, else 3.
    """
    stride = 4 if alpha else 3
    expected = width * height * stride
    data = bytes(pixels)
    if len(data) != expected:
        raise ValueError(f"expected {expected} bytes of pixel data, got {len(data)}")
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        rows += data[y * width * stride:(y + 1) * width * stride]
    with open(path, "wb") as fh:
        fh.write(PNG_SIGNATURE)
        fh.write(_header(width, height, alpha))
        fh.write(_chunk(b"IDAT", zlib.compress(bytes(rows), 9)))
        fh.write(_chunk(b"IEND", b""))


def write_indexed(path, width: int, height: int, indices, palette) -> None:
    """Expands 8-bit palette indices into RGBA and writes a PNG."""
    pixels = bytearray()
    for index in indices:
        if index * 4 + 3 < len(palette):
            pixels += palette[index * 4:index * 4 + 4]
        else:
            pixels += b"\x00\x00\x00\x00"
    write(path, width, height, pixels, alpha=True)
