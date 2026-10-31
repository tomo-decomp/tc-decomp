#!/usr/bin/env python3
"""
match.py -- matching-decompilation harness for Tomodachi Collection.

Compiles a C source file with the project's CodeWarrior (mwccarm) compiler
under wine and compares the resulting `.text` byte-for-byte with the original
function bytes at the address it claims, the way a matching decomp project
does.

Source layout convention
------------------------
    src/arm9/func_02000abc.c     -> ARM9 main, address 0x02000abc
    src/ov000/func_02149a40.c    -> overlay 0, address 0x02149a40

The file name gives the address; the parent directory gives the target.
Each file defines exactly one function, named after its address, e.g.

    void func_02149a40(void) { }

Compiled objects go to build/match/, so a failure never leaves stale output.

Usage
-----
    python3 tools/match.py build                 # compile + compare everything
    python3 tools/match.py build --verbose       # with disassembly on failure
    python3 tools/match.py src/ov000/func_02149a40.c
    python3 tools/match.py build --compiler 2.0/sp2p2
"""

import argparse
import json
import os
import re
import shlex
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
TOOLS = ROOT / "tools"
MWCC_DIR = TOOLS / "mwccarm"
BUILD = ROOT / "build" / "match"
EXTRACT = ROOT / "extract"

DEFAULT_COMPILER = "2.0/sp2"
DEFAULT_FLAGS = [
    "-O4,p",            # optimize for speed
    "-proc arm946e",    # ARM9
    "-interworking",    # ARM/Thumb interworking
    "-enum int",        # enums are int-sized
    "-char signed",     # char is signed
    "-fp soft",         # software floating point
    "-lang=c99",
    "-Cpp_exceptions off",
    "-gccext,on",
    "-gccinc",
    "-i include",
    "-inline on,noauto",
    "-ipa file",
    "-sym on",          # keep debug info (does not change .text)
    "-requireprotos",
    "-nolink",
    "-msgstyle gcc",
]

SOURCE_RE = re.compile(r"^func_([0-9a-f]{8})\.c$")


def find_mwcc(compiler: str) -> Path:
    path = MWCC_DIR / compiler / "mwccarm.exe"
    if not path.exists():
        available = sorted(p.parent.relative_to(MWCC_DIR).as_posix()
                           for p in MWCC_DIR.glob("*/*/mwccarm.exe"))
        sys.exit(f"no mwccarm at tools/mwccarm/{compiler}/mwccarm.exe\n"
                 f"available: {', '.join(available)}")
    return path


def elf_section(data, wanted):
    """Returns (offset, size) of a named section in an ELF32 little-endian object."""
    if data[:4] != b"\x7fELF":
        raise ValueError("not an ELF object")
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x2E)[0]
    e_shnum = struct.unpack_from("<H", data, 0x30)[0]
    e_shstrndx = struct.unpack_from("<H", data, 0x32)[0]
    str_off = e_shoff + e_shstrndx * e_shentsize
    _, _, _, _, str_off, str_size = struct.unpack_from("<IIIIII", data, str_off)
    strtab = data[str_off:str_off + str_size]
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name_off, _, _, _, sh_off, sh_size = struct.unpack_from("<IIIIII", data, off)
        name = strtab[name_off:strtab.find(b"\0", name_off)].decode("ascii", "replace")
        if name == wanted:
            return sh_off, sh_size
    raise ValueError(f"no {wanted} section")


def elf_symbols(data):
    """Returns {name: (value, size)} from .symtab."""
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x2E)[0]
    e_shnum = struct.unpack_from("<H", data, 0x30)[0]
    e_shstrndx = struct.unpack_from("<H", data, 0x32)[0]
    str_off = e_shoff + e_shstrndx * e_shentsize
    _, _, _, _, shstr_off, shstr_size = struct.unpack_from("<IIIIII", data, str_off)
    shstr = data[shstr_off:shstr_off + shstr_size]
    symtab = None
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name_off = struct.unpack_from("<I", data, off)[0]
        name = shstr[name_off:shstr.find(b"\0", name_off)].decode("ascii", "replace")
        if name == ".symtab":
            _, _, _, _, sym_off, sym_size, link = struct.unpack_from("<IIIIIII", data, off)
            symtab = (sym_off, sym_size, link)
    if not symtab:
        return {}
    sym_off, sym_size, link = symtab
    _, _, _, _, str_off, str_size = struct.unpack_from("<IIIIII", data,
                                                       e_shoff + link * e_shentsize)
    strtab = data[str_off:str_off + str_size]
    symbols = {}
    for off in range(sym_off, sym_off + sym_size, 16):
        name_off, value, size, info, other, shndx = struct.unpack_from("<IIIBBH", data, off)
        name = strtab[name_off:strtab.find(b"\0", name_off)].decode("ascii", "replace")
        if name:
            symbols[name] = (value, size, shndx)
    return symbols


def elf_symtab(data):
    """Returns the symbol table as [(name, value, size, shndx)]."""
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x2E)[0]
    e_shnum = struct.unpack_from("<H", data, 0x30)[0]
    e_shstrndx = struct.unpack_from("<H", data, 0x32)[0]
    _, _, _, _, shstr_off, shstr_size = struct.unpack_from(
        "<IIIIII", data, e_shoff + e_shstrndx * e_shentsize)
    shstr = data[shstr_off:shstr_off + shstr_size]
    symtab = None
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name_off = struct.unpack_from("<I", data, off)[0]
        name = shstr[name_off:shstr.find(b"\0", name_off)].decode("ascii", "replace")
        if name == ".symtab":
            _, _, _, _, sym_off, sym_size, link = struct.unpack_from("<IIIIIII", data, off)
            symtab = (sym_off, sym_size, link)
    if not symtab:
        return []
    sym_off, sym_size, link = symtab
    _, _, _, _, str_off, str_size = struct.unpack_from("<IIIIII", data,
                                                       e_shoff + link * e_shentsize)
    strtab = data[str_off:str_off + str_size]
    symbols = []
    for off in range(sym_off, sym_off + sym_size, 16):
        name_off, value, size, info, other, shndx = struct.unpack_from("<IIIBBH", data, off)
        name = strtab[name_off:strtab.find(b"\0", name_off)].decode("ascii", "replace")
        symbols.append((name, value, size, shndx))
    return symbols


# relocations a single-function object can legitimately contain, for ARM
ARM_PC_RELOCS = {1: "R_ARM_PC24", 28: "R_ARM_CALL", 29: "R_ARM_JUMP24"}
ARM_ABS_RELOCS = {2: "R_ARM_ABS32"}


def elf_text_relocs(data):
    """Returns [(offset, symbol name, type, addend)] for relocations against
    .text. MWCC emits SHT_RELA (type 4) on ARM."""
    e_shoff = struct.unpack_from("<I", data, 0x20)[0]
    e_shentsize = struct.unpack_from("<H", data, 0x2E)[0]
    e_shnum = struct.unpack_from("<H", data, 0x30)[0]
    symbols = elf_symtab(data)
    # find the .text section index so relocations can be matched to it
    e_shstrndx = struct.unpack_from("<H", data, 0x32)[0]
    _, _, _, _, so, ss = struct.unpack_from(
        "<IIIIII", data, e_shoff + e_shstrndx * e_shentsize)
    shstr = data[so:so + ss]
    text_index = None
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        name_off = struct.unpack_from("<I", data, off)[0]
        if shstr[name_off:shstr.find(b"\0", name_off)] == b".text":
            text_index = i
    relocs = []
    for i in range(e_shnum):
        off = e_shoff + i * e_shentsize
        _, sh_type, _, _, sh_off, sh_size, sh_link, sh_info = struct.unpack_from(
            "<IIIIIIII", data, off)
        if sh_type not in (4, 9) or sh_info != text_index:
            continue
        stride = 12 if sh_type == 4 else 8
        for entry in range(sh_off, sh_off + sh_size, stride):
            r_offset, r_info = struct.unpack_from("<II", data, entry)
            addend = struct.unpack_from("<i", data, entry + 8)[0] if stride == 12 else 0
            sym = r_info >> 8
            rtype = r_info & 0xFF
            name = symbols[sym][0] if sym < len(symbols) else ""
            relocs.append((r_offset, name, rtype, addend))
    return relocs


SYMBOL_ADDRESS_RE = re.compile(r"^(?:func|data|unk)_([0-9a-fA-F]{8})$")


def symbol_address(name: str):
    """Resolves a project symbol name such as func_02009978 to its address."""
    match = SYMBOL_ADDRESS_RE.match(name)
    if not match:
        return None
    return int(match.group(1), 16)


def apply_relocations(text: bytes, text_address: int, relocs):
    """Patches a compiled .text the way the linker would, using the symbol
    name's encoded address. Returns (patched bytes, unresolved list)."""
    buf = bytearray(text)
    unresolved = []
    for offset, name, rtype, addend in relocs:
        if offset + 4 > len(buf):
            unresolved.append((offset, name, rtype, "offset outside .text"))
            continue
        base = symbol_address(name)
        if base is None:
            unresolved.append((offset, name, rtype, "unknown symbol"))
            continue
        target = base + addend
        if rtype in ARM_PC_RELOCS:
            # the RELA addend already holds the ARM pc bias (-8)
            word = struct.unpack_from("<I", buf, offset)[0]
            immediate = ((target - (text_address + offset)) >> 2) & 0xFFFFFF
            struct.pack_into("<I", buf, offset, (word & 0xFF000000) | immediate)
        elif rtype in ARM_ABS_RELOCS:
            struct.pack_into("<I", buf, offset, target)
        else:
            unresolved.append((offset, name, rtype, "unsupported relocation"))
    return bytes(buf), unresolved


def original_bytes(target, address, size):
    """Returns the original bytes of a function range from the extract."""
    if target == "arm9":
        data = (EXTRACT / "arm9").read_bytes()
        base = 0x02000000
    else:
        match = re.fullmatch(r"ov(\d{3})", target)
        if not match:
            raise ValueError(f"bad target {target!r}")
        ov_id = int(match.group(1))
        data = (EXTRACT / "files" / f"{ov_id:04d}.bin").read_bytes()
        base = 0x02149A40
    off = address - base
    if off < 0 or off + size > len(data):
        raise ValueError(f"{target}: {address:#010x} outside the image")
    return data[off:off + size], base


def compile_source(source: Path, compiler: str, flags: list[str]) -> bytes:
    """Compiles one source file and returns the raw .o bytes."""
    BUILD.mkdir(parents=True, exist_ok=True)
    source = source.resolve()
    rel = source.relative_to(ROOT)
    obj = BUILD / rel.with_suffix(".o")
    obj.parent.mkdir(parents=True, exist_ok=True)
    if obj.exists():
        obj.unlink()
    mwcc = find_mwcc(compiler)
    # wine does not translate Unix absolute paths, so keep everything
    # relative to the project root and run from there
    tokens = [token for flag in flags for token in shlex.split(flag)]
    command = ["wine", mwcc.relative_to(ROOT).as_posix(), *tokens,
               "-c", rel.as_posix(), "-o", obj.relative_to(ROOT).as_posix()]
    env = dict(os.environ, WINEDEBUG="-all")
    proc = subprocess.run(command, capture_output=True, text=True, env=env,
                          cwd=ROOT, timeout=120)
    if proc.returncode != 0 or not obj.exists():
        raise RuntimeError(f"mwccarm failed for {rel}:\n{proc.stdout}\n{proc.stderr}")
    return obj.read_bytes()


def disassemble_text(text: bytes, address: int):
    try:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_ARM
    except ImportError:
        return ["  (install capstone for disassembly)"]
    md = Cs(CS_ARCH_ARM, CS_MODE_ARM)
    lines = []
    for insn in md.disasm(text, address):
        lines.append(f"  {insn.address:08x}: {insn.bytes.hex():8s} "
                     f"{insn.mnemonic:8s} {insn.op_str}")
    return lines


def compare_one(source: Path, compiler: str, flags: list[str], verbose: bool):
    """Compiles and compares one source file. Returns a result dict."""
    source = source.resolve()
    name = source.name
    match = SOURCE_RE.match(name)
    if not match:
        return {"source": str(source), "status": "skip",
                "reason": "file name is not func_XXXXXXXX.c"}
    address = int(match.group(1), 16)
    target = source.parent.name
    result = {"source": str(source.relative_to(ROOT)), "target": target,
              "address": f"{address:#010x}"}
    try:
        obj = compile_source(source, compiler, flags)
        text_off, text_size = elf_section(obj, ".text")
        compiled = obj[text_off:text_off + text_size]
        symbols = elf_symbols(obj)
        func_name = f"func_{address:08x}"
        if func_name not in symbols:
            result.update(status="error",
                          reason=f"object has no symbol {func_name}")
            return result
        relocs = elf_text_relocs(obj)
        compiled, unresolved = apply_relocations(compiled, address, relocs)
        if unresolved:
            result.update(status="error", size=text_size,
                          reason="; ".join(
                              f"{ARM_PC_RELOCS.get(t, ARM_ABS_RELOCS.get(t, t))} "
                              f"at +{o:#x} -> {n or '<local>'} ({why})"
                              for o, n, t, why in unresolved))
            return result
        expected, _ = original_bytes(target, address, text_size)
        result.update(status="match" if compiled == expected else "mismatch",
                      size=text_size, compiled_sha=None)
        if compiled != expected:
            diff = next(i for i, (a, b) in enumerate(zip(compiled, expected)) if a != b)
            result["first_diff"] = f"{address + diff:#010x}"
            if verbose:
                print(f"\n--- {result['source']} ({target} {address:#010x}) ---")
                print("compiled:")
                print("\n".join(disassemble_text(compiled, address)))
                print("original:")
                print("\n".join(disassemble_text(expected, address)))
        return result
    except (RuntimeError, ValueError) as error:
        result.update(status="error", reason=str(error))
        return result


def iter_sources():
    for path in sorted((ROOT / "src").rglob("func_*.c")):
        yield path


def cmd_build(args):
    sources = list(iter_sources())
    if not sources:
        sys.exit("no sources under src/; nothing to match")
    total = matched = 0
    failures = []
    report = []
    for source in sources:
        result = compare_one(source, args.compiler, DEFAULT_FLAGS, args.verbose)
        report.append(result)
        if result["status"] == "match":
            matched += 1
            total += result["size"]
        else:
            failures.append(result)
        mark = {"match": "ok", "mismatch": "MISMATCH", "error": "ERROR",
                "skip": "skip"}[result["status"]]
        print(f"{mark:9s} {result['source']}")
    BUILD.mkdir(parents=True, exist_ok=True)
    (BUILD / "progress.json").write_text(
        json.dumps({"compiler": args.compiler, "matched": matched,
                    "total": len(sources), "results": report}, indent=2) + "\n",
        encoding="utf-8")
    print(f"\n{matched}/{len(sources)} functions match "
          f"({total:#x} matched code bytes)")
    if args.stamp:
        Path(args.stamp).parent.mkdir(parents=True, exist_ok=True)
        Path(args.stamp).write_text(f"{matched}/{len(sources)} matched\n",
                                    encoding="utf-8")
    return 0 if not failures else 1


def main(argv=None):
    parser = argparse.ArgumentParser(prog="match.py")
    parser.add_argument("--compiler", default=DEFAULT_COMPILER,
                        help="mwccarm version under tools/mwccarm "
                             f"(default {DEFAULT_COMPILER})")
    parser.add_argument("--verbose", action="store_true",
                        help="disassemble differences")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="compile and compare all sources")
    p.add_argument("--compiler", default=DEFAULT_COMPILER)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--stamp", help="write a stamp file for a meson custom target")
    p.set_defaults(func=cmd_build)
    p = sub.add_parser("file", help="compile and compare one source file")
    p.add_argument("source")
    p.add_argument("--compiler", default=DEFAULT_COMPILER)
    p.add_argument("--verbose", action="store_true")
    p.set_defaults(func=lambda a: _cmd_file(a, a.source))
    args = parser.parse_args(argv)
    return args.func(args)


def _cmd_file(args, source):
    result = compare_one(Path(source), args.compiler, DEFAULT_FLAGS,
                         args.verbose)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "match" else 1


if __name__ == "__main__":
    sys.exit(main())
