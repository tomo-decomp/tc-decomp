"""Nintendo DS 2D graphics (NCLR, NCGR, NSCR) decoding.

The game's 2D resources are the standard Nitro G2D files, with one quirk: the
four-character magic is byte-reversed relative to the format's spec (`RLCN`
where the spec says `NCLR`), so the readers here accept the reversed spelling
and then parse everything else as ordinary little-endian.

Layouts, as measured from the cartridge:

    NCLR  "RLCN" | BOM | version | size | header size | section count
          "TTLP" | size | bit depth (3 = 4bpp, 4 = 8bpp) | reserved
                 | palette size in bytes | palette offset | colours (BGR555)

    NCGR  "RGCN" | BOM | version | size | header size | section count
          "RAHC" | size | -1 | bit depth | width (u16) | height (u16)
                 | reserved | tile data size | tile data offset | tiles

    NSCR  "RCSN" | BOM | version | size | header size | section count
          "NRCS" | size | width (u16, cells) | height (u16, cells)
                 | reserved | tile map size | tile map

Colours are 15-bit BGR555; bit 15 is the alpha/"show" bit.

Rasterising is done a whole tile at a time -- every 8x8 tile is expanded to
RGBA rows once, then pasted with slice assignments -- because a 256x256-cell
screen map is a four-megapixel image and a per-pixel Python loop is far too
slow for the 682 of them on the cartridge.
"""

from __future__ import annotations

import struct

from . import png

MAGIC_NCLR = (b"NCLR", b"RLCN")
MAGIC_NCGR = (b"NCGR", b"RGCN")
MAGIC_NSCR = (b"NSCR", b"RCSN")

MAX_DIMENSION = 1024
TRANSPARENT = b"\x00\x00\x00\x00"


class GfxError(ValueError):
    """The resource does not parse."""


def is_nclr(data: bytes) -> bool:
    return data[:4] in MAGIC_NCLR


def is_ncgr(data: bytes) -> bool:
    return data[:4] in MAGIC_NCGR


def _section(data: bytes, magic: bytes, start: int = 0x10) -> int:
    """Offset of the first occurrence of a section magic at/after `start`."""
    pos = data.find(magic, start)
    if pos < 0:
        raise GfxError(f"missing {magic!r} section")
    return pos


def bgr555_to_rgba(color: int) -> bytes:
    """Converts one BGR555 word into RGBA bytes."""
    red = (color & 0x1F) << 3
    green = (color >> 5 & 0x1F) << 3
    blue = (color >> 10 & 0x1F) << 3
    alpha = 0 if (color & 0x8000) == 0 else 255
    return bytes((red | red >> 5, green | green >> 5, blue | blue >> 5, alpha))


# ------------------------------------------------------------------ palettes


def read_palette(data: bytes) -> tuple[int, list[bytes]]:
    """Returns (bit depth, [RGBA colour]) for an NCLR file."""
    if not is_nclr(data):
        raise GfxError("not an NCLR")
    ttlp = _section(data, b"TTLP")
    depth, = struct.unpack_from("<I", data, ttlp + 0x08)
    size, = struct.unpack_from("<I", data, ttlp + 0x10)
    # Measured: the colour table starts right after the six-word TTLP header.
    start = ttlp + 0x18
    if size == 0 or start + size > len(data):
        size = len(data) - start
    count = size // 2
    colours = [bgr555_to_rgba(struct.unpack_from("<H", data, start + 2 * i)[0])
               for i in range(count)]
    return depth, colours


def nth_palette(data: bytes, index: int) -> list[bytes]:
    """Returns one palette of a multi-palette NCLR (256 colours each)."""
    _, colours = read_palette(data)
    chunk = colours[index * 256:(index + 1) * 256]
    return chunk or colours


# ------------------------------------------------------------------- tiles


def read_tiles(data: bytes) -> tuple[int, int, int, bytes]:
    """Returns (width, height, bit depth, tile bytes) for an NCGR file."""
    if not is_ncgr(data):
        raise GfxError("not an NCGR")
    char = _section(data, b"RAHC")
    depth, = struct.unpack_from("<I", data, char + 0x0C)
    width, height = struct.unpack_from("<HH", data, char + 0x10)
    offset, = struct.unpack_from("<I", data, char + 0x1C)
    start = char + (offset or 0x18)
    if start >= len(data):
        start = char + 0x18
    return width, height, (4 if depth == 3 else 8), data[start:]


def tile_rows(tiles: bytes, depth: int, palette: list[bytes],
              count: int) -> list[list[bytes]]:
    """Expands tiles to RGBA: one entry per tile, each entry eight row strings."""
    stride = 32 if depth == 4 else 64
    bank: list[list[bytes]] = []
    for index in range(count):
        base = index * stride
        if base + stride > len(tiles):
            bank.append([TRANSPARENT * 8] * 8)
            continue
        rows = []
        for y in range(8):
            row = bytearray()
            if depth == 4:
                for x in range(8):
                    byte = tiles[base + (y * 8 + x) // 2]
                    value = byte & 0xF if (x & 1) == 0 else byte >> 4
                    row += palette[value] if value < len(palette) else TRANSPARENT
            else:
                for x in range(8):
                    value = tiles[base + y * 8 + x]
                    row += palette[value] if value < len(palette) else TRANSPARENT
            rows.append(bytes(row))
        bank.append(rows)
    return bank


def ncgr_to_png(data: bytes, palette_data: bytes, path,
                palette_index: int = 0) -> tuple[int, int]:
    """Writes an NCGR (using the given NCLR) as a PNG; returns its size."""
    width, height, depth, tiles = read_tiles(data)
    palette = nth_palette(palette_data, palette_index)
    if depth == 8 and len(palette) < 256:
        palette = palette + [TRANSPARENT] * (256 - len(palette))
    stride = 32 if depth == 4 else 64
    if width == 0 or height == 0:
        # Most NCGRs here are *tile banks* for screen maps and declare no
        # dimensions of their own.  Lay them out 16 tiles wide so the sheet is
        # still viewable; the NSCR converter does not use this layout.
        count = len(tiles) // stride
        tiles_wide = 16
        width = tiles_wide * 8
        height = max(1, -(-count // tiles_wide)) * 8
    if not (0 < width <= MAX_DIMENSION and 0 < height <= MAX_DIMENSION):
        raise GfxError(f"implausible tile dimensions {width}x{height}")
    tiles_wide = max(1, width // 8)
    tiles_high = max(1, height // 8)
    bank = tile_rows(tiles, depth, palette,
                     min(len(tiles) // stride, tiles_wide * tiles_high))

    out = bytearray(b"\x00\x00\x00\x00" * (width * height))
    row_bytes = width * 4
    for index, rows in enumerate(bank):
        tx = (index % tiles_wide) * 8
        ty = (index // tiles_wide) * 8
        if ty + 8 > height:
            break
        for y in range(8):
            offset = (ty + y) * row_bytes + tx * 4
            out[offset:offset + 32] = rows[y]
    png.write(path, width, height, out)
    return width, height


def nclr_to_png(data: bytes, path) -> tuple[int, int]:
    """Writes an NCLR as a 16-wide swatch strip; returns its size."""
    _, colours = read_palette(data)
    if not colours:
        raise GfxError("empty palette")
    count = len(colours)
    width = 16
    height = (count + width - 1) // width
    pixels = bytearray()
    for i in range(width * height):
        pixels += colours[i] if i < count else TRANSPARENT
    png.write(path, width, height, pixels)
    return width, height


def nscr_to_png(map_data: bytes, tile_data: bytes, palette_data: bytes,
                path) -> tuple[int, int]:
    """Composes an NSCR screen using its NCGR tiles and NCLR palette.

    Measured NRCS section layout: magic, size, width (u16), height (u16),
    reserved (u32), data size (u32), then the u16 tile map, one entry per
    8x8 cell:

        bits 0..9   tile index
        bit 10      horizontal flip
        bit 11      vertical flip
    """
    scr = _section(map_data, b"NRCS")
    # The width and height are in *pixels*, not cells: a 256x256 screen is a
    # 32x32 cell map, which is 0x800 bytes and exactly what the section holds.
    pixels_wide, pixels_high = struct.unpack_from("<HH", map_data, scr + 0x08)
    start = scr + 0x14
    available = (len(map_data) - start) // 2
    cells_wide = pixels_wide // 8 or 32
    cells_high = pixels_high // 8 or max(1, available // cells_wide)
    if not (0 < cells_wide <= MAX_DIMENSION // 8
            and 0 < cells_high <= MAX_DIMENSION // 8):
        raise GfxError(f"implausible screen size {cells_wide}x{cells_high} cells")

    tile_width, tile_height, depth, tiles = read_tiles(tile_data)
    palette = nth_palette(palette_data, 0)
    if depth == 8 and len(palette) < 256:
        palette = palette + [TRANSPARENT] * (256 - len(palette))
    stride = 32 if depth == 4 else 64
    bank = tile_rows(tiles, depth, palette, len(tiles) // stride)
    flipped: dict[int, list] = {0: bank}

    def rows_for(tile: int) -> list[bytes]:
        if tile >= len(bank):
            return [TRANSPARENT * 8] * 8
        return bank[tile]

    width, height = cells_wide * 8, cells_high * 8
    out = bytearray(b"\x00\x00\x00\x00" * (width * height))
    row_bytes = width * 4
    cache: dict[tuple[int, bool, bool], list[bytes]] = {}

    for cy in range(cells_high):
        for cx in range(cells_wide):
            index = cy * cells_wide + cx
            if start + index * 2 + 2 > len(map_data):
                continue
            entry = struct.unpack_from("<H", map_data, start + index * 2)[0]
            tile = entry & 0x3FF
            flip_x = bool(entry & 0x400)
            flip_y = bool(entry & 0x800)
            key = (tile, flip_x, flip_y)
            rows = cache.get(key)
            if rows is None:
                base = rows_for(tile)
                rows = []
                for y in range(8):
                    row = base[7 - y] if flip_y else base[y]
                    if flip_x:
                        row = b"".join(row[k * 4:k * 4 + 4] for k in range(7, -1, -1))
                    rows.append(row)
                cache[key] = rows
            for y in range(8):
                offset = (cy * 8 + y) * row_bytes + cx * 8 * 4
                out[offset:offset + 32] = rows[y]
    del flipped
    png.write(path, width, height, out)
    return width, height
