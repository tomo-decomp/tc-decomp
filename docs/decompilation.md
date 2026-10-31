# Decompiling a function

The goal of `src/` is C that the original compiler turns back into the exact
bytes of the original function. `tools/match.py` is the judge: it compiles one
file, patches relocations the way the linker would, and compares the result
against the cartridge byte for byte.

## Layout

    src/arm9/func_0200xxxx.c    -> ARM9 main program
    src/ovNNN/func_0214xxxx.c   -> overlay NNN (id from extract/overlays.tsv)

One function per file, and the file name *is* the address. Every overlay links
at `0x02149A40`, so an overlay function's name is its address in that window.

## Running the check

```sh
python3 tools/match.py build                     # every file under src/
python3 tools/match.py build --verbose           # disassemble mismatches
python3 tools/match.py file src/ov057/func_0214b978.c
python3 tools/match.py build --compiler 2.0/sp2p2
```

or through the build system, which uses the same harness:

```sh
meson setup build/meson
ninja -C build/meson check
```

`build/match/progress.json` records the last run, and `build/match/*.o` keeps
the compiled objects (the `.text` section is the function plus its literal
pool, which is exactly the range that has to match).

## Compiler

The compiler is CodeWarrior for ARM (`tools/mwccarm/<version>/mwccarm.exe`,
driven through wine) with the flags in `DEFAULT_FLAGS` in `tools/match.py`,
mirrored in `meson.build`:

| Flag | Meaning |
|---|---|
| `-O4,p` | optimize for speed (the game's build) |
| `-proc arm946e` | ARM9 |
| `-enum int`, `-char signed`, `-fp soft` | ABI details |
| `-interworking`, `-inline on,noauto`, `-ipa file` | code generation |
| `-requireprotos`, `-lang c99` | source language |

`2.0/sp2` is the working default. Functions decompiled so far also match under
`2.0/base` and `2.0/sp2p2`; a function that distinguishes them is the way to
settle the exact version.

## Finding functions

The cartridge has no symbol table, so function starts come from the code
itself:

- a `bl` target that lies inside the same image, whose preceding word is a
  flow terminator (`pop {..., pc}` or `bx lr`), is a function entry;
- the body runs to the next terminator; anything after it is padding or a
  literal pool.

`tools/disasm.py` produces linear listings (milestone 2); the addressing above
is what it uses.

## Writing the C

Names follow the usual decomp conventions:

- `func_XXXXXXXX` for code, `data_XXXXXXXX` for data. Declare what you call:

  ```c
  extern void func_02009978(void *a, void *b);
  extern int data_0214ea08[];
  ```

  The name encodes the address, and `tools/match.py` resolves the object's
  `R_ARM_CALL` / `R_ARM_PC24` / `R_ARM_ABS32` relocations by parsing it, so a
  correct symbol name is all the "linking" a single-function object needs.
- `UnkNNNNNNNN` for a struct recovered from one function, `unk_NNN` for its
  fields, `pad_NNN` for the gaps, with offsets written in hex.
- `u8`/`s8`/`u16`/`s16`/`u32`/`s32`, `Vec3` for the recurring x/y/z triple.

Two things matter for byte-exactness beyond using the right operations:

- **Typed bases beat flat pointer arithmetic.** `p + 0x2860` then a member at
  `0xb4` is not the same instruction sequence as `*(int *)(p + 0x2914)`: the
  compiler folds the constant differently and picks a different base register.
  Model the sub-object (as a struct or a typed pointer) and access members.
- **Aliasing decides scheduling.** Accesses through `char *` (or `u8 *`, which
  is a character type here) can alias anything, so loads stay interleaved with
  stores and the code comes out longer. Typing the pointee lets the compiler
  batch the loads, which is what the original build did.

## Legal

`src/` is reverse-engineered from the game and carries no license grant; see
`LEGAL.md`. No game data, no ROM, no SDK binaries are distributed here.
