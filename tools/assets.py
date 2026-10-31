#!/usr/bin/env python3
"""Asset tooling for Tomodachi Collection.

The cartridge's filesystem is one level of NARC archives (plus the ARM9
overlays), and the archives nest another level or two.  Every leaf is in a
standard Nitro format, though the 2D ones store their magic byte-reversed
(`RLCN` where the spec says `NCLR`):

    NARC    archive                 -> expanded as a directory
    BMD0    model (NSBMD)           -> kept as .nsbmd
    BCA0    model animation (NSBCA) -> kept as .nsbca
    BTA0    texture animation       -> kept as .nsbta
    BTP0    texture pattern         -> kept as .nsbtp
    RGCN    tile graphics (NCGR)    -> PNG (with its sibling RLCN palette)
    RLCN    palette (NCLR)          -> PNG strip
    RCSN    screen map (NSCR)       -> PNG (composited from tiles + palette)
    RECN    cell bank (NCER)        -> .ncer, plus a JSON summary
    RNAN    animation (NANR)        -> .nanr, plus a JSON summary
    RTFN    font (NFTR)             -> .nftr
    NTFT    texture data            -> .ntft
    NTFP    texture palette         -> .ntfp
    MESG    message bank (BMG)      -> TSV of message id, text
    SDAT    sound archive           -> WAV per sample, raw SSEQ/SBNK/SWAR

Commands:

    assets.py index     classify every leaf, write an inventory
    assets.py unpack    unpack archives into a mirror directory
    assets.py extract   unpack, then convert leaves to PNG/WAV/TSV

`index` is the map: it walks the same recursion the other commands use and
records, per leaf, the path inside the cartridge, the archive nesting, the
format and its parameters.  Everything else is driven by that walk, so a new
converter only has to be added in one place.

Output layout (all under `build/assets/`, gitignored):

    index.tsv              every leaf: path, kind, size, depth
    unpack/<path>          the cartridge tree, archives expanded, with
                           extensions chosen from the leaf's magic
    art/<path>.png         converted graphics
    text/<path>.tsv        converted message banks
    audio/<path>/          one WAV per sample, plus SSEQ/SBNK kept verbatim

Nothing here writes into the repository's tracked files: conversion is always
a build step, so the repo stays free of game data.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ndsrom
from tomolib import lz, narc, nitro2d, sdat, text

DEFAULT_ROM = Path("../roms/ds/tomo_collection_rev1.nds")

# Leaf kind -> extension for the unpacked mirror.  ``None`` means "the path
# already ends in a usable extension"; archives never reach this table because
# they are expanded into directories.
EXTENSIONS = {
    "BMD0": ".nsbmd",
    "BCA0": ".nsbca",
    "BTA0": ".nsbta",
    "BTP0": ".nsbtp",
    "BMA0": ".nsbma",
    "BVA0": ".nsbva",
    "RGCN": ".ncgr",
    "RLCN": ".nclr",
    "RCSN": ".nscr",
    "RECN": ".ncer",
    "RNAN": ".nanr",
    "RTFN": ".nftr",
    "NTFT": ".ntft",
    "NTFP": ".ntfp",
    "MESG": ".bmg",
    "SDAT": ".sdat",
    "raw": ".bin",
}

# The four-character magics are stored reversed for the 2D/3D Nitro formats on
# this cartridge, so both spellings are accepted.
MAGICS = {
    b"NCLR": "RLCN", b"RLCN": "RLCN",
    b"NCGR": "RGCN", b"RGCN": "RGCN",
    b"NSCR": "RCSN", b"RCSN": "RCSN",
    b"NCER": "RECN", b"RECN": "RECN",
    b"NANR": "RNAN", b"RNAN": "RNAN",
    b"NFT R": "RTFN", b"RTFN": "RTFN",
    b"NSBMD": "BMD0", b"BMD0": "BMD0",
    b"NSBCA": "BCA0", b"BCA0": "BCA0",
    b"NSBTA": "BTA0", b"BTA0": "BTA0",
    b"NSBTP": "BTP0", b"BTP0": "BTP0",
    b"NSBMA": "BMA0", b"BMA0": "BMA0",
    b"NSBVA": "BVA0", b"BVA0": "BVA0",
    b"NTFT": "NTFT",
    b"NTFP": "NTFP",
    b"MESG": "MESG",
    b"SDAT": "SDAT",
    b"NARC": "NARC",
}


@dataclass
class Leaf:
    """One file recovered from the cartridge or from inside an archive."""

    path: str                     # cartridge path, archive members joined by '/'
    kind: str                     # format id, e.g. "RGCN", "BMD0", "raw"
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


def classify(data: bytes) -> str:
    """Format id for a leaf payload, from its magic."""
    kind = MAGICS.get(data[:4])
    return kind or "raw"


def walk(cart: Cartridge, max_depth: int = 4):
    """Yields every leaf, recursing through NARC archives."""
    pending = [(name, data, 0) for name, data in cart.files()]
    while pending:
        path, data, depth = pending.pop(0)
        if data[:4] == narc.MAGIC:
            if depth < max_depth:
                try:
                    archive = narc.Narc.parse(data)
                except narc.NarcError as exc:
                    print(f"warning: {path}: {exc}", file=sys.stderr)
                else:
                    for member in archive.members:
                        payload, _ = lz.decode_or_raw(member.data)
                        pending.append((f"{path}/{member.path}", payload, depth + 1))
                    continue
            yield Leaf(path=path, kind="NARC", size=len(data), depth=depth)
            continue
        yield Leaf(path=path, kind=classify(data), size=len(data), depth=depth,
                   data=data)


# ---------------------------------------------------------------- conversion


def mirror_name(leaf: Leaf) -> str:
    """Path of a leaf in the unpacked mirror, with a format extension."""
    extension = EXTENSIONS.get(leaf.kind, ".bin")
    name = leaf.path.rsplit("/", 1)[-1]
    if "." in name:
        return leaf.path
    return leaf.path + extension


def _siblings(leaves: list[Leaf], leaf: Leaf, kind: str) -> list[Leaf]:
    """Leaves of `kind` in the same archive directory as `leaf`."""
    directory = leaf.path.rsplit("/", 1)[0] if "/" in leaf.path else ""
    prefix = directory + "/" if directory else ""
    return [other for other in leaves
            if other.kind == kind and other.path.startswith(prefix)
            and "/" not in other.path[len(prefix):]]


def _pick(leaf: Leaf, candidates: list[Leaf]) -> Leaf | None:
    """The candidate whose file name best matches `leaf`'s."""
    if not candidates:
        return None
    stem = leaf.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    for candidate in candidates:
        other = candidate.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        if other == stem:
            return candidate
    for candidate in candidates:
        other = candidate.path.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        if other in stem or stem in other:
            return candidate
    return candidates[0]


def convert_graphics(leaf: Leaf, leaves: list[Leaf], out: Path) -> str | None:
    """Writes the PNG for a 2D resource; returns a note, or None on failure."""
    if leaf.kind == "RLCN":
        nitro2d.nclr_to_png(leaf.data, out)
        return f"palette, {len(nitro2d.read_palette(leaf.data)[1])} colours"
    if leaf.kind == "RGCN":
        palette = _pick(leaf, _siblings(leaves, leaf, "RLCN"))
        if palette is None:
            return "no palette in this archive"
        width, height = nitro2d.ncgr_to_png(leaf.data, palette.data, out)
        return f"{width}x{height}"
    if leaf.kind == "RCSN":
        tiles = _pick(leaf, _siblings(leaves, leaf, "RGCN"))
        palette = _pick(leaf, _siblings(leaves, leaf, "RLCN"))
        if tiles is None or palette is None:
            return "no tiles or palette in this archive"
        width, height = nitro2d.nscr_to_png(leaf.data, tiles.data, palette.data, out)
        return f"{width}x{height} screen"
    return None


def convert_text(leaf: Leaf, out: Path) -> str | None:
    """Writes one message bank as TSV; returns a note, or None on failure."""
    encoding, codec, messages = text.parse_bmg(leaf.data)
    text.write_tsv(out, messages)
    return f"{len(messages)} messages, encoding {encoding} ({codec})"


AUDIO_EXTENSIONS = {
    b"SSEQ": ".sseq",
    b"SBNK": ".sbnk",
    b"SWAR": ".swar",
    b"SSAR": ".ssar",
    b"STRM": ".strm",
    b"SWAV": ".swav",
}


def convert_audio(leaf: Leaf, out: Path) -> str | None:
    """Splits an SDAT into its archived files and converts what is decoded.

    Sequences (`SSEQ`), banks (`SBNK`), wave archives (`SWAR`), sequence
    archives (`SSAR`) and streams (`STRM`) are written out verbatim, since an
    editor wants the untouched stream.  Standalone `SWAV` samples are also
    decoded to WAV.  The samples inside a `SWAR` are *not* decoded yet: their
    per-sample headers sit after an offset table whose base is not settled
    (see docs/assets.md), and writing guessed WAVs would be worse than writing
    none -- the archive is dumped intact instead.
    """
    archive = sdat.Sdat(leaf.data)
    out.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    waves = 0
    for fid, payload in archive.files():
        magic = payload[:4]
        extension = AUDIO_EXTENSIONS.get(magic, ".bin")
        label = magic.decode("latin-1").strip() or "unk"
        (out / f"{fid:03d}_{label}{extension}").write_bytes(payload)
        counts[extension] = counts.get(extension, 0) + 1
        if magic == b"SWAV":
            try:
                sdat.write_wav(out / f"{fid:03d}_SWAV.wav", sdat.parse_swav(payload))
                waves += 1
            except sdat.SdatError as exc:
                print(f"warning: {leaf.path} file {fid}: {exc}", file=sys.stderr)
    (out / "index.json").write_text(json.dumps({
        "archive": leaf.path,
        "names": archive.names(),
        "files": counts,
        "waves": waves,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = ", ".join(f"{count} {ext}" for ext, count in sorted(counts.items()))
    return f"{summary}" + (f", {waves} wav" if waves else "")


def convert(leaf: Leaf, leaves: list[Leaf], root: Path) -> str | None:
    """Converts one leaf under `root`; returns a human-readable note."""
    relative = mirror_name(leaf)
    if leaf.kind in ("RLCN", "RGCN", "RCSN"):
        out = root / "art" / (relative.rsplit(".", 1)[0] + ".png")
    elif leaf.kind == "MESG":
        out = root / "text" / (relative.rsplit(".", 1)[0] + ".tsv")
    elif leaf.kind == "SDAT":
        return convert_audio(leaf, root / "audio" / relative.rsplit(".", 1)[0])
    else:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    if leaf.kind in ("RLCN", "RGCN", "RCSN"):
        return convert_graphics(leaf, leaves, out)
    return convert_text(leaf, out)


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
        print(f"  {kind:6s} {count:6d}")
    return 0


def cmd_unpack(args):
    cart = Cartridge(args.rom)
    root = Path(args.output)
    written = 0
    for leaf in walk(cart, args.depth):
        if leaf.kind == "NARC":
            continue
        path = root / mirror_name(leaf)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(leaf.data)
        written += 1
    print(f"unpacked {written} files to {root}")
    return 0


def cmd_extract(args):
    cart = Cartridge(args.rom)
    root = Path(args.output)
    leaves = list(walk(cart, args.depth))
    kept = converted = skipped = 0
    notes: list[tuple[str, str, str]] = []

    for leaf in leaves:
        if leaf.kind == "NARC":
            continue
        path = root / "unpack" / mirror_name(leaf)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(leaf.data)
        kept += 1
        try:
            note = convert(leaf, leaves, root)
        except (ValueError, IndexError, struct.error) as exc:
            # One malformed leaf must not abort a 6000-file run: record it and
            # carry on, so convert.tsv is the list of what still needs work.
            skipped += 1
            notes.append((leaf.path, leaf.kind,
                          f"error: {type(exc).__name__}: {exc}"))
            continue
        if note is None:
            skipped += 1
        else:
            converted += 1
            notes.append((leaf.path, leaf.kind, note))

    report = root / "convert.tsv"
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("w", encoding="utf-8") as fh:
        fh.write("path\tkind\tresult\n")
        for path_name, kind, note in notes:
            fh.write(f"{path_name}\t{kind}\t{note}\n")

    print(f"copied {kept} leaves, converted {converted}, skipped {skipped}")
    print(f"report: {report}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rom", type=Path, default=DEFAULT_ROM,
                        help=f"ROM dump (default: {DEFAULT_ROM})")
    parser.add_argument("--depth", type=int, default=4,
                        help="maximum archive nesting to descend")
    sub = parser.add_subparsers(dest="command", required=True)

    index = sub.add_parser("index", help="classify every leaf file")
    index.add_argument("-o", "--output", default="build/assets/index.tsv")
    index.set_defaults(func=cmd_index)

    unpack = sub.add_parser("unpack", help="unpack archives into a mirror")
    unpack.add_argument("-o", "--output", default="build/assets/unpack")
    unpack.set_defaults(func=cmd_unpack)

    extract = sub.add_parser("extract",
                             help="unpack and convert to PNG/WAV/TSV")
    extract.add_argument("-o", "--output", default="build/assets")
    extract.set_defaults(func=cmd_extract)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
