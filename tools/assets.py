#!/usr/bin/env python3
"""Asset tooling for Tomodachi Collection.

The cartridge's filesystem is one level of NARC archives (everything except the
ARM9 overlays) that nest another level or two, with leaves in Nintendo DS
standard formats:

    NARC    archive                 -> unpacked, recursively
    SDAT    sound archive           -> SSEQ (sequences), SWAV (samples), banks
    NSBTX   texture dictionary      -> PNG per texture
    NCGR    tile graphics           -> PNG (with its NCLR palette)
    NCLR    palette                 -> PNG strip
    BMG     message bank            -> CSV of message id, text
    BTX     text bank               -> CSV of message id, text

Commands:

    assets.py index                 classify every leaf, write an inventory
    assets.py unpack                unpack archives into a mirror directory
    assets.py extract               convert leaves to PNG/WAV/CSV/TXT
    assets.py pack                  rebuild archives from an edited mirror

`index` is the map: it walks the same recursion the other commands use and
records, per leaf, the path inside the cartridge, the archive nesting, the
format and its parameters.  Everything else is driven by that walk.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ndsrom
from tomolib import lz, narc

DEFAULT_ROM = Path("../roms/ds/tomo_collection_rev1.nds")


@dataclass
class Leaf:
    """One file recovered from the cartridge or from inside an archive."""

    path: str                     # cartridge path, archive members joined by '/'
    kind: str                     # format id, e.g. "NSBTX", "SWAV", "raw"
    size: int                     # decompressed byte length
    depth: int                    # how many archives deep
    data: bytes = field(repr=False, default=b"")


# ---------------------------------------------------------------- ROM access


class Cartridge:
    """Reads the filesystem of a Tomodachi Collection ROM dump."""

    def __init__(self, path: Path):
        self.path = path
        self.rom = path.read_bytes()
        header = ndsrom.parse_header(self.rom)
        self.header = header
        self.names, _ = ndsrom.parse_fnt(
            self.rom[header["fnt_offset"]:header["fnt_offset"] + header["fnt_size"]])
        self.entries = ndsrom.fat_entries(self.rom, header)

    def files(self):
        """Yields (path, decompressed bytes) for every cartridge file."""
        for fid, start, end in self.entries:
            payload, _ = lz.decode_or_raw(self.rom[start:end])
            yield self.names.get(fid, f"file{fid:04d}"), payload


BINARY = {"raw", "arm9", "overlay", "NARC", "SDAT", "NSBTX", "NSBMD", "NSBMD"}


def classify(data: bytes) -> str:
    """Format id for a leaf payload, from its magic."""
    magic = data[:4]
    if magic == narc.MAGIC:
        return "NARC"
    if magic == b"SDAT":
        return "SDAT"
    if magic == b"NSBTX":
        return "NSBTX"
    if magic == b"NSBMD":
        return "NSBMD"
    if magic == b"NCGR":
        return "NCGR"
    if magic == b"NCLR":
        return "NCLR"
    if magic == b"NSCR":
        return "NSCR"
    if magic == b"NCER":
        return "NCER"
    if magic == b"NANR":
        return "NANR"
    if magic == b"SSEQ":
        return "SSEQ"
    if magic == b"SWAV":
        return "SWAV"
    if magic == b"SWAR":
        return "SWAR"
    if magic in (b"\x20\x00\x00\x00", b"\x20\x00"):
        return "BMG-like"
    if magic == b"BTX\x00":
        return "BTX"
    if magic[:3] in (b"BTA", b"BTX"):
        return "BTX"
    if magic[:2] == b"\x1f\x8b":
        return "gzip"
    return "raw"


def walk(cart: Cartridge, max_depth: int = 4):
    """Yields every leaf, recursing through NARC archives."""
    pending = [(name, data, 0) for name, data in cart.files()]
    while pending:
        path, data, depth = pending.pop(0)
        if data[:4] == narc.MAGIC:
            yield Leaf(path=path, kind="NARC", size=len(data), depth=depth,
                       data=b"" if depth else data)
            if depth >= max_depth:
                continue
            try:
                archive = narc.Narc.parse(data)
            except narc.NarcError as exc:
                print(f"warning: {path}: {exc}", file=sys.stderr)
                continue
            for member in archive.members:
                payload, _ = lz.decode_or_raw(member.data)
                pending.append((f"{path}/{member.path}", payload, depth + 1))
            continue
        yield Leaf(path=path, kind=classify(data), size=len(data), depth=depth,
                   data=data)


# ------------------------------------------------------------------ commands


def cmd_index(args):
    cart = Cartridge(args.rom)
    leaves = list(walk(cart, args.depth))
    counts: dict[str, int] = {}
    for leaf in leaves:
        counts[leaf.kind] = counts.get(leaf.kind, 0) + 1

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        fh.write("path\tkind\tsize\tdepth\n")
        for leaf in leaves:
            fh.write(f"{leaf.path}\t{leaf.kind}\t{leaf.size}\t{leaf.depth}\n")

    print(f"{len(leaves)} leaves -> {out}")
    for kind, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:10s} {count:6d}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM,
                        help=f"ROM dump (default: {DEFAULT_ROM})")
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="classify every leaf file")
    index.add_argument("-o", "--output", default="build/assets/index.tsv")
    index.add_argument("--depth", type=int, default=4,
                       help="maximum archive nesting to descend")
    index.set_defaults(func=cmd_index)

    args = parser.parse_args(argv)
    args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
