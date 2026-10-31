"""Nintendo DS NARC archives.

A NARC is the DS "nitro archive": a header, then three named chunks.

    NARC
    BTAF  file allocation table: base offset + (start, end) pairs
    BTNF  file name table (same layout as a ROM's FNT)
    GMIF  the file data, addressed by the BTAF offsets

Everything in Tomodachi Collection's filesystem except the ARM9 overlays is a
NARC, and archives nest (a `Map` archive contains `Model` archives, and so on),
so the asset tools recurse until they reach a leaf format.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"NARC"

BTAF = b"BTAF"
BTNF = b"BTNF"
GMIF = b"GMIF"


class NarcError(ValueError):
    """The archive is malformed."""


@dataclass
class Member:
    """One file inside an archive."""

    id: int
    path: str
    data: bytes

    @property
    def magic(self) -> str:
        head = self.data[:4]
        if len(head) < 4:
            return head.hex()
        if all(0x20 <= b < 0x7F for b in head):
            return head.decode("ascii")
        return head.hex()


@dataclass
class Narc:
    """A parsed archive: ordered members plus its original chunk layout."""

    members: list[Member] = field(default_factory=list)
    version: int = 0

    @classmethod
    def parse(cls, data: bytes) -> "Narc":
        if len(data) < 0x10 or data[:4] != MAGIC:
            raise NarcError("not a NARC")
        header_size = struct.unpack_from("<H", data, 0x0C)[0]
        if header_size < 0x10:
            raise NarcError(f"unexpected NARC header size {header_size:#x}")
        chunk_count = struct.unpack_from("<H", data, 0x0E)[0]
        chunks: dict[bytes, tuple[int, int]] = {}
        off = header_size
        for _ in range(chunk_count):
            if off + 8 > len(data):
                raise NarcError("chunk table runs past the end")
            magic = data[off:off + 4]
            chunk_size = struct.unpack_from("<I", data, off + 4)[0]
            if off + chunk_size > len(data):
                raise NarcError(f"{magic!r} chunk runs past the end")
            chunks[magic] = (off, chunk_size)
            off += chunk_size
        for needed in (BTAF, GMIF):
            if needed not in chunks:
                raise NarcError(f"missing {needed!r} chunk")

        btaf_off, _ = chunks[BTAF]
        count = struct.unpack_from("<H", data, btaf_off + 8)[0]
        base = struct.unpack_from("<I", data, btaf_off + 0x0C)[0]
        if btaf_off + 0x10 + count * 8 > len(data):
            raise NarcError("BTAF entries run past the end")

        names: dict[int, str] = {}
        if BTNF in chunks:
            btnf_off, btnf_size = chunks[BTNF]
            names = _parse_btxf(data[btnf_off:btnf_off + btnf_size])

        gmif_off, gmif_size = chunks[GMIF]
        members: list[Member] = []
        for fid in range(count):
            start, end = struct.unpack_from("<II", data, btaf_off + 0x10 + fid * 8)
            start -= base
            end -= base
            if start > end or gmif_off + 8 + end > len(data):
                raise NarcError(f"member {fid} has a bad range")
            members.append(Member(
                id=fid,
                path=names.get(fid, f"file{fid:03d}"),
                data=data[gmif_off + 8 + start:gmif_off + 8 + end],
            ))
        return cls(members=members, version=struct.unpack_from("<H", data, 0x06)[0])


def _parse_btxf(btxf: bytes) -> dict[int, str]:
    """Parses a BTNF/BTXT name table: paths by file id."""
    if len(btxf) < 8 or btxf[:4] not in (BTNF, b"BTXT"):
        return {}
    dir_count = struct.unpack_from("<H", btfx, 6)[0]
    if 8 + dir_count * 8 > len(btxf):
        return {}
    dirs = [struct.unpack_from("<IH", btfx, 8 + d * 8) for d in range(dir_count)]
    paths: dict[int, str] = {}
    seen: set[int] = set()
    stack = [(0, "")]
    while stack:
        d, prefix = stack.pop()
        if d in seen or d >= dir_count:
            continue
        seen.add(d)
        pos, file_id = dirs[d]
        while pos < len(btxf):
            length = btfx[pos]
            pos += 1
            if length == 0:
                break
            name_len = length & 0x7F
            name = btfx[pos:pos + name_len].decode("shift-jis", errors="replace")
            pos += name_len
            if length & 0x80:
                if pos + 2 > len(btxf):
                    break
                child = struct.unpack_from("<H", btfx, pos)[0] & 0x0FFF
                pos += 2
                stack.append((child, prefix + name + "/"))
            else:
                paths[file_id] = prefix + name
                file_id += 1
    return paths


def is_narc(data: bytes) -> bool:
    return data[:4] == MAGIC


def build(members: list[Member], base: int = 0x02000000, version: int = 0x0001) -> bytes:
    """Packs member data back into a NARC with a name table.

    The layout mirrors what the DS SDK's `NARC` tool writes: BTAF, BTNF, GMIF
    with 4-byte alignment, so a rebuilt archive has the same shape as the one
    it replaces.
    """
    payload = bytearray()
    offsets = []
    for member in members:
        offsets.append((base + len(payload), base + len(payload) + len(member.data)))
        payload += member.data
        while len(payload) % 4:
            payload.append(0)

    btaf = bytearray(BTAF)
    btaf += struct.pack("<IHHII", 0x0C + 8 + len(members) * 8, 0x0100, 0x0001,
                        len(members), base)
    for start, end in offsets:
        btaf += struct.pack("<II", start, end)
    btaf += pack_names([m.path for m in members])

    gmif = bytearray(GMIF)
    gmif += struct.pack("<I", 8 + len(payload))
    gmif += payload

    total = 0x10 + len(btaf) + len(gmif)
    header = MAGIC + struct.pack("<HHIHH", 0xFFFE, 0x0100, total, 0x10, 2)
    return bytes(header + btaf + gmif)


def pack_names(paths: list[str]) -> bytes:
    """Builds a flat BTNF for the given paths (all files in one directory)."""
    names = [p.rsplit("/", 1)[-1] for p in paths]
    table = bytearray(struct.pack("<4sHH", BTNF, 0x0C + 8 + sum(1 + len(n) for n in names) + 1 + 8, 0x0100))
    table += struct.pack("<IH", 8, 1)  # one directory at offset 8, first id 0
    for name in names:
        table.append(len(name))
        table += name.encode("shift-jis", errors="replace")
    table.append(0)
    while len(table) % 4:
        table.append(0)
    struct.pack_into("<I", table, 4, len(table))
    return bytes(table)
