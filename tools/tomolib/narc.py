"""Nintendo DS NARC archives.

A NARC ("nitro archive") is a 0x10-byte header followed by three chunks:

    NARC  header: BOM, version, total size, header size, section count
    BTAF  file allocation table: file count, then (start, end) pairs, offsets
          relative to the start of the GMIF payload
    BTNF  file name table: directory table, then the names
    GMIF  the file data

The directory table is an array of

    name_offset  u32   relative to the start of the directory table
    first_file   u16   first file id owned by this directory
    dir_count    u16   number of directories; for the root entry this field is
                       the table length in the DS SDK's own writer

The layout here matches `tools/nitroarc` in pokeplatinum/pokeheartgold, which
is the reference these tools were written against.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"NARC"

BTAF = b"BTAF"
BTNF = b"BTNF"
GMIF = b"GMIF"

NARC_HEADER_SIZE = 0x10
FATB_HEADER_SIZE = 0x0C
FNTB_HEADER_SIZE = 0x08
FIMG_HEADER_SIZE = 0x08


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
    """A parsed archive: ordered members plus its original header fields."""

    members: list[Member] = field(default_factory=list)
    version: int = 0

    @classmethod
    def parse(cls, data: bytes) -> "Narc":
        if len(data) < NARC_HEADER_SIZE or data[:4] != MAGIC:
            raise NarcError("not a NARC")
        version, total, header_size, section_count = struct.unpack_from(
            "<HIHH", data, 0x06)
        if header_size < NARC_HEADER_SIZE or header_size > len(data):
            raise NarcError(f"bad header size {header_size:#x}")

        sections: dict[bytes, tuple[int, int]] = {}
        off = header_size
        for _ in range(section_count):
            if off + 8 > len(data):
                raise NarcError("section table runs past the end")
            magic = data[off:off + 4]
            size = struct.unpack_from("<I", data, off + 4)[0]
            if size < 8 or off + size > len(data):
                raise NarcError(f"{magic!r} section has a bad size {size:#x}")
            sections[magic] = (off, size)
            off += size
        for needed in (BTAF, GMIF):
            if needed not in sections:
                raise NarcError(f"missing {needed!r} section")

        btaf_off, _ = sections[BTAF]
        count = struct.unpack_from("<H", data, btaf_off + 0x08)[0]
        first = btaf_off + FATB_HEADER_SIZE
        if first + count * 8 > len(data):
            raise NarcError("BTAF entries run past the end")

        names: dict[int, str] = {}
        if BTNF in sections:
            fnt_off, fnt_size = sections[BTNF]
            names = _parse_fntb(data[fnt_off:fnt_off + fnt_size])

        gmif_off, gmif_size = sections[GMIF]
        payload = gmif_off + FIMG_HEADER_SIZE
        limit = gmif_off + gmif_size
        members: list[Member] = []
        for fid in range(count):
            start, end = struct.unpack_from("<II", data, first + fid * 8)
            if start > end or payload + end > limit:
                raise NarcError(f"member {fid} has a bad range")
            members.append(Member(id=fid,
                                  path=names.get(fid, f"file{fid:03d}"),
                                  data=data[payload + start:payload + end]))
        del total
        return cls(members=members, version=version)


def _parse_fntb(fnt: bytes) -> dict[int, str]:
    """Parses a BTNF directory/name table into paths by file id."""
    if len(fnt) < FNTB_HEADER_SIZE + 8:
        return {}
    table = fnt[FNTB_HEADER_SIZE:]
    count = struct.unpack_from("<H", table, 6)[0] & 0x0FFF
    if count == 0 or 8 * count > len(table):
        return {}
    dirs = [struct.unpack_from("<IHH", table, 8 * d) for d in range(count)]

    paths: dict[int, str] = {}
    seen: set[int] = set()
    stack = [(0, "")]
    while stack:
        d, prefix = stack.pop()
        if d in seen or d >= count:
            continue
        seen.add(d)
        name_off, file_id, _ = dirs[d]
        pos = name_off
        while pos < len(table):
            length = table[pos]
            pos += 1
            if length == 0:
                break
            name_len = length & 0x7F
            name = table[pos:pos + name_len].decode("shift-jis", errors="replace")
            pos += name_len
            if length & 0x80:
                if pos + 2 > len(table):
                    break
                child = struct.unpack_from("<H", table, pos)[0] & 0x0FFF
                pos += 2
                stack.append((child, prefix + name + "/"))
            else:
                paths[file_id] = prefix + name
                file_id += 1
    return paths


def is_narc(data: bytes) -> bool:
    return data[:4] == MAGIC


def build(members: list[Member]) -> bytes:
    """Packs members into a NARC laid out the way the DS SDK writes one."""
    payload = bytearray()
    ranges = []
    for member in members:
        ranges.append((len(payload), len(payload) + len(member.data)))
        payload += member.data
        while len(payload) % 4:
            payload.append(0)

    fatb = bytearray(BTAF)
    fatb += struct.pack("<IHH", FATB_HEADER_SIZE + 8 * len(members),
                        len(members), 0)
    for start, end in ranges:
        fatb += struct.pack("<II", start, end)

    fntb = bytearray(BTNF)
    names = bytearray()
    name_offset = 8  # one directory entry
    for member in members:
        name = member.path.rsplit("/", 1)[-1].encode("shift-jis", errors="replace")
        name_offset = name_offset if names else 8
        names.append(len(name))
        names += name
        name_offset = 8
    names.append(0)
    fntb += struct.pack("<IHH", 8, 0, 1)  # root: names at 8, files from 0, 1 dir
    fntb += names
    while len(fntb) % 4:
        fntb.append(0)
    struct.pack_into("<I", fntb, 4, len(fntb))

    gmif = bytearray(GMIF)
    gmif += struct.pack("<I", FIMG_HEADER_SIZE + len(payload))
    gmif += payload

    total = NARC_HEADER_SIZE + len(fatb) + len(fntb) + len(gmif)
    header = MAGIC + struct.pack("<HHIHH", 0xFFFE, 1, total, NARC_HEADER_SIZE, 3)
    return bytes(header + fatb + fntb + gmif)
