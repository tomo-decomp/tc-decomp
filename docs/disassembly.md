# Disassembly notes (milestone 2, first pass)

Produced by `tools/disasm.py` (requires `capstone`). Listings live in
`build/disasm/` and are generated, never committed.

## Findings from the first pass

### ARM9 main is entirely ARM state — no Thumb

Scanning `extract/arm9` for Thumb `bl`/`blx` pairs finds **zero**, while the
ARM `b`/`bl` scan finds 1881 encodings resolving to **218 unique in-range
targets**, plus the header entry point = **219 function starts**. The game's
ARM9 code was compiled with CodeWarrior for ARM (`-nothumb`), unlike later
NDS titles (and pokebw2) that compile most game code as Thumb.

Practical consequence for milestone 3: expect `mwccarm` `2.0/sp2`-era ARM
code generation, `stmfd sp!, {..., lr}` prologues (71 found), and interworking
only at SDK boundaries.

### Code footprint is small relative to the binary

`arm9` is `0xB52BC` (742 KB) but only ~`0x30AC` bytes are reached by the
linear sweep from function starts; the rest is read-only data, literal pools,
and the region after the header (the file's first `0x800` bytes are the
header area's tail, disassembling as garbage — expected, that is not code).
The ARM9 program proper is the code around the entry at `0x02000800`
(NitroSDK startup: MMIO setup, mode/stack init, `bl` into the C runtime).

### Overlays

- 111 overlays, ids `0..110`, all ARM state, all sharing RAM slot
  `0x02149A40` (mutually exclusive — one mapped at a time).
- Function starts per overlay range from 1 (tiny `0x240`-byte stubs) to ~94
  (the largest, `ov109`/`ov110` at ~38 KB and ~25 KB).
- The biggest overlays by function count are the likely gameplay modules;
  see `build/disasm/ov*.funcs.tsv` for per-overlay tables.

### SDK identification (partial)

- `![SDK+NINTENDO:BACKUP]` string in ARM9 → NitroSDK **backup (save)**
  library is linked.
- `DWCPAMCP` → DWC (Nintendo Wi-Fi Connection) **PAM/CP** pieces present.
- No `NitroSDK`/`mwcc` version banner strings survive in the binary, so the
  exact SDK/compiler version is still unknown (open question, see
  `docs/layout.md`).

## Known limitations of this pass

- **Linear sweep, not recursive descent.** Data embedded between functions
  and functions reached only via function pointers are not entered; capstone
  stops a sweep at the first undecodable word, so listings may end early
  (`ended=fell-through` in the `.funcs.tsv` marks those).
- **No symbol names yet.** Every function is addressed by number; naming is
  milestone 3's job, seeded from SDK imports and string references.
- Thumb detection is unused (bit 0 of branch targets) but harmless here
  since no Thumb code exists.

## Next steps in this milestone

1. Recursion-descent sweep from the 219 ARM9 starts + overlay entries to
   close the `fell-through` gaps and get true function bounds.
2. Locate the NitroSDK import stubs (the ARM9's PLT-like veneers) to split
   SDK from game code, the same way pokebw2/aletheia do.
3. Cross-reference `extract/files/` strings against code to anchor the
   first named functions (save-system, sound, message banks under `Msg/`).
