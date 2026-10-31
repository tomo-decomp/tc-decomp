# Cartridge layout (measured)

All numbers below were measured from a dump of Tomodachi Collection (Japan,
game code `CCUJ`), sha1 `f37d5ff0e3444cf3fab38890efb71f4f14c96994`, by
`tools/ndsrom.py info` and the extract manifest. They describe this dump only;
a different revision may differ.

## Header area

| Field | Value |
|---|---|
| Size | `0x4000` (only the first `0x200` bytes are meaningful NDS header) |
| Title | `TOMODACHI` |
| Game code / maker | `CCUJ` / `01` |
| Unit code | `0x00` — plain NTR, **not** DSi-enhanced (no TWL region) |
| Total used ROM size | `0x364DBE0` of the 64 MiB (`0x4000000`) image; the rest is `0xFF` fill |
| Header CRC-16 | valid (bytes `0x000..0x15D`, poly `0xA001`) |

## ARM9 main

| Field | Value |
|---|---|
| ROM offset | `0x04000` |
| RAM load / entry | `0x02000000` / `0x02000800` |
| Size | `0xB52BC` (742 KB) |

The entry is `0x800` past the load address — the standard DS devkit-style
entry point, with the NitroSDK startup stub ahead of it.

## ARM7

| Field | Value |
|---|---|
| ROM offset | `0x221400` |
| RAM load / entry | `0x02380000` / `0x02380000` |
| Size | `0x270F0` (160 KB) |

No ARM7 overlays (`y7` size is 0). This is the usual NTR pattern: the ARM7
runs one fixed program (audio, touch, firmware services).

## ARM9 overlays (y9)

| Field | Value |
|---|---|
| Table | ROM `0x0B9400`, size `0x0DE0` = **111 entries**, ids `0..110` |
| Flags byte | `0x00` on every entry — none compressed at the overlay layer |
| Shared RAM slot | **every overlay loads at `0x02149A40`** |
| Sizes | min `0x240`, median `0x1880`, max `0x3A5C0` (240 KB) |

The single shared load address means the 111 overlays are *mutually
exclusive*: the game maps one at a time into the same window (classic
NDS "overlay bank" pattern). Each entry's `file id` points at its backing
bytes in the FAT.

## Filesystem

| Field | Value |
|---|---|
| FNT | `0x248600`, size `0x8AA3` — 31 directories, 1969 named files |
| FAT | `0x251200`, size `0x4100` — **2080 entries**, `0x34DF247` bytes total |
| Banner | `0x255400`, version 1, size `0xA80`, title `トモダチコレクション` |

The 111 FAT entries with no FNT name are exactly the overlay backings, so
`1969 named + 111 overlays = 2080`.

Top-level FNT directories (named-file counts):

| Directory | Files | Likely content |
|---|---|---|
| `Mdl/` | 1318 | 3D models (`*_3D_LZ.bin`), rooms, items |
| `Scn/` | 249 | scene/background graphics |
| `News/` | 200 | news items |
| `Job/` | 120 | jobs (minigame assignments) |
| `Pht/` | 50 | photos |
| `Msg/` | 24 | message/text banks |
| `Cmn/` | 7 | common data |
| (root) | 1 | `sound_data.sdat` — the SDAT sound archive, **`0x182F9E0` (23.2 MiB)**, the largest file on the cart |

Most content files are named `*_LZ.bin` and begin with byte `0x10`: the
standard NDS **LZ77** header (type 1 in the low nibble, 3-byte
little-endian decompressed size). Decompression is a milestone-4 task.

## Unmodelled bytes

The extract covers: header area, arm9, arm7, y9, FNT, FAT, banner, and all
2080 FAT files. One residue run of **324 bytes** (alignment filler and small
checksum blocks between modelled regions) is stored verbatim in
`residue.bin`; everything else outside regions is `0xFF` fill. This is what
makes `extract -> build` byte-identical by construction.

## What is *not* yet known

- Which library (NitroSDK version, MSL, etc.) each region links against
- Which compiler produced ARM9/overlays (CodeWarrior `mwccarm` presumably,
  version unknown)
- Text encoding of `Msg/` banks and any message table format
- The internal format of SDAT, `Mdl/*_3D_LZ.bin`, scene and photo files
- Script/disassembly of ARM9 and overlays (milestone 2)
