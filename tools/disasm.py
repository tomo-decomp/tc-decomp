#!/usr/bin/env python3
"""
disasm.py -- first-pass disassembler for Tomodachi Collection's ARM9 code.

Milestone 2 tool. Requires capstone (`pip install capstone`). Stdlib otherwise.

Given the extracted ARM9 main or one of the 111 overlays, it:

  1. discovers function entry points by scanning for branch-with-link
     targets (ARM `bl`, Thumb `bl`/`blx`), seeding from the known entry
     points (ARM9 entry 0x800, each overlay's RAM load address);
  2. disassembles linearly from each start until a return instruction or
     cartridge padding, whichever comes first;
  3. writes a GNU-as-style listing to build/disasm/<target>.s plus a
     function table <target>.funcs.tsv.

This is a *linear sweep*, not a recursive-descent decompiler: data embedded
in code and overlapping functions will be mislabelled in places. The point
is to get addressable listings for manual analysis, exactly like the early
days of any matching decomp.

Usage:
    python3 tools/disasm.py arm9
    python3 tools/disasm.py overlay 12
    python3 tools/disasm.py overlay --all
    python3 tools/disasm.py arm9 --out build/disasm
"""

import argparse
import csv
import json
import struct
import sys
from pathlib import Path

try:
    from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM, CS_MODE_THUMB
except ImportError:
    sys.exit("disasm.py needs capstone: pip install capstone")

ROOT = Path(__file__).parent.parent.resolve()
MANIFEST = ROOT / "extract" / "manifest.json"

ARM9_LOAD = 0x02000000
ARM9_ENTRY = 0x02000800


def load_manifest():
    if not MANIFEST.exists():
        sys.exit("extract/manifest.json not found; run ndsrom.py extract first")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def arm9_bytes():
    path = ROOT / "extract" / "arm9"
    return path.read_bytes()


def overlay_bytes(file_id):
    path = ROOT / "extract" / "files" / f"{file_id:04d}.bin"
    return path.read_bytes()


def overlays(manifest):
    """Returns the parsed y9 entries from the extract manifest."""
    header = manifest["header"]
    y9 = (ROOT / "extract" / "y9").read_bytes()
    entries = []
    for base in range(0, len(y9), 32):
        raw = struct.unpack_from("<I", y9, base + 0x1C)[0]
        entries.append({
            "id": struct.unpack_from("<I", y9, base)[0],
            "ram_addr": struct.unpack_from("<I", y9, base + 4)[0],
            "size": struct.unpack_from("<I", y9, base + 8)[0],
            "bss_size": struct.unpack_from("<I", y9, base + 0x0C)[0],
            "file_id": struct.unpack_from("<I", y9, base + 0x18)[0],
            "compressed_size": raw & 0xFFFFFF,
            "flags": raw >> 24,
        })
    del header
    return entries


# ---------------------------------------------------------------------------


def scan_arm_bl_targets(data, base):
    """ARM-state B/BL targets: cond 101 L imm24."""
    targets = set()
    for off in range(0, len(data) - 3, 4):
        word = struct.unpack_from("<I", data, off)[0]
        if (word >> 25) == 0b101:  # B or BL (any condition)
            imm = word & 0xFFFFFF
            if imm & 0x800000:
                imm -= 0x1000000
            targets.add(base + off + 8 + (imm << 2))
    return targets


def scan_thumb_bl_targets(data, base):
    """Thumb BL/BLX imm pairs: F000.. / F800.. (BL) or E800.. (BLX)."""
    targets = set()
    hw = memoryview(data)
    for off in range(0, len(data) - 3, 2):
        first = struct.unpack_from("<H", hw, off)[0]
        second = struct.unpack_from("<H", hw, off + 2)[0]
        if first & 0xF800 != 0xF000 or second & 0xE800 != 0xF800:
            continue
        imm = ((first & 0x7FF) << 12) | ((second & 0x7FF) << 1)
        if imm & 0x400000:
            imm -= 0x800000
        targets.add(base + off + 4 + imm)
    return targets


def discover_functions(data, base, entry_points):
    """Returns a sorted set of function starts: entries plus branch targets."""
    starts = set(a for a in entry_points if base <= a < base + len(data))
    starts |= scan_arm_bl_targets(data, base)
    starts |= scan_thumb_bl_targets(data, base)
    return sorted(a for a in starts if base <= a < base + len(data))


def disassemble(data, base, functions):
    """Linear-sweeps each function; returns (lines, rows) for the listing."""
    md_arm = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    md_thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    lines = []
    rows = []
    for start in functions:
        off = start - base
        chunk = data[off:off + 0x10000]
        # Thumb entry points have bit 0 set in their branch destination
        thumb = bool(start & 1)
        addr = start & ~1
        md = md_thumb if thumb else md_arm
        lines.append("")
        lines.append(f"arm_func start={start:#010x}" if not thumb
                     else f"thumb_func start={start:#010x}")
        ended = False
        for insn in md.disasm(chunk, addr):
            lines.append(f"    {insn.address:08x}:  {insn.mnemonic:8s} {insn.op_str}")
            if insn.mnemonic == "bx" and insn.op_str == "lr":
                ended = True
                break
            if insn.mnemonic == "mov" and insn.op_str.startswith("pc,"):
                ended = True
                break
            if insn.mnemonic == "pop" and "pc" in insn.op_str:
                ended = True
                break
        rows.append({"start": f"{start:#010x}",
                     "state": "thumb" if thumb else "arm",
                     "ended": "yes" if ended else "fell-through"})
    return lines, rows


def write_listing(name, lines, rows, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    listing = out_dir / f"{name}.s"
    header = [f"; Tomodachi Collection ({name}) first-pass disassembly",
              f"; generated by tools/disasm.py -- do not edit, do not commit",
              ""]
    listing.write_text("\n".join(header + lines) + "\n", encoding="utf-8")
    with open(out_dir / f"{name}.funcs.tsv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["start", "state", "ended"],
                                delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    return listing, len(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="disasm.py",
                                     description="first-pass ARM disassembly")
    parser.add_argument("target", choices=["arm9", "overlay"])
    parser.add_argument("id", nargs="?", type=int,
                        help="overlay id (0..110)")
    parser.add_argument("--all", action="store_true",
                        help="disassemble every overlay")
    parser.add_argument("--out", default=str(ROOT / "build" / "disasm"))
    args = parser.parse_args(argv)

    manifest = load_manifest()
    out_dir = Path(args.out)

    if args.target == "arm9":
        data = arm9_bytes()
        functions = discover_functions(data, ARM9_LOAD, {ARM9_ENTRY})
        lines, rows = disassemble(data, ARM9_LOAD, functions)
        listing, count = write_listing("arm9", lines, rows, out_dir)
        print(f"arm9: {count} function starts, listing {listing}")
        return 0

    ov_list = overlays(manifest)
    if args.all:
        chosen = ov_list
    elif args.id is not None:
        chosen = [o for o in ov_list if o["id"] == args.id]
        if not chosen:
            sys.exit(f"no overlay with id {args.id} (ids 0..{ov_list[-1]['id']})")
    else:
        parser.error("overlay needs an id or --all")

    for ov in chosen:
        data = overlay_bytes(ov["file_id"])
        if len(data) != ov["size"]:
            print(f"warning: overlay {ov['id']} file {ov['file_id']} is "
                  f"{len(data):#x} bytes, table says {ov['size']:#x}",
                  file=sys.stderr)
        base = ov["ram_addr"]
        functions = discover_functions(data, base, {base})
        lines, rows = disassemble(data, base, functions)
        listing, count = write_listing(f"ov{ov['id']:03d}", lines, rows, out_dir)
        print(f"overlay {ov['id']:3d} ({ov['size']:#08x} @ {base:#010x}): "
              f"{count} function starts -> {listing.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
