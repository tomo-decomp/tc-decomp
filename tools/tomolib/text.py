"""Text extraction for the game's message banks.

Two containers matter for translation work:

    BMG   a message bank: `MESG` header, an `INF1` index and a `DAT1` string
          blob.  The index gives each message an id and an offset into `DAT1`.
    BTX   older/simpler text banks, a bare block of strings.

Both are dumped to a two-column file (id, text) that can be edited and read
back with the same tool, which is how a translation pass stays reviewable in
git: the extracted text is ordinary UTF-8.

The game is Japanese.  Every string is decoded with the bank's declared
encoding when that succeeds, and with Shift-JIS otherwise; anything that still
does not decode is kept as an escape sequence (`\\xNN`) rather than dropped, so
no bytes are lost on the way back in.
"""

from __future__ import annotations

import struct

MESG = b"MESG"
# BMG character encodings, from the format's header field at 0x10.
ENCODINGS = {0: "cp1252", 1: "utf-16-le", 2: "shift-jis", 3: "utf-8"}


class BmgError(ValueError):
    """The message bank is malformed."""


def _find(data: bytes, magic: bytes, start: int = 0) -> int:
    return data.find(magic, start)


def is_bmg(data: bytes) -> bool:
    return data[:4] == MESG


def parse_bmg(data: bytes) -> tuple[int, str, list[tuple[int, str]]]:
    """Returns (encoding id, codec, [(message id, text)])."""
    if not is_bmg(data) or len(data) < 0x20:
        raise BmgError("not a BMG")
    # Header: "MESG", "bmg1", size, section count, encoding id.
    encoding = struct.unpack_from("<I", data, 0x10)[0]
    codec = ENCODINGS.get(encoding)

    inf1 = _find(data, b"INF1")
    dat1 = _find(data, b"DAT1")
    if inf1 < 0 or dat1 < 0:
        raise BmgError("missing INF1/DAT1")
    count = struct.unpack_from("<H", data, inf1 + 8)[0]
    entry_size = struct.unpack_from("<H", data, inf1 + 0x0A)[0] or 8
    dat_size = struct.unpack_from("<I", data, dat1 + 4)[0]
    payload = dat1 + 8
    payload_end = min(len(data), dat1 + dat_size)

    # INF1 entries are 12 bytes and hold the DAT1 offset in their first word
    # (measured; the rest are text width/render fields).
    offsets = []
    for i in range(count):
        base = inf1 + 0x10 + i * entry_size
        if base + 4 > len(data):
            break
        offsets.append(struct.unpack_from("<I", data, base)[0])
    if not offsets:
        raise BmgError("no message entries")
    if codec is None or codec == "shift-jis":
        # The header's id is unreliable on this cartridge (every bank says 2,
        # while the strings are really UTF-16LE), so the text itself decides.
        codec = detect_encoding(data, payload + offsets[0], payload_end)

    # Each message runs from its own offset to the next one.  Slicing by the
    # index matters: the text contains 0x1A escape sequences whose arguments
    # include zero words, so stopping at the first 0x0000 would truncate those
    # messages and silently drop text.
    messages: list[tuple[int, str]] = []
    for i, offset in enumerate(offsets):
        start = payload + offset
        stop = (payload + offsets[i + 1]) if i + 1 < len(offsets) else payload_end
        messages.append((i, decode_range(data, start, min(stop, payload_end), codec)))
    return encoding, codec, messages


def decode_range(data: bytes, start: int, end: int, codec: str) -> str:
    """Decodes one message's byte range, dropping its terminator only."""
    chunk = data[start:end]
    if codec.startswith("utf-16"):
        if len(chunk) % 2:
            chunk = chunk[:-1]
        while len(chunk) >= 2 and chunk[-2:] == b"\x00\x00":
            chunk = chunk[:-2]
        return chunk.decode(codec, errors="backslashreplace")
    chunk = chunk.split(b"\x00")[0]
    return chunk.decode(codec, errors="backslashreplace")


def detect_encoding(data: bytes, start: int, end: int) -> str:
    """Picks between UTF-16LE and Shift-JIS by which one decodes as text.

    Japanese UTF-16LE text has high bytes in the 0x30..0x9F range rather than
    0x00, so a plain zero-byte test is not enough: decode a sample both ways
    and prefer the one whose characters are kana, kanji or ASCII.
    """
    sample = data[start:min(end, start + 512)]
    if len(sample) < 4:
        return "shift-jis"
    return max(("utf-16-le", "shift-jis"), key=lambda c: _score(sample, c))


def _score(sample: bytes, codec: str) -> int:
    """How much of `sample` reads as Japanese or ASCII text in `codec`."""
    try:
        decoded = sample.decode(codec, errors="replace")
    except LookupError:
        return -1
    score = 0
    for ch in decoded:
        code = ord(ch)
        if ch.isascii() and ch.isprintable():
            score += 2
        elif 0x3040 <= code <= 0x30FF:      # kana
            score += 3
        elif 0x4E00 <= code <= 0x9FFF:      # kanji
            score += 3
        elif 0xFF01 <= code <= 0xFF60:      # full-width forms
            score += 2
        elif ch in "\n\r\t" or code < 0x20:
            score += 1
        elif ch == "\ufffd":
            score -= 4
        else:
            score -= 1
    return score


def decode_string(data: bytes, start: int, end: int, codec: str) -> str:
    """Decodes one NUL-terminated string, keeping undecodable bytes escaped."""
    if codec.startswith("utf-16"):
        chunks = []
        pos = start
        while pos + 1 < end:
            unit = data[pos:pos + 2]
            if unit == b"\x00\x00":
                break
            chunks.append(unit)
            pos += 2
        raw = b"".join(chunks)
        return raw.decode(codec, errors="backslashreplace")
    stop = data.find(b"\x00", start, end)
    if stop < 0:
        stop = end
    return data[start:stop].decode(codec, errors="backslashreplace")


def _printable(text: str) -> int:
    """Rough score: how much of `text` looks like real text."""
    good = 0
    for ch in text:
        if ch.isprintable() and ch not in "\\":
            good += 1
        elif ch in "\n\t":
            good += 1
    return good


def _escape(text: str) -> str:
    """Escapes a message onto one tab-separated line, losslessly."""
    out = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\x{ord(ch):02x}")
        else:
            out.append(ch)
    return "".join(out)


def _unescape(text: str) -> str:
    out = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            if nxt == "x" and i + 3 < len(text):
                out.append(chr(int(text[i + 2:i + 4], 16)))
                i += 4
                continue
            if nxt in "nt\\":
                out.append({"n": "\n", "t": "\t", "\\": "\\"}[nxt])
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def write_tsv(path, messages: list[tuple[int, str]]) -> None:
    """Writes id/text rows; tabs and newlines are escaped so the file is flat."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("id\ttext\n")
        for mid, text in messages:
            fh.write(f"{mid}\t{_escape(text)}\n")


def read_tsv(path) -> list[tuple[int, str]]:
    """Reads the format `write_tsv` produces."""
    rows: list[tuple[int, str]] = []
    with open(path, encoding="utf-8") as fh:
        header = fh.readline()
        if not header.startswith("id\t"):
            raise ValueError(f"{path}: not a message table")
        for line in fh:
            if not line.strip():
                continue
            mid, _, text = line.rstrip("\n").partition("\t")
            rows.append((int(mid), _unescape(text)))
    return rows
