#!/usr/bin/env python3
"""
ndsrom.py -- Nintendo DS ROM unpacker, rebuilder and verifier.

Written for tomo_coll_decomp (Tomodachi Collection, game code CCUJ).
Standard library only, single file, no dependencies.

The guiding principle is *byte-exactness*: every byte of the cartridge image
is either (a) covered by a modelled region we extract verbatim (header area,
arm9, arm7, overlay tables, banner, FNT, FAT, and every file the FAT names),
(b) part of a run of the padding byte 0xFF, or (c) captured verbatim by the
residue pass.  `build` reverses that exactly, so

    extract -> build -> verify

reproduces the input ROM bit for bit.  That is milestone 1 of a matching
decompilation; later milestones replace regions with output rebuilt from
source until nothing of the original image is left.

--------------------------------------------------------------------------
NDS cartridge header (fields used here; header *area* is header_size bytes,
0x4000 on this cart)
--------------------------------------------------------------------------
  0x000  char[12]  game title            ("TOMODACHI")
  0x00C  char[4]   game code             ("CCUJ")
  0x010  char[2]   maker code            ("01")
  0x012  u8        unit code             (0x00 = NTR only on this cart)
  0x020  u32       arm9 ROM offset
  0x024  u32       arm9 entry address
  0x028  u32       arm9 RAM load address
  0x02C  u32       arm9 size
  0x030  u32       arm7 ROM offset
  0x034  u32       arm7 entry address
  0x038  u32       arm7 RAM load address
  0x03C  u32       arm7 size
  0x040  u32       FNT (file name table) offset
  0x044  u32       FNT size
  0x048  u32       FAT (file allocation table) offset
  0x04C  u32       FAT size
  0x050  u32       arm9 overlay table (y9) offset
  0x054  u32       arm9 overlay table size
  0x058  u32       arm7 overlay table (y7) offset
  0x05C  u32       arm7 overlay table size
  0x068  u32       icon/banner offset
  0x080  u32       total used ROM size (NTR region)
  0x084  u32       header size
  0x15E  u16       header CRC-16 (over 0x000..0x15D)

--------------------------------------------------------------------------
Overlay table entry (32 bytes, in y9.bin / y7.bin)
--------------------------------------------------------------------------
  0x00  u32  overlay id
  0x04  u32  RAM load address
  0x08  u32  size to copy
  0x0C  u32  .bss size
  0x10  u32  static initialiser start address
  0x14  u32  static initialiser end address
  0x18  u32  file id  (index into the FAT -> where the overlay bytes live)
  0x1C  u32  compressed size (low 24 bits) | flags (high byte)

--------------------------------------------------------------------------
FAT entry (8 bytes each, FAT size / 8 entries, indexed by file id)
--------------------------------------------------------------------------
  0x00  u32  start offset in ROM
  0x04  u32  end offset in ROM (exclusive)

--------------------------------------------------------------------------
FNT -- file name table
--------------------------------------------------------------------------
Main table, 8 bytes per directory, directory 0 = root:
  0x00  u32  offset of this directory's subtable, relative to FNT start
  0x04  u16  file id of the first file in this directory
  0x06  u16  parent directory id  (for the root entry: total directory count)

Sub-table, a sequence of entries terminated by a 0x00 length byte:
  u8 len
     len == 0x00          -> end of this directory
     0x01..0x7F           -> file,      followed by `len` name bytes
     0x81..0xFF           -> directory, followed by (len & 0x7F) name bytes
                             and then a u16 directory id
Files are numbered sequentially from the directory's first file id, in the
order they appear in the sub-table.
"""

import argparse
import hashlib
import heapq
import json
import struct
import sys
from pathlib import Path

PAD_BYTE = 0xFF          # unused cartridge space is 0xFF filled
OVERLAY_ENTRY_SIZE = 32
FAT_ENTRY_SIZE = 8
FNT_MAIN_ENTRY_SIZE = 8
MANIFEST_FORMAT = "tomo-coll-extract/1"

EXPECTED_GAMECODE = b"CCUJ"

# Banner version -> total size.  Versions 3+ pad to the DSi-animated size.
BANNER_SIZES = {1: 0xA80, 2: 0xE80, 3: 0x2300, 4: 0x2300, 5: 0x2300}


class RomError(Exception):
    """Raised for any structural problem; the CLI turns it into a loud error."""


def u16(buf, off):
    return struct.unpack_from("<H", buf, off)[0]


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def sha1_of(data):
    return hashlib.sha1(data).hexdigest()


def crc16(data, init=0xFFFF):
    """CRC-16 as the NDS header/banner use it: reflected, poly 0xA001."""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def parse_header(rom):
    """Returns the header fields we model, checked against the file bounds."""
    if len(rom) < 0x200:
        raise RomError("file too small to be an NDS ROM")
    header = {
        "title": rom[0:12].split(b"\x00")[0].decode("ascii", "replace"),
        "gamecode": rom[12:16].decode("ascii", "replace"),
        "makercode": rom[16:18].decode("ascii", "replace"),
        "unit_code": rom[0x12],
        "arm9_offset": u32(rom, 0x20),
        "arm9_entry": u32(rom, 0x24),
        "arm9_load": u32(rom, 0x28),
        "arm9_size": u32(rom, 0x2C),
        "arm7_offset": u32(rom, 0x30),
        "arm7_entry": u32(rom, 0x34),
        "arm7_load": u32(rom, 0x38),
        "arm7_size": u32(rom, 0x3C),
        "fnt_offset": u32(rom, 0x40),
        "fnt_size": u32(rom, 0x44),
        "fat_offset": u32(rom, 0x48),
        "fat_size": u32(rom, 0x4C),
        "ovt9_offset": u32(rom, 0x50),
        "ovt9_size": u32(rom, 0x54),
        "ovt7_offset": u32(rom, 0x58),
        "ovt7_size": u32(rom, 0x5C),
        "banner_offset": u32(rom, 0x68),
        "total_used_size": u32(rom, 0x80),
        "header_size": u32(rom, 0x84),
        "header_crc": u16(rom, 0x15E),
    }
    if header["header_size"] < 0x200 or header["header_size"] > len(rom):
        raise RomError(f"implausible header size {header['header_size']:#x}")
    return header


def banner_size(rom, banner_offset):
    """Returns the banner region's size, validated with the banner CRC on v1."""
    if banner_offset == 0 or banner_offset + 4 > len(rom):
        return 0
    version = u16(rom, banner_offset)
    size = BANNER_SIZES.get(version)
    if size is None:
        raise RomError(f"unknown banner version {version} at {banner_offset:#x}")
    if banner_offset + size > len(rom):
        raise RomError("banner extends past the end of the file")
    if version == 1:
        stored = u16(rom, banner_offset + 2)
        computed = crc16(rom[banner_offset + 0x20:banner_offset + 0x840])
        if stored != computed:
            print(f"warning: banner CRC-16 mismatch (stored {stored:#06x}, "
                  f"computed {computed:#06x}); keeping v1 size {size:#x}",
                  file=sys.stderr)
    return size


def parse_fnt(fnt):
    """Returns (paths by file id, directory count) from the file name table."""
    if len(fnt) < FNT_MAIN_ENTRY_SIZE:
        raise RomError("FNT too small")
    dir_count = u16(fnt, 6)
    if dir_count * FNT_MAIN_ENTRY_SIZE > len(fnt):
        raise RomError("FNT directory count exceeds the FNT size")
    dirs = []
    for d in range(dir_count):
        base = d * FNT_MAIN_ENTRY_SIZE
        dirs.append((u32(fnt, base), u16(fnt, base + 4)))
    paths = {}
    visited = set()
    stack = [(0, "")]
    while stack:
        d, prefix = stack.pop()
        if d in visited:
            continue
        visited.add(d)
        name_off, first_id = dirs[d]
        pos, file_id = name_off, first_id
        while pos < len(fnt):
            length = fnt[pos]
            pos += 1
            if length == 0:
                break
            name_len = length & 0x7F
            raw = fnt[pos:pos + name_len]
            pos += name_len
            name = raw.decode("shift-jis", errors="replace")
            if length & 0x80:
                if pos + 2 > len(fnt):
                    break
                # Directory ids are stored as 0xF000 | index
                child = u16(fnt, pos) & 0x0FFF
                pos += 2
                if child < dir_count:
                    stack.append((child, prefix + name + "/"))
            else:
                paths[file_id] = prefix + name
                file_id += 1
    return paths, dir_count


def parse_overlays(y9):
    """Returns one dict per 32-byte overlay table entry."""
    entries = []
    for base in range(0, len(y9) - OVERLAY_ENTRY_SIZE + 1, OVERLAY_ENTRY_SIZE):
        raw = u32(y9, base + 0x1C)
        entries.append({
            "id": u32(y9, base),
            "ram_addr": u32(y9, base + 4),
            "size": u32(y9, base + 8),
            "bss_size": u32(y9, base + 0x0C),
            "static_init_start": u32(y9, base + 0x10),
            "static_init_end": u32(y9, base + 0x14),
            "file_id": u32(y9, base + 0x18),
            "compressed_size": raw & 0xFFFFFF,
            "flags": raw >> 24,
        })
    return entries


def fat_entries(rom, header):
    """Returns [(file id, start, end)] from the FAT, bounds-checked."""
    off, size = header["fat_offset"], header["fat_size"]
    if off + size > len(rom):
        raise RomError("FAT extends past the end of the file")
    entries = []
    for file_id in range(size // FAT_ENTRY_SIZE):
        start = u32(rom, off + file_id * FAT_ENTRY_SIZE)
        end = u32(rom, off + file_id * FAT_ENTRY_SIZE + 4)
        if start > end or end > len(rom):
            raise RomError(f"FAT entry {file_id} has a bad range "
                           f"[{start:#x}, {end:#x})")
        entries.append((file_id, start, end))
    return entries


def build_regions(rom, header):
    """Returns every modelled region: (name, offset, size) in ROM order.

    A region is extracted verbatim and written back verbatim on build.  Bytes
    outside every region are handled by the padding assumption (0xFF fill) and
    the residue pass, so a region that models too little only moves bytes into
    residue; modelling too much is caught by the overlap check at build time.
    """
    regions = [("header", 0, header["header_size"])]
    for name, off_key, size_key in (
            ("arm9", "arm9_offset", "arm9_size"),
            ("arm7", "arm7_offset", "arm7_size"),
            ("y9", "ovt9_offset", "ovt9_size"),
            ("y7", "ovt7_offset", "ovt7_size"),
            ("fnt", "fnt_offset", "fnt_size"),
            ("fat", "fat_offset", "fat_size")):
        offset, size = header[off_key], header[size_key]
        if size:
            regions.append((name, offset, size))
    bsize = banner_size(rom, header["banner_offset"])
    if bsize:
        regions.append(("banner", header["banner_offset"], bsize))
    for file_id, start, end in fat_entries(rom, header):
        if end > start:
            regions.append((f"file {file_id}", start, end - start))
    for name, offset, size in regions:
        if offset + size > len(rom):
            raise RomError(f"region {name} [{offset:#x}, {offset + size:#x}) "
                           f"extends past the end of the file")
    return regions


def region_file(name):
    """Returns the file a region is stored in, under the extract directory."""
    return name if not name.startswith("file ") else f"files/{int(name[5:]):04d}.bin"


def compute_residue(rom, regions):
    """Returns (runs, residue bytes): gaps between regions that aren't 0xFF.

    A gap that is entirely the padding byte needs no storage -- build fills
    with 0xFF -- so residue.bin only holds runs with real content, typically
    alignment filler and the odd checksum block.
    """
    covered = sorted((off, off + size) for _, off, size in regions)
    merged = []
    for start, end in covered:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    runs, residue = [], bytearray()
    cursor = 0
    for start, end in merged:
        if cursor < start:
            gap = rom[cursor:start]
            if gap.count(PAD_BYTE) != len(gap):
                runs.append({"offset": cursor, "size": len(gap),
                             "position": len(residue)})
                residue += gap
        cursor = max(cursor, end)
    if cursor < len(rom):
        gap = rom[cursor:]
        if gap.count(PAD_BYTE) != len(gap):
            runs.append({"offset": cursor, "size": len(gap),
                         "position": len(residue)})
            residue += gap
    return runs, bytes(residue)


def rebuild(manifest, root):
    """Rebuilds the ROM image in memory from an extract directory."""
    total = manifest["total_size"]
    out = bytearray([PAD_BYTE]) * total
    residue = (root / "residue.bin").read_bytes() if manifest["residue"] else b""
    for run in manifest["residue"]:
        chunk = residue[run["position"]:run["position"] + run["size"]]
        if len(chunk) != run["size"]:
            raise RomError("residue.bin is shorter than the manifest says")
        out[run["offset"]:run["offset"] + run["size"]] = chunk
    ordered = sorted(manifest["regions"], key=lambda r: r["offset"])
    loaded = []
    for region in ordered:
        path = root / region["path"]
        size = region["size"]
        if size == 0:
            data = b""
        else:
            data = path.read_bytes()
            if len(data) != size:
                raise RomError(f"{region['path']}: expected {size} bytes, "
                               f"found {len(data)}; the file was modified "
                               f"or the manifest is stale")
        loaded.append((region["name"], region["offset"], data))
    # Overlap sweep over the actual bytes about to be written
    active = []  # (end, index)
    for i, (name, offset, data) in enumerate(loaded):
        end = offset + len(data)
        while active and active[0][0] <= offset:
            heapq.heappop(active)
        for _, j in active:
            other_name, other_offset, other_data = loaded[j]
            ov_start, ov_end = offset, min(end, other_offset + len(other_data))
            if (data[ov_start - offset:ov_end - offset]
                    != other_data[ov_start - other_offset:ov_end - other_offset]):
                raise RomError(
                    f"regions {other_name!r} and {name!r} overlap at "
                    f"[{ov_start:#x}, {ov_end:#x}) with different bytes")
        heapq.heappush(active, (end, i))
    for name, offset, data in loaded:
        out[offset:offset + len(data)] = data
    return bytes(out)


# ---------------------------------------------------------------------------


def cmd_info(args):
    rom = Path(args.rom).read_bytes()
    header = parse_header(rom)
    fnt = rom[header["fnt_offset"]:header["fnt_offset"] + header["fnt_size"]]
    paths, dir_count = parse_fnt(fnt)
    entries = fat_entries(rom, header)
    y9 = rom[header["ovt9_offset"]:header["ovt9_offset"] + header["ovt9_size"]]
    overlays = parse_overlays(y9) if header["ovt9_size"] else []
    banner_off = header["banner_offset"]
    bsize = banner_size(rom, banner_off) if banner_off else 0

    print(f"{args.rom}")
    print(f"  size {len(rom):#x} ({len(rom) / (1 << 20):.1f} MiB), "
          f"used {header['total_used_size']:#x}, sha1 {sha1_of(rom)}")
    stored = header["header_crc"]
    computed = crc16(rom[:0x15E])
    verdict = "ok" if stored == computed else f"MISMATCH (computed {computed:#06x})"
    print(f"  title {header['title']!r}  gamecode {header['gamecode']}  "
          f"maker {header['makercode']}  unit {header['unit_code']:#04x}")
    print(f"  header size {header['header_size']:#x}, header CRC-16 {verdict}")
    print(f"  arm9 {header['arm9_offset']:#x} load {header['arm9_load']:#010x} "
          f"entry {header['arm9_entry']:#010x} size {header['arm9_size']:#x}")
    print(f"  arm7 {header['arm7_offset']:#x} load {header['arm7_load']:#010x} "
          f"entry {header['arm7_entry']:#010x} size {header['arm7_size']:#x}")
    print(f"  y9   {header['ovt9_offset']:#x} size {header['ovt9_size']:#x} "
          f"({len(overlays)} arm9 overlays)"
          + (f"\n  y7   {header['ovt7_offset']:#x} size {header['ovt7_size']:#x}"
             if header["ovt7_size"] else ", no arm7 overlays"))
    print(f"  fnt  {header['fnt_offset']:#x} size {header['fnt_size']:#x} "
          f"({dir_count} directories, {len(paths)} named files)")
    print(f"  fat  {header['fat_offset']:#x} size {header['fat_size']:#x} "
          f"({len(entries)} entries, "
          f"{sum(e - s for _, s, e in entries):#x} bytes of files)")
    if bsize:
        jp = rom[banner_off + 0x240:banner_off + 0x340]
        title = jp.decode("utf-16-le", errors="replace").split("\x00")[0]
        print(f"  banner {banner_off:#x} version {u16(rom, banner_off)} "
              f"size {bsize:#x}, title {title!r}")
    top = sorted({p.split("/", 1)[0] for p in paths.values() if "/" in p})
    if top:
        print(f"  top-level directories: {', '.join(top[:12])}"
              + (f", ... ({len(top)} total)" if len(top) > 12 else ""))
    biggest = sorted(entries, key=lambda e: e[2] - e[1], reverse=True)[:5]
    print("  largest files: " + ", ".join(
        f"#{fid} ({end - start:#x} bytes)" for fid, start, end in biggest))
    return 0


def cmd_extract(args):
    rom = Path(args.rom).read_bytes()
    out = Path(args.out)
    if (out / "manifest.json").exists() and not args.force:
        raise RomError(f"{out}/manifest.json already exists; pass --force to "
                       f"re-extract over it")
    out.mkdir(parents=True, exist_ok=True)
    (out / "files").mkdir(exist_ok=True)
    header = parse_header(rom)
    if header["gamecode"].encode() != EXPECTED_GAMECODE:
        print(f"warning: gamecode {header['gamecode']!r} is not the expected "
              f"{EXPECTED_GAMECODE.decode()!r}; extracting anyway",
              file=sys.stderr)

    regions = build_regions(rom, header)
    fnt = rom[header["fnt_offset"]:header["fnt_offset"] + header["fnt_size"]]
    paths, dir_count = parse_fnt(fnt)

    manifest_regions = []
    for name, offset, size in regions:
        path = region_file(name)
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(rom[offset:offset + size])
        record = {"name": name, "offset": offset, "size": size, "path": path}
        if name.startswith("file "):
            record["file_id"] = int(name[5:])
        manifest_regions.append(record)
    residue_runs, residue = compute_residue(rom, regions)
    if residue:
        (out / "residue.bin").write_bytes(residue)

    # Human-readable sidecars; not read back by build
    with open(out / "files.tsv", "w", encoding="utf-8") as tsv:
        tsv.write("file_id\toffset\tsize\tpath\n")
        for file_id, start, end in fat_entries(rom, header):
            path = paths.get(file_id, "")
            path = "".join(c if c >= " " and c != "\x7f" else "?"
                           for c in path).replace("\t", " ")
            tsv.write(f"{file_id}\t{start:#010x}\t{end - start:#x}\t{path}\n")
    y9 = rom[header["ovt9_offset"]:header["ovt9_offset"] + header["ovt9_size"]]
    if header["ovt9_size"]:
        with open(out / "overlays.tsv", "w", encoding="utf-8") as tsv:
            tsv.write("id\tram_addr\tsize\tbss\tstatic_init_start\t"
                      "static_init_end\tfile_id\tcompressed_size\tflags\n")
            for ov in parse_overlays(y9):
                tsv.write(f"{ov['id']}\t{ov['ram_addr']:#010x}\t{ov['size']:#x}\t"
                          f"{ov['bss_size']:#x}\t{ov['static_init_start']:#010x}\t"
                          f"{ov['static_init_end']:#010x}\t{ov['file_id']}\t"
                          f"{ov['compressed_size']:#x}\t{ov['flags']:#04x}\n")

    manifest = {
        "format": MANIFEST_FORMAT,
        "source": {"name": Path(args.rom).name, "size": len(rom),
                   "sha1": sha1_of(rom)},
        "header": header,
        "total_size": len(rom),
        "regions": sorted(manifest_regions, key=lambda r: r["offset"]),
        "residue": residue_runs,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    image = rebuild(manifest, out)
    if image == rom:
        print(f"extracted {len(regions)} regions, "
              f"{len(residue_runs)} residue runs ({len(residue)} bytes) to {out}")
        print(f"immediate rebuild check: byte-identical, sha1 {sha1_of(image)}")
        return 0
    diff = next(i for i, (a, b) in enumerate(zip(image, rom)) if a != b)
    raise RomError(f"immediate rebuild check FAILED, first difference at "
                   f"{diff:#x}; the region model is wrong, do not trust {out}")


def cmd_build(args):
    root = Path(args.extract)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != MANIFEST_FORMAT:
        raise RomError(f"{root}/manifest.json: unknown format "
                       f"{manifest.get('format')!r}")
    image = rebuild(manifest, root)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(image)
    print(f"built {out} ({len(image):#x} bytes), sha1 {sha1_of(image)}")
    expected = manifest["source"]["sha1"]
    if sha1_of(image) == expected:
        print("matches the source ROM")
        return 0
    print(f"differs from the source ROM (expected sha1 {expected}); expected "
          f"if any region was replaced by rebuilt output")
    return 1


def cmd_verify(args):
    root = Path(args.extract)
    rom = Path(args.rom).read_bytes()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    image = rebuild(manifest, root)
    if image == rom:
        print(f"verify: {root} rebuilds byte-identically to {args.rom}")
        print(f"sha1 {sha1_of(image)}")
        return 0
    mismatch = next(i for i, (a, b) in enumerate(zip(image, rom)) if a != b)
    print(f"verify: FAILED, first difference at {mismatch:#x} "
          f"({image[mismatch]:#04x} built vs {rom[mismatch]:#04x} original)")
    print(f"built sha1 {sha1_of(image)}, original sha1 {sha1_of(rom)}")
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ndsrom.py",
        description="unpack, rebuild and verify a Nintendo DS ROM, "
                    "byte-exactly")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("info", help="print what the cartridge contains")
    p.add_argument("rom")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("extract", help="unpack a ROM into a buildable directory")
    p.add_argument("rom")
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--force", action="store_true",
                   help="extract even if the output already has a manifest")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("build", help="rebuild the ROM from an extract directory")
    p.add_argument("extract")
    p.add_argument("-o", "--output", required=True)
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("verify", help="rebuild and compare against the original")
    p.add_argument("extract")
    p.add_argument("rom")
    p.set_defaults(func=cmd_verify)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except RomError as error:
        print(f"ndsrom.py: error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
