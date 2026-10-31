"""Nintendo DS LZ77 compression formats.

The DS SDK's `MI_CompressLZ` produces three variants, distinguished by the
first byte of the stream:

    0x10  LZ10  -- 12-bit length, 12-bit displacement
    0x11  LZ11  -- 4/12-bit length, 12-bit displacement
    0x40  LZ40  -- 4-bit length, 8-bit displacement (byte-oriented)

Every variant starts with a one-byte type and a 24-bit *decompressed* size, so
a stream can be recognised from its header alone.  Random data can begin with
0x10 by accident (ARM code often does: `10 40 2D E9` is `push {r4, lr}`), which
is why `decompress` cross-checks the header against the compressed input and
refuses a stream that would need more input than it has.

`compress` writes LZ11, which is what the SDK uses for the cartridge's own
files, so a decoded file can be re-encoded and fed back into the ROM builder.
"""

from __future__ import annotations

MAX_DECOMPRESSED = 64 * 1024 * 1024

TYPE_LZ10 = 0x10
TYPE_LZ11 = 0x11
TYPE_LZ40 = 0x40


class LZError(ValueError):
    """A stream is not valid LZ77, or is truncated."""


def header(data: bytes) -> tuple[int, int] | None:
    """Returns (type, decompressed size) if `data` starts with an LZ header."""
    if len(data) < 4:
        return None
    kind = data[0]
    if kind not in (TYPE_LZ10, TYPE_LZ11, TYPE_LZ40):
        return None
    size = data[1] | data[2] << 8 | data[3] << 16
    if size == 0 or size > MAX_DECOMPRESSED:
        return None
    return kind, size


def is_compressed(data: bytes) -> bool:
    """True if `data` really starts with an LZ77 stream.

    ARM code frequently begins with bytes that look like an LZ header -- the
    prologue `10 40 2D E9` (`stmdb r13!, {r4, lr}`) reads as "LZ10, 0xE92D40
    bytes" -- so the header alone is not evidence. The stream has to decode
    cleanly to exactly the advertised size.
    """
    if header(data) is None:
        return False
    try:
        decompress(data)
    except LZError:
        return False
    return True


def decode_or_raw(data: bytes) -> tuple[bytes, bool]:
    """Returns (payload, was_compressed), falling back to the raw bytes."""
    if header(data) is not None:
        try:
            return decompress(data), True
        except LZError:
            pass
    return data, False


def decompress(data: bytes) -> bytes:
    """Decompresses LZ10/LZ11/LZ40. Raises LZError on a malformed stream."""
    h = header(data)
    if h is None:
        raise LZError("no LZ77 header")
    kind, size = h
    if kind == TYPE_LZ40:
        return _decompress_lz40(data, size)
    return _decompress_lz77(data, size, kind == TYPE_LZ11)


def _decompress_lz77(data: bytes, size: int, lz11: bool) -> bytes:
    out = bytearray()
    i = 4
    n = len(data)
    try:
        while len(out) < size:
            flags = data[i]
            i += 1
            for bit in range(8):
                if len(out) >= size:
                    break
                if flags & (0x80 >> bit):
                    b1 = data[i]
                    i += 1
                    if lz11:
                        length = b1 >> 4
                        if length == 0:
                            length = ((b1 & 0x0F) << 4 | data[i] >> 4) + 0x11
                            i += 1
                        else:
                            length += 1
                        disp = ((b1 & 0x0F) << 8 | data[i]) + 1
                        i += 1
                    else:
                        b2 = data[i]
                        i += 1
                        length = (b1 >> 4) + 3
                        disp = ((b1 & 0x0F) << 8 | b2) + 1
                    if disp > len(out):
                        raise LZError(f"back-reference {disp} before output start")
                    start = len(out) - disp
                    if length > disp:
                        # Overlapping copy has to be done byte by byte.
                        for k in range(length):
                            out.append(out[start + k])
                    else:
                        out += out[start:start + length]
                else:
                    out.append(data[i])
                    i += 1
    except IndexError as exc:
        raise LZError("stream ends mid-block") from exc
    if len(out) != size:
        raise LZError(f"decoded {len(out)} bytes, header says {size}")
    return bytes(out)


def _decompress_lz40(data: bytes, size: int) -> bytes:
    out = bytearray()
    i = 4
    n = len(data)
    while len(out) < size:
        if i + 1 >= n:
            raise LZError("stream ends mid-token")
        flag = data[i]
        i += 1
        for _ in range(8):
            if len(out) >= size:
                break
            if flag & 0x80:
                if i + 1 >= n:
                    raise LZError("stream ends mid-token")
                b1 = data[i]
                b2 = data[i + 1]
                i += 2
                length = (b1 >> 4) + 3
                disp = ((b1 & 0x0F) << 8 | b2) + 1
                if disp > len(out):
                    raise LZError(f"back-reference {disp} before output start")
                start = len(out) - disp
                for k in range(length):
                    out.append(out[start + k])
            else:
                out.append(data[i])
                i += 1
            flag <<= 1
    return bytes(out)


def _match(data: bytes, pos: int, limit: int) -> tuple[int, int]:
    """Best (length, displacement) for `pos`, searching the sliding window.

    Overlapping runs are allowed: the decompressor copies byte by byte, so a
    match may extend past `pos` as long as the source bytes keep agreeing.
    """
    best_len, best_disp = 0, 0
    start = max(0, pos - 0x1000)
    max_len = min(limit, len(data) - pos)
    for back in range(pos - 1, start - 1, -1):
        length = 0
        while length < max_len and data[back + length] == data[pos + length]:
            length += 1
        if length >= 3 and length > best_len:
            best_len, best_disp = length, pos - back
            if length >= max_len:
                break
    return best_len, best_disp


def compress(data: bytes, kind: int = TYPE_LZ11) -> bytes:
    """Compresses `data` as LZ11 (default) or LZ10."""
    if kind not in (TYPE_LZ10, TYPE_LZ11):
        raise LZError("only LZ10 and LZ11 can be written")
    out = bytearray([kind, len(data) & 0xFF, len(data) >> 8 & 0xFF, len(data) >> 16 & 0xFF])
    pos = 0
    n = len(data)
    while pos < n:
        flag_pos = len(out)
        out.append(0)
        flags = 0
        for bit in range(8):
            if pos >= n:
                break
            limit = 0x12 if kind == TYPE_LZ10 else 0x110
            length, disp = _match(data, pos, limit)
            if length >= 3:
                flags |= 0x80 >> bit
                d = disp - 1
                if kind == TYPE_LZ10:
                    out.append((length - 3) << 4 | d >> 8)
                    out.append(d & 0xFF)
                elif length <= 0x10:
                    out.append((length - 1) << 4 | d >> 8)
                    out.append(d & 0xFF)
                else:
                    v = length - 0x11
                    out.append(v >> 4)
                    out.append((v & 0x0F) << 4 | d >> 8)
                    out.append(d & 0xFF)
                pos += length
            else:
                out.append(data[pos])
                pos += 1
        out[flag_pos] = flags
    return bytes(out)
