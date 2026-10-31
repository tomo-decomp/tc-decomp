# tomo_coll_decomp

A work-in-progress decompilation of **Tomodachi Collection** (Nintendo DS, Japan,
game code `CCUJ`), in the same spirit as the other projects under `dsdecomp/`.
The long-term goal is matching C source for the ARM9 program, and beyond that a
native PC port.

No copyrighted game data lives in this repository: you supply your own
legally obtained ROM dump, and the tools derive everything locally.

## Status

| Milestone | State |
|---|---|
| 1. ROM extraction and byte-identical rebuild | **done** |
| 2. Delinking, disassembly, byte-identical reassembly | **first pass done** (linear sweep, 219 ARM9 starts + all 111 overlays); recursion-descent and SDK split pending |
| 3. Decompilation to matching C (`src/`) | **in progress** (19 functions, `0x2a4` bytes) |
| 4. Data formats (archives, text, graphics) | not started |
| 5. Native PC port | not started |

Milestone 1 is verified: `extract -> build` reproduces the ROM bit for bit
(sha1 `f37d5ff0e3444cf3fab38890efb71f4f14c96994`).

## The cartridge

| | |
|---|---|
| Title | トモダチコレクション (Tomodachi Collection) |
| Game code | `CCUJ` (Nintendo, maker `01`) |
| Media | 64 MiB NTR cartridge (not DSi-enhanced) |
| ARM9 | load `0x02000000`, entry `0x02000800`, size `0xB52BC` |
| ARM7 | load `0x02380000`, entry `0x02380000`, size `0x270F0` |
| Overlays | 111 ARM9 overlays (y9), no ARM7 overlays |
| Filesystem | 2080 FAT entries (1969 named files in 31 directories, plus the 111 overlay files) |

See [docs/layout.md](docs/layout.md) for the full measured layout.

## Requirements

- Python 3.9+ (standard library only; the ROM tool has no dependencies)
- A legally obtained dump of Tomodachi Collection (Japan)

## Usage

```sh
# What does the cartridge contain?
python3 tools/ndsrom.py info path/to/tomo_collection_rev1.nds

# Unpack into a buildable directory
python3 tools/ndsrom.py extract path/to/tomo_collection_rev1.nds -o extract

# Rebuild and verify byte-for-byte against the original
python3 tools/ndsrom.py build extract -o build/tomo_collection_rev1.nds
python3 tools/ndsrom.py verify extract path/to/tomo_collection_rev1.nds
```

`extract/` also contains two human-readable sidecars:

- `files.tsv` — every FAT entry: id, ROM range, and filesystem path
- `overlays.tsv` — every y9 overlay entry: RAM address, sizes, static
  initialisers, backing file id

### Disassembly (milestone 2 first pass)

```sh
python3 tools/disasm.py arm9                    # ARM9 main
python3 tools/disasm.py overlay 12              # one overlay
python3 tools/disasm.py overlay --all           # every overlay
```

Listings and per-function tables land in `build/disasm/`. Notes and known
limitations: [docs/disassembly.md](docs/disassembly.md).

### Matching decompilation (milestone 3)

```sh
python3 tools/match.py build          # compile every src/ file, compare bytes
ninja -C build/meson check            # the same check through the build system
```

Each file under `src/` must compile with CodeWarrior for ARM back into the exact
original bytes. The workflow, source conventions and toolchain notes are in
[docs/decompilation.md](docs/decompilation.md).

The build scaffolding mirrors `pokeplatinum`/`pokeheartgold`: `meson.build` with
the same compiler flags, `meson/cross.ini` driving `tools/mwccarm` through wine,
and `subprojects/*.wrap` pinning NitroSDK, NitroSystem and libvct at the same
revisions those projects use:

```sh
meson setup build/meson
meson subprojects download            # fetch the pinned SDK sources
```

Those SDK dependencies are not configured into the build yet: compiling and
linking them needs the Metrowerks MSL standard library, which is not
redistributable, so the ROM-link target lands with the rest of milestone 3.
Today the harness is the authority on byte-exactness.

## Repository structure

- `tools/` — ROM extraction, rebuild, verification, disassembly and the
  matching harness (`match.py`)
- `src/` — decompiled C, one file per function, grouped by binary
  (`src/arm9/`, `src/ovNNN/`)
- `include/` — shared headers (currently the MSL stand-ins the compiler needs)
- `meson/`, `subprojects/` — build definition and the pinned NitroSDK,
  NitroSystem and libvct wraps, as in the other DS projects here
- `docs/` — technical notes, measured cartridge layout, disassembly findings,
  and the decompilation workflow
- `extract/` — extracted ROM contents (generated, gitignored)
- `build/` — build artifacts, disassembly listings, match results
  (generated, gitignored)

## Legal

Tooling and documentation are original work (see `LEGAL.md`). The game itself
and any future reverse-engineered source remain the property of Nintendo.
