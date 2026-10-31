# Assets

`tools/assets.py` turns the cartridge into editable files: every archive is
expanded, 2D graphics become PNG, message banks become TSV, and the sound
archive is split into its sequences, banks and samples.  It is driven entirely
by the ROM dump, so nothing derived is committed.

```sh
python3 tools/assets.py index     # classify every leaf -> build/assets/index.tsv
python3 tools/assets.py unpack    # expand archives   -> build/assets/unpack/
python3 tools/assets.py extract   # unpack + convert  -> build/assets/{art,text,audio}
```

`extract` also writes `build/assets/convert.tsv`, one row per leaf: either what
it became (`854x256`, `601 messages, encoding 2 (utf-16-le)`) or the error that
stopped it.  That file is the worklist for the converters, and it is what to
diff when a decoder changes.

## What the cartridge holds

The filesystem is 1,968 NARC archives plus the 111 overlays.  Expanding to four
levels of nesting gives 4,844 leaves:

| Kind | Count | What it is | Converted to |
|---|---|---|---|
| `BMD0` | 1,682 | 3D model (NSBMD) | kept as `.nsbmd` |
| `RGCN` | 744 | tile graphics (NCGR) | PNG |
| `RLCN` | 738 | palette (NCLR) | PNG swatch strip |
| `RCSN` | 682 | screen map (NSCR) | PNG, composited |
| `BCA0` | 159 | model animation (NSBCA) | kept as `.nsbca` |
| `RECN` | 113 | cell bank (NCER) | kept as `.ncer` |
| `RNAN` | 113 | cell animation (NANR) | kept as `.nanr` |
| `BTA0` | 24 | texture animation | kept as `.nsbta` |
| `MESG` | 24 | message bank (BMG) | TSV |
| `BTP0` | 21 | texture pattern | kept as `.nsbtp` |
| `BMA0` | 6 | material animation | kept as `.nsbma` |
| `BVA0` | 5 | visibility animation | kept as `.nsbva` |
| `RTFN` | 3 | font (NFTR) | kept as `.nftr` |
| `SDAT` | 1 | sound archive | split; WAV where decoded |
| other | 529 | textures, binaries, gaps | kept as `.bin`/`.ntft`/`.ntfp` |

The 3D models keep their textures in separate `NTFT` (texture) and `NTFP`
(palette) blocks rather than in an `NSBTX` dictionary, which is why those
appear as loose files.

## Measured formats

Everything below was read off this cartridge, not taken from a spec; the DS
formats are byte-reversed here in a way that matters.

### 2D graphics

The four-character magics are stored reversed, so the files start with `RLCN`,
`RGCN`, `RCSN`, `RECN`, `RNAN` (the spec spells them `NCLR`, `NCGR`, `NSCR`,
`NCER`, `NANR`).  The rest is ordinary little-endian:

```
NCLR   0x10 "TTLP" | +0x04 size | +0x08 bit depth (3 = 4bpp, 4 = 8bpp)
       +0x10 palette size in bytes | +0x14 palette offset
       +0x18 colours, BGR555 (bit 15 = "show", the DS's alpha bit)

NCGR   0x10 "RAHC" | +0x04 size | +0x0C bit depth | +0x10 width u16
       +0x12 height u16 | +0x18 tile data size | +0x1C tile data offset

NSCR   0x10 "NRCS" | +0x04 size | +0x08 width in cells u16
       +0x0A height in cells u16 | +0x14 tile map, u16 per cell
       cell: bits 0..9 tile index, bit 10 flip X, bit 11 flip Y
```

A tile sheet is 8x8 tiles, 32 bytes each at 4bpp and 64 at 8bpp, arranaged
left to right and then down.  Palettes are 16 or 256 entries; a file with more
than one palette repeats the 256-entry table.

An `NCGR` is converted with a palette from the same archive: the converter
prefers an `NCLR` whose name matches the tile file, then the first one in the
archive.  An `NSCR` uses the archive's `NCGR` and `NCLR` the same way.

### Message banks (BMG)

```
0x00  "MESG"         0x04  "bmg1"
0x08  file size      0x0C  section count
0x10  encoding id    0x14  section offset table
```

Sections are `INF1` (index) and `DAT1` (text), found by their magic at 0x20 and
later.  `INF1`: count u16 at +0x08, entry size u16 at +0x0A (12 bytes), entries
from +0x10 — each entry's first word is the byte offset into `DAT1`'s payload
(`DAT1` + 8), and the string runs to a `0x0000`.

The header's encoding id says 2 (Shift-JIS) on all 24 banks, but the strings are
really **UTF-16LE**: `i0c0a0k0` decodes to `どっちか`.  The extractor therefore
scores a sample both ways and uses the one that reads as kana/kanji/ASCII, and
records the winner in `convert.tsv`.

`text.write_tsv` / `text.read_tsv` round-trip losslessly: control bytes become
`\xNN`, tabs and newlines become `\t` / `\n`, so a translated file can be read
back without guessing.

### Sound (SDAT)

The archive lists 309 files: 135 `SBNK` banks, 118 `SSEQ` sequences, 52 `SSAR`
sequence archives, 3 `STRM` streams and 1 `SWAR` wave archive.  The biggest
stream is 17,392,868 bytes; the wave archive is 7,410,772.

`extract` writes every one of them out verbatim with a format extension, and
decodes a WAV when it meets a standalone `SWAV`.  Two conversions are still
open, and are deliberately not guessed:

- **SWAR samples.**  The archive has an offset table (593 entries, `0x38`..)
  and per-sample 12-byte info records (`codec`, `loop`, `rate`, `time`,
  `loopOffset`, `length`) that begin right after it at `0x97C` — the first
  record reads `02 01 44 ac 7b 01 2c 0a 49 0d`, i.e. IMA-ADPCM, looped,
  44,100 Hz.  What is not settled is the base the offsets are relative to
  (the last offset lands either just short of, or past, the end of the file
  depending on the choice), so `sdat.split_war` is not wired up yet.
- **STRM streams.**  `0x10 "HEAD"`, with the sample description after it; the
  field order in this game's `HEAD` does not match the SDK's documented order,
  so the codec/rate are read but not trusted for decoding yet.

Both are self-contained next steps, and the raw files are already on disk for
an audio editor (or for whoever picks the decoding up) to work from.

## Editing workflow

The point of the extractor is an edit loop that is reviewable in git:

1. `assets.py extract`, edit `build/assets/text/*.tsv` (or a PNG).
2. Re-import: text today needs the reverse of `text.read_tsv` plus a `DAT1`
   rebuilder that recomputes the `INF1` offsets — the offsets are part of the
   index, so a longer translation is fine as long as the bank is rebuilt.
3. `ndsrom.py build` puts the rebuilt bank back into the archive, then into the
   ROM, and `ndsrom.py verify` proves nothing else moved.

Step 2 is the missing piece for a translation patch; the reader side
(`read_tsv`) and the container side (`narc.build`) already exist.

## Cross-check with NitroPacker

`../NitroPacker` (built in `publish/net10.0`, .NET 10) unpacks the same ROM:

```sh
NitroPacker unpack -r rom.nds -o /tmp/np -p tomo -d
```

It produces `data/` with 1,969 files, `overlay/` with 111, plus `arm9.bin`,
`arm7.bin`, `banner.bin` and `tomo.json`.  Those counts match this project's
own extraction (1,969 named files, 111 overlays), which is a useful independent
check that the NARC/FNT/FAT readers agree with another implementation.  The
tool is not part of the build: `ndsrom.py` already rebuilds the ROM byte for
byte, and NitroPacker's packing path rewrites the header, which is exactly what
a matching decompilation must not do.
