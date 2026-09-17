"""
miorom.platforms.wii.tpl
~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo TPL (Texture Palette Library) and NW4R BRRES/TEX0 Resource Engine.

Comprehensive reverse engineering toolset for Nintendo GameCube and Wii texture formats:
- TPL (Texture Palette Library): Standard texture image container used across GameCube
  and Wii titles (Super Smash Bros. Melee, Mario Kart: Double Dash!!, Super Mario Galaxy,
  The Legend of Zelda: Twilight Princess, etc.).
- BRRES (Binary Revolution Resource): Modern NW4R archive container used in Wii titles
  (Mario Kart Wii, Super Smash Bros. Brawl, Xenoblade Chronicles, Skyward Sword, etc.).
- TEX0: NW4R hardware texture sections supporting CMPR (DXT1), RGB565, RGB5A3, RGBA8,
  I4, I8, IA4, IA8, CI4, and CI8 formats with full mipmapping support.
- PLT0: NW4R color lookup table (CLUT) palette sections.
- BresIndexGroup: Deterministic NW4R Patricia tree (trie) index group parser and synthesizer.

Pure Python, zero-dependency, using MioROM declarative binary primitives and codecs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import (
    I32,
    U8,
    U16,
    U32,
    BinaryStruct,
    Float32,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.result import MioRomResult

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


TPL_FORMAT_NAMES = {
    0: "I4",
    1: "I8",
    2: "IA4",
    3: "IA8",
    4: "RGB565",
    5: "RGB5A3",
    6: "RGBA8",
    8: "CI4",
    9: "CI8",
    10: "CI14X2",
    14: "CMPR",  # S3TC / DXT1
}

TPL_PALETTE_FORMAT_NAMES = {
    0: "IA8",
    1: "RGB565",
    2: "RGB5A3",
}


class TPLHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = U32()
    num_images = U32()
    table_offset = U32()


class TPLImageTableEntryStruct(BinaryStruct):
    _endian = ">"
    image_header_offset = U32()
    palette_header_offset = U32()


class TPLPaletteHeaderStruct(BinaryStruct):
    _endian = ">"
    num_entries = U16()
    unpacked = U8()
    pad = U8()
    format_id = U32()
    data_offset = U32()


class TPLImageHeaderStruct(BinaryStruct):
    _endian = ">"
    height = U16()
    width = U16()
    format_id = U32()
    data_offset = U32()
    wrap_s = U32()
    wrap_t = U32()
    min_filter = U32()
    mag_filter = U32()


class TPLColorStruct(BinaryStruct):
    _endian = ">"
    value = U16()


def decode_gx_palette(raw: bytes, num_entries: int, format_id: int) -> List[Tuple[int, int, int, int]]:
    """
    Decodes raw Nintendo GX TLUT (Texture LookUp Table) palette bytes into RGBA8888 tuples.

    Supported formats:
    - 0: IA8 (8-bit alpha, 8-bit intensity)
    - 1: RGB565 (5-bit R, 6-bit G, 5-bit B, opaque)
    - 2: RGB5A3 (15-bit RGB opaque or 12-bit RGB with 3-bit alpha)
    """
    palette: List[Tuple[int, int, int, int]] = []
    pos = 0
    for _ in range(num_entries):
        if pos + 2 > len(raw):
            palette.append((0, 0, 0, 0))
            continue
        val = (raw[pos] << 8) | raw[pos + 1]
        pos += 2
        if format_id == 0:  # IA8
            a = val >> 8
            i = val & 0xFF
            palette.append((i, i, i, a))
        elif format_id == 1:  # RGB565
            r = ((val >> 11) & 0x1F) * 255 // 31
            g = ((val >> 5) & 0x3F) * 255 // 63
            b = (val & 0x1F) * 255 // 31
            palette.append((r, g, b, 255))
        elif format_id == 2:  # RGB5A3
            if val & 0x8000:
                r = ((val >> 10) & 0x1F) * 255 // 31
                g = ((val >> 5) & 0x1F) * 255 // 31
                b = (val & 0x1F) * 255 // 31
                a = 255
            else:
                a = ((val >> 12) & 0x07) * 255 // 7
                r = ((val >> 8) & 0x0F) * 255 // 15
                g = ((val >> 4) & 0x0F) * 255 // 15
                b = (val & 0x0F) * 255 // 15
            palette.append((r, g, b, a))
        else:
            palette.append((0, 0, 0, 0))
    return palette


def encode_gx_palette(palette: List[Tuple[int, int, int, int]], format_id: int) -> bytes:
    """
    Encodes a list of RGBA8888 tuples into raw big-endian 16-bit Nintendo GX palette bytes.
    """
    out = bytearray()
    for col in palette:
        r, g, b, a = col
        if format_id == 0:  # IA8
            i = (r * 30 + g * 59 + b * 11) // 100
            out.extend([a & 0xFF, i & 0xFF])
        elif format_id == 1:  # RGB565
            r5 = r >> 3
            g6 = g >> 2
            b5 = b >> 3
            val = (r5 << 11) | (g6 << 5) | b5
            out.extend([(val >> 8) & 0xFF, val & 0xFF])
        elif format_id == 2:  # RGB5A3
            if a >= 224:
                val = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
            else:
                val = ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
            out.extend([(val >> 8) & 0xFF, val & 0xFF])
        else:
            out.extend([0, 0])
    return bytes(out)


def extract_or_quantize_palette(
    rgba_bytes: bytes,
    width: int,
    height: int,
    max_colors: int = 16,
) -> Tuple[List[Tuple[int, int, int, int]], List[int]]:
    """
    Extracts an optimal RGBA palette and pixel index array.
    If unique colors <= max_colors, extracts exact colors (lossless).
    If greater, quantizes down to max_colors using centroid frequency clustering.
    """
    pixels: List[Tuple[int, int, int, int]] = []
    total_pixels = width * height
    for i in range(0, total_pixels * 4, 4):
        pixels.append((rgba_bytes[i], rgba_bytes[i + 1], rgba_bytes[i + 2], rgba_bytes[i + 3]))

    color_counts: Dict[Tuple[int, int, int, int], int] = {}
    for p in pixels:
        color_counts[p] = color_counts.get(p, 0) + 1

    unique_colors = list(color_counts.keys())
    has_transparent = any(c[3] < 128 for c in unique_colors)
    transparent_color = (0, 0, 0, 0)

    palette: List[Tuple[int, int, int, int]] = []
    if has_transparent:
        palette.append(transparent_color)

    if len(unique_colors) <= max_colors:
        for c in unique_colors:
            if has_transparent and c[3] < 128:
                continue
            if c not in palette:
                palette.append(c)
    else:
        sorted_colors = sorted(
            [c for c in unique_colors if not (has_transparent and c[3] < 128)],
            key=lambda c: color_counts[c],
            reverse=True,
        )
        needed = max_colors - len(palette)
        palette.extend(sorted_colors[:needed])

    # BUG-07 fix: if the image consists entirely of semi-transparent pixels,
    # the loop above skips every color, leaving palette=[transparent_sentinel].
    # In this case preserve distinct alpha variants up to max_colors.
    if has_transparent and len(palette) == 1:
        for c in sorted(unique_colors, key=lambda c: color_counts[c], reverse=True):
            if c not in palette:
                palette.append(c)
            if len(palette) >= max_colors:
                break

    while len(palette) < max_colors:
        palette.append((0, 0, 0, 0))

    color_to_idx: Dict[Tuple[int, int, int, int], int] = {}
    for idx, col in enumerate(palette):
        if col not in color_to_idx:
            color_to_idx[col] = idx

    indices: List[int] = []
    cache: Dict[Tuple[int, int, int, int], int] = dict(color_to_idx)

    for p in pixels:
        if p in cache:
            indices.append(cache[p])
        elif has_transparent and p[3] < 32:
            indices.append(0)
        else:
            best_idx = 0
            best_dist = float("inf")
            for idx, c in enumerate(palette):
                dr = p[0] - c[0]
                dg = p[1] - c[1]
                db = p[2] - c[2]
                da = p[3] - c[3]
                dist = dr * dr + dg * dg + db * db + (da * da * 2)
                if dist < best_dist:
                    best_dist = dist
                    best_idx = idx
            cache[p] = best_idx
            indices.append(best_idx)

    return palette, indices


def decode_gx_texture(
    raw: bytes,
    width: int,
    height: int,
    format_id: int,
    palette: Optional[List[Tuple[int, int, int, int]]] = None,
) -> bytes:
    """
    Decodes GameCube/Wii tiled texture data into linear uncompressed RGBA8888 bytes.
    """
    w, h, fmt = width, height, format_id
    out = bytearray(w * h * 4)

    if fmt == 0:  # I4 (8x8 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(8):
                    for px in range(0, 8, 2):
                        if pos < len(raw):
                            b = raw[pos]
                            i0 = ((b >> 4) & 0x0F) * 17
                            i1 = (b & 0x0F) * 17
                            x0 = tx * 8 + px
                            y0 = ty * 8 + py
                            if x0 < w and y0 < h:
                                idx = (y0 * w + x0) * 4
                                out[idx : idx + 4] = bytes([i0, i0, i0, 255])
                            x1 = x0 + 1
                            if x1 < w and y0 < h:
                                idx = (y0 * w + x1) * 4
                                out[idx : idx + 4] = bytes([i1, i1, i1, 255])
                            pos += 1

    elif fmt == 1:  # I8 (8x4 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 3) // 4
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(8):
                        x = tx * 8 + px
                        y = ty * 4 + py
                        if pos < len(raw) and x < w and y < h:
                            val = raw[pos]
                            idx = (y * w + x) * 4
                            out[idx : idx + 4] = bytes([val, val, val, 255])
                        pos += 1

    elif fmt == 2:  # IA4 (8x4 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 3) // 4
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(8):
                        x = tx * 8 + px
                        y = ty * 4 + py
                        if pos < len(raw) and x < w and y < h:
                            b = raw[pos]
                            a = ((b >> 4) & 0x0F) * 17
                            i = (b & 0x0F) * 17
                            idx = (y * w + x) * 4
                            out[idx : idx + 4] = bytes([i, i, i, a])
                        pos += 1

    elif fmt == 3:  # IA8 (4x4 tiles)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if pos + 2 <= len(raw) and x < w and y < h:
                            a = raw[pos]
                            i = raw[pos + 1]
                            idx = (y * w + x) * 4
                            out[idx : idx + 4] = bytes([i, i, i, a])
                        pos += 2

    elif fmt == 4:  # RGB565 (4x4 tiles)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if pos + 2 <= len(raw) and x < w and y < h:
                            val = (raw[pos] << 8) | raw[pos + 1]
                            r = ((val >> 11) & 0x1F) * 255 // 31
                            g = ((val >> 5) & 0x3F) * 255 // 63
                            b = (val & 0x1F) * 255 // 31
                            idx = (y * w + x) * 4
                            out[idx : idx + 4] = bytes([r, g, b, 255])
                        pos += 2

    elif fmt == 5:  # RGB5A3 (4x4 tiles)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if pos + 2 <= len(raw) and x < w and y < h:
                            val = (raw[pos] << 8) | raw[pos + 1]
                            if val & 0x8000:
                                r = ((val >> 10) & 0x1F) * 255 // 31
                                g = ((val >> 5) & 0x1F) * 255 // 31
                                b = (val & 0x1F) * 255 // 31
                                a = 255
                            else:
                                a = ((val >> 12) & 0x07) * 255 // 7
                                r = ((val >> 8) & 0x0F) * 255 // 15
                                g = ((val >> 4) & 0x0F) * 255 // 15
                                b = (val & 0x0F) * 255 // 15
                            idx = (y * w + x) * 4
                            out[idx : idx + 4] = bytes([r, g, b, a])
                        pos += 2

    elif fmt == 6:  # RGBA8 (4x4 tiles, 64 bytes per tile: 32 bytes AR, 32 bytes GB)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        pos = 0
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                tile_ar = raw[pos : pos + 32]
                tile_gb = raw[pos + 32 : pos + 64]
                pos += 64
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        p_idx = py * 4 + px
                        if x < w and y < h and p_idx * 2 + 1 < len(tile_ar):
                            a = tile_ar[p_idx * 2]
                            r = tile_ar[p_idx * 2 + 1]
                            g = tile_gb[p_idx * 2]
                            b = tile_gb[p_idx * 2 + 1]
                            idx = (y * w + x) * 4
                            out[idx : idx + 4] = bytes([r, g, b, a])

    elif fmt == 14:  # CMPR / DXT1 (8x8 tile = 4 sub-blocks of 4x4)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        pos = 0
        sub_offsets = [(0, 0), (4, 0), (0, 4), (4, 4)]

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for sub_x, sub_y in sub_offsets:
                    if pos + 8 > len(raw):
                        break
                    c0 = (raw[pos] << 8) | raw[pos + 1]
                    c1 = (raw[pos + 2] << 8) | raw[pos + 3]
                    bits = (raw[pos + 4] << 24) | (raw[pos + 5] << 16) | (raw[pos + 6] << 8) | raw[pos + 7]
                    pos += 8

                    # Unpack 565 colors
                    r0 = ((c0 >> 11) & 0x1F) * 255 // 31
                    g0 = ((c0 >> 5) & 0x3F) * 255 // 63
                    b0 = (c0 & 0x1F) * 255 // 31
                    col0 = (r0, g0, b0, 255)

                    r1 = ((c1 >> 11) & 0x1F) * 255 // 31
                    g1 = ((c1 >> 5) & 0x3F) * 255 // 63
                    b1 = (c1 & 0x1F) * 255 // 31
                    col1 = (r1, g1, b1, 255)

                    palette = [col0, col1]
                    if c0 > c1:
                        col2 = (
                            (2 * r0 + r1) // 3,
                            (2 * g0 + g1) // 3,
                            (2 * b0 + b1) // 3,
                            255,
                        )
                        col3 = (
                            (r0 + 2 * r1) // 3,
                            (g0 + 2 * g1) // 3,
                            (b0 + 2 * b1) // 3,
                            255,
                        )
                    else:
                        col2 = ((r0 + r1) // 2, (g0 + g1) // 2, (b0 + b1) // 2, 255)
                        col3 = (0, 0, 0, 0)
                    palette.extend([col2, col3])

                    for py in range(4):
                        for px in range(4):
                            bit_shift = 30 - ((py * 4 + px) * 2)
                            p_code = (bits >> bit_shift) & 0x03
                            x = tx * 8 + sub_x + px
                            y = ty * 8 + sub_y + py
                            if x < w and y < h:
                                idx = (y * w + x) * 4
                                c = palette[p_code]
                                out[idx : idx + 4] = bytes([c[0], c[1], c[2], c[3]])

    elif fmt == 8:  # CI4 (8x8 tiles, 4 bpp, 2 pixels per byte)
        if not palette:
            raise ParseError("Paletted texture (CI4) requires a palette for decoding.")
        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        pos = 0
        pal_len = len(palette)
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(8):
                    for px in range(0, 8, 2):
                        if pos < len(raw):
                            b = raw[pos]
                            idx0 = (b >> 4) & 0x0F
                            idx1 = b & 0x0F
                            x0 = tx * 8 + px
                            y0 = ty * 8 + py
                            if x0 < w and y0 < h:
                                col = palette[idx0] if idx0 < pal_len else (0, 0, 0, 0)
                                pidx = (y0 * w + x0) * 4
                                out[pidx : pidx + 4] = bytes(col)
                            x1 = x0 + 1
                            if x1 < w and y0 < h:
                                col = palette[idx1] if idx1 < pal_len else (0, 0, 0, 0)
                                pidx = (y0 * w + x1) * 4
                                out[pidx : pidx + 4] = bytes(col)
                            pos += 1

    elif fmt == 9:  # CI8 (8x4 tiles, 8 bpp, 1 pixel per byte)
        if not palette:
            raise ParseError("Paletted texture (CI8) requires a palette for decoding.")
        tiles_x = (w + 7) // 8
        tiles_y = (h + 3) // 4
        pos = 0
        pal_len = len(palette)
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(8):
                        x = tx * 8 + px
                        y = ty * 4 + py
                        if pos < len(raw) and x < w and y < h:
                            idx = raw[pos]
                            col = palette[idx] if idx < pal_len else (0, 0, 0, 0)
                            pidx = (y * w + x) * 4
                            out[pidx : pidx + 4] = bytes(col)
                        pos += 1

    return bytes(out)


def encode_gx_texture(
    rgba: bytes,
    width: int,
    height: int,
    format_id: int,
    palette: Optional[List[Tuple[int, int, int, int]]] = None,
) -> bytes:
    """
    Encodes linear RGBA8888 bytes into GameCube/Wii tiled texture format.
    """
    w, h, fmt = width, height, format_id
    out = bytearray()

    if fmt == 0:  # I4 (8x8 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(8):
                    for px in range(0, 8, 2):
                        x0 = tx * 8 + px
                        y0 = ty * 8 + py
                        x1 = x0 + 1
                        i0 = 0
                        if x0 < w and y0 < h:
                            idx0 = (y0 * w + x0) * 4
                            i0 = (rgba[idx0] * 30 + rgba[idx0 + 1] * 59 + rgba[idx0 + 2] * 11) // 100 >> 4
                        i1 = 0
                        if x1 < w and y0 < h:
                            idx1 = (y0 * w + x1) * 4
                            i1 = (rgba[idx1] * 30 + rgba[idx1 + 1] * 59 + rgba[idx1 + 2] * 11) // 100 >> 4
                        out.append(((i0 & 0x0F) << 4) | (i1 & 0x0F))

    elif fmt == 1:  # I8 (8x4 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(8):
                        x = tx * 8 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            idx = (y * w + x) * 4
                            val = (rgba[idx] * 30 + rgba[idx + 1] * 59 + rgba[idx + 2] * 11) // 100
                            out.append(val & 0xFF)
                        else:
                            out.append(0)

    elif fmt == 2:  # IA4 (8x4 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(8):
                        x = tx * 8 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            idx = (y * w + x) * 4
                            a = rgba[idx + 3] >> 4
                            i = (rgba[idx] * 30 + rgba[idx + 1] * 59 + rgba[idx + 2] * 11) // 100 >> 4
                            out.append(((a & 0x0F) << 4) | (i & 0x0F))
                        else:
                            out.append(0)

    elif fmt == 3:  # IA8 (4x4 tiles)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            idx = (y * w + x) * 4
                            out.append(rgba[idx + 3])
                            out.append((rgba[idx] * 30 + rgba[idx + 1] * 59 + rgba[idx + 2] * 11) // 100)
                        else:
                            out.extend([0, 0])

    elif fmt == 4:  # RGB565 (4x4 tiles)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            idx = (y * w + x) * 4
                            r = rgba[idx] >> 3
                            g = rgba[idx + 1] >> 2
                            b = rgba[idx + 2] >> 3
                            val = (r << 11) | (g << 5) | b
                        else:
                            val = 0
                        out.append((val >> 8) & 0xFF)
                        out.append(val & 0xFF)

    elif fmt == 5:  # RGB5A3 (4x4 tiles)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            idx = (y * w + x) * 4
                            r = rgba[idx]
                            g = rgba[idx + 1]
                            b = rgba[idx + 2]
                            a = rgba[idx + 3]
                            if a >= 224:
                                val = 0x8000 | ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3)
                            else:
                                val = ((a >> 5) << 12) | ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
                        else:
                            val = 0
                        out.append((val >> 8) & 0xFF)
                        out.append(val & 0xFF)

    elif fmt == 6:  # RGBA8 (4x4 tiles, 64 bytes)
        tiles_x = (w + 3) // 4
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                ar_buf = bytearray()
                gb_buf = bytearray()
                for py in range(4):
                    for px in range(4):
                        x = tx * 4 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            idx = (y * w + x) * 4
                            ar_buf.append(rgba[idx + 3])
                            ar_buf.append(rgba[idx])
                            gb_buf.append(rgba[idx + 1])
                            gb_buf.append(rgba[idx + 2])
                        else:
                            ar_buf.extend([0, 0])
                            gb_buf.extend([0, 0])
                out.extend(ar_buf)
                out.extend(gb_buf)

    elif fmt == 14:  # CMPR / DXT1 (8x8 tiles)
        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        sub_offsets = [(0, 0), (4, 0), (0, 4), (4, 4)]

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for sub_x, sub_y in sub_offsets:
                    block_pixels = []
                    has_transparency = False
                    for py in range(4):
                        for px in range(4):
                            x = tx * 8 + sub_x + px
                            y = ty * 8 + sub_y + py
                            if x < w and y < h:
                                idx = (y * w + x) * 4
                                r = rgba[idx]
                                g = rgba[idx + 1]
                                b = rgba[idx + 2]
                                a = rgba[idx + 3]
                                if a < 128:
                                    has_transparency = True
                                block_pixels.append((r, g, b, a))
                            else:
                                block_pixels.append((0, 0, 0, 0))
                                has_transparency = True

                    # Find extremes (simplest representative 565 endpoints)
                    opaque_px = [p for p in block_pixels if p[3] >= 128]
                    if not opaque_px:
                        out.extend([0, 0, 0, 0, 0, 0, 0, 0])
                        continue

                    min_p = min(opaque_px, key=lambda p: p[0] + p[1] + p[2])
                    max_p = max(opaque_px, key=lambda p: p[0] + p[1] + p[2])

                    c_max = ((max_p[0] >> 3) << 11) | ((max_p[1] >> 2) << 5) | (max_p[2] >> 3)
                    c_min = ((min_p[0] >> 3) << 11) | ((min_p[1] >> 2) << 5) | (min_p[2] >> 3)

                    if has_transparency:
                        if c_max > c_min:
                            c0, c1 = c_min, c_max
                        else:
                            c0, c1 = c_max, c_min
                    else:
                        if c_max <= c_min:
                            if c_max > 0:
                                c0, c1 = c_max, c_max - 1
                            else:
                                c0, c1 = 1, 0
                        else:
                            c0, c1 = c_max, c_min

                    c0_r = ((c0 >> 11) & 0x1F) * 255 // 31
                    c0_g = ((c0 >> 5) & 0x3F) * 255 // 63
                    c0_b = (c0 & 0x1F) * 255 // 31

                    c1_r = ((c1 >> 11) & 0x1F) * 255 // 31
                    c1_g = ((c1 >> 5) & 0x3F) * 255 // 63
                    c1_b = (c1 & 0x1F) * 255 // 31

                    bits = 0
                    for p_i, p in enumerate(block_pixels):
                        if p[3] < 128:
                            code = 3 if c0 <= c1 else 1
                        else:
                            d0 = abs(p[0] - c0_r) + abs(p[1] - c0_g) + abs(p[2] - c0_b)
                            d1 = abs(p[0] - c1_r) + abs(p[1] - c1_g) + abs(p[2] - c1_b)
                            code = 0 if d0 <= d1 else 1
                        bits |= (code << (30 - p_i * 2))

                    out.append((c0 >> 8) & 0xFF)
                    out.append(c0 & 0xFF)
                    out.append((c1 >> 8) & 0xFF)
                    out.append(c1 & 0xFF)
                    out.append((bits >> 24) & 0xFF)
                    out.append((bits >> 16) & 0xFF)
                    out.append((bits >> 8) & 0xFF)
                    out.append(bits & 0xFF)

    elif fmt == 8:  # CI4 (8x8 tiles, 4 bpp, 32 bytes/tile)
        if not palette:
            raise ValueError("CI4 texture encoding requires a palette.")
        pal_len = len(palette)
        color_map: Dict[Tuple[int, int, int, int], int] = {}
        for idx, col in enumerate(palette):
            if col not in color_map:
                color_map[col] = idx

        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(8):
                    for px in range(0, 8, 2):
                        x0 = tx * 8 + px
                        y0 = ty * 8 + py
                        x1 = x0 + 1
                        idx0 = 0
                        if x0 < w and y0 < h:
                            p0 = (y0 * w + x0) * 4
                            pix0 = (rgba[p0], rgba[p0 + 1], rgba[p0 + 2], rgba[p0 + 3])
                            if pix0 in color_map:
                                idx0 = color_map[pix0]
                            else:
                                idx0 = min(
                                    range(pal_len),
                                    key=lambda i: sum((pix0[c] - palette[i][c]) ** 2 for c in range(4)),
                                )
                        idx1 = 0
                        if x1 < w and y0 < h:
                            p1 = (y0 * w + x1) * 4
                            pix1 = (rgba[p1], rgba[p1 + 1], rgba[p1 + 2], rgba[p1 + 3])
                            if pix1 in color_map:
                                idx1 = color_map[pix1]
                            else:
                                idx1 = min(
                                    range(pal_len),
                                    key=lambda i: sum((pix1[c] - palette[i][c]) ** 2 for c in range(4)),
                                )
                        out.append(((idx0 & 0x0F) << 4) | (idx1 & 0x0F))

    elif fmt == 9:  # CI8 (8x4 tiles, 8 bpp, 32 bytes/tile)
        if not palette:
            raise ValueError("CI8 texture encoding requires a palette.")
        pal_len = len(palette)
        color_map: Dict[Tuple[int, int, int, int], int] = {}
        for idx, col in enumerate(palette):
            if col not in color_map:
                color_map[col] = idx

        tiles_x = (w + 7) // 8
        tiles_y = (h + 3) // 4
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                for py in range(4):
                    for px in range(8):
                        x = tx * 8 + px
                        y = ty * 4 + py
                        if x < w and y < h:
                            p = (y * w + x) * 4
                            pix = (rgba[p], rgba[p + 1], rgba[p + 2], rgba[p + 3])
                            if pix in color_map:
                                idx = color_map[pix]
                            else:
                                idx = min(
                                    range(pal_len),
                                    key=lambda i: sum((pix[c] - palette[i][c]) ** 2 for c in range(4)),
                                )
                            out.append(idx & 0xFF)
                        else:
                            out.append(0)

    return bytes(out)


@dataclass
class TPLImage(MioRomResult):
    index: int
    width: int
    height: int
    format_id: int
    data_offset: int
    wrap_s: int = 0
    wrap_t: int = 0
    min_filter: int = 1
    mag_filter: int = 1
    palette_header_offset: int = 0
    raw_data: bytes = b""
    palette: Optional[List[Tuple[int, int, int, int]]] = None
    palette_format_id: int = 2

    @property
    def format_name(self) -> str:
        return TPL_FORMAT_NAMES.get(self.format_id, f"Unknown (0x{self.format_id:X})")

    @property
    def is_paletted(self) -> bool:
        return self.format_id in (8, 9, 10)

    @property
    def palette_format_name(self) -> str:
        return TPL_PALETTE_FORMAT_NAMES.get(self.palette_format_id, f"Unknown (0x{self.palette_format_id:X})")

    @property
    def color_count(self) -> int:
        return len(self.palette) if self.palette else 0

    def summary(self) -> str:
        pal_info = f", Paletted ({self.palette_format_name}, {self.color_count} colors)" if self.is_paletted else ""
        return (
            f"TPLImage #{self.index}: {self.width}x{self.height} | "
            f"Format: {self.format_name} (0x{self.format_id:02X}){pal_info} | "
            f"Data Size: {len(self.raw_data)} bytes"
        )

    def to_terminal_ascii(self, max_width: int = 40) -> str:
        """
        Renders an ASCII art representation of the texture for terminal diagnostics.
        """
        rgba = decode_gx_texture(self.raw_data, self.width, self.height, self.format_id, palette=self.palette)
        tw = min(self.width, max_width)
        th = max(1, int(self.height * (tw / self.width) * 0.5))

        ascii_chars = " .:-=+*#%@"
        lines = []
        for ty in range(th):
            line = []
            for tx in range(tw):
                src_x = int(tx * self.width / tw)
                src_y = int(ty * self.height / th)
                idx = (src_y * self.width + src_x) * 4
                r = rgba[idx]
                g = rgba[idx + 1]
                b = rgba[idx + 2]
                a = rgba[idx + 3]
                if a < 32:
                    line.append(" ")
                else:
                    lum = (r * 299 + g * 587 + b * 114) // 1000
                    lum = lum * a // 255
                    char_idx = lum * (len(ascii_chars) - 1) // 255
                    line.append(ascii_chars[char_idx])
            lines.append("".join(line))
        return "\n".join(lines)

    def __repr__(self) -> str:
        pal_info = f" palette={self.palette_format_name}[{self.color_count}]" if self.is_paletted else ""
        return (
            f"<TPLImage #{self.index} {self.width}x{self.height} "
            f"format={self.format_name}{pal_info} offset=0x{self.data_offset:06X} "
            f"({len(self.raw_data)} bytes)>"
        )
def calc_gx_texture_size(width: int, height: int, format_id: int) -> int:
    """Calculates the byte size of a tiled GX texture according to its format."""
    if format_id in (0, 8):  # I4, CI4 (8x8 tiles, 4 bpp = 32 bytes/tile)
        bw = (width + 7) // 8
        bh = (height + 7) // 8
        return bw * bh * 32
    elif format_id in (1, 2, 9):  # I8, IA4, CI8 (8x4 tiles, 8 bpp = 32 bytes/tile)
        bw = (width + 7) // 8
        bh = (height + 3) // 4
        return bw * bh * 32
    elif format_id in (3, 4, 5, 10):  # IA8, RGB565, RGB5A3 (4x4 tiles, 16 bpp = 32 bytes/tile)
        bw = (width + 3) // 4
        bh = (height + 3) // 4
        return bw * bh * 32
    elif format_id == 6:  # RGBA8 (4x4 tiles, 32 bpp = 64 bytes/tile)
        bw = (width + 3) // 4
        bh = (height + 3) // 4
        return bw * bh * 64
    elif format_id == 14:  # CMPR (8x8 tile = 32 bytes/tile)
        bw = (width + 7) // 8
        bh = (height + 7) // 8
        return bw * bh * 32
    else:
        return width * height * 4


class TPLFile:
    """
    Nintendo TPL (Texture Palette Library) reader and builder.
    Standard texture image container used in Nintendo GameCube and Wii games.
    """

    MAGIC = 0x0020AF30

    def __init__(self, images: Optional[List[TPLImage]] = None):
        self.images: List[TPLImage] = images or []

    @classmethod
    def from_file(cls, filepath: str) -> TPLFile:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> TPLFile:
        if len(data) < TPLHeaderStruct.sizeof():
            raise ParseError("Data too short for TPL header.")

        header = TPLHeaderStruct.from_bytes(data, offset=0)
        if header.magic != cls.MAGIC:
            raise ParseError(f"Invalid TPL magic: expected 0x0020AF30, got {hex(header.magic)}")

        images: List[TPLImage] = []

        for i in range(header.num_images):
            entry_offset = header.table_offset + i * TPLImageTableEntryStruct.sizeof()
            entry = TPLImageTableEntryStruct.from_bytes(data, offset=entry_offset)

            if entry.image_header_offset == 0:
                continue

            image_header = TPLImageHeaderStruct.from_bytes(data, offset=entry.image_header_offset)

            data_size = cls._calculate_texture_size(
                image_header.width,
                image_header.height,
                image_header.format_id,
            )
            data_offset = image_header.data_offset
            raw_bytes = (
                data[data_offset : data_offset + data_size]
                if data_offset + data_size <= len(data)
                else data[data_offset:]
            )

            palette_colors = None
            pal_format_id = 2
            if (
                entry.palette_header_offset != 0
                and entry.palette_header_offset + TPLPaletteHeaderStruct.sizeof() <= len(data)
            ):
                pal_header = TPLPaletteHeaderStruct.from_bytes(data, offset=entry.palette_header_offset)
                pal_format_id = pal_header.format_id
                pal_size = pal_header.num_entries * 2
                pal_raw = data[pal_header.data_offset : pal_header.data_offset + pal_size]
                palette_colors = decode_gx_palette(pal_raw, pal_header.num_entries, pal_header.format_id)

            images.append(
                TPLImage(
                    index=i,
                    width=image_header.width,
                    height=image_header.height,
                    format_id=image_header.format_id,
                    data_offset=image_header.data_offset,
                    wrap_s=image_header.wrap_s,
                    wrap_t=image_header.wrap_t,
                    min_filter=image_header.min_filter,
                    mag_filter=image_header.mag_filter,
                    palette_header_offset=entry.palette_header_offset,
                    raw_data=raw_bytes,
                    palette=palette_colors,
                    palette_format_id=pal_format_id,
                )
            )

        return cls(images)
    @classmethod
    def _calculate_texture_size(cls, width: int, height: int, format_id: int) -> int:
        return calc_gx_texture_size(width, height, format_id)

    def decode_rgba(self, image_index: int = 0) -> bytes:
        """
        Decodes the specified texture image into linear uncompressed RGBA8888 byte stream.
        """
        if image_index >= len(self.images):
            raise IndexError(f"Image index {image_index} out of range.")

        img = self.images[image_index]
        return decode_gx_texture(img.raw_data, img.width, img.height, img.format_id, palette=img.palette)

    def to_image(self, image_index: int = 0) -> Any:
        """
        Renders the specified TPL image to an RGBA image.
        Returns a PIL Image when Pillow is installed, or a PNGImage (zero-dependency fallback).
        """
        if image_index >= len(self.images):
            raise IndexError(f"Image index {image_index} out of range.")

        img = self.images[image_index]
        rgba = self.decode_rgba(image_index)
        if HAS_PIL:
            return Image.frombytes("RGBA", (img.width, img.height), rgba)
        from miorom.graphics.png_codec import PNGColorType, PNGImage
        return PNGImage(
            width=img.width,
            height=img.height,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=rgba,
        )

    def to_png(self, output_path: str, image_index: int = 0) -> str:
        """
        Saves the specified TPL image to a PNG file. Zero-dependency (works without Pillow).
        """
        from miorom.graphics.png_codec import PNGCodec
        if image_index >= len(self.images):
            raise IndexError(f"Image index {image_index} out of range.")
        img = self.images[image_index]
        rgba = self.decode_rgba(image_index)
        png_bytes = PNGCodec.encode_rgba(img.width, img.height, rgba)
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        return output_path

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, Any],
        format_id: int = 5,
        palette_format_id: int = 2,
        palette: Optional[List[Tuple[int, int, int, int]]] = None,
    ) -> TPLFile:
        """
        Creates a TPLFile container containing a single encoded image.
        Default format: 5 (RGB5A3).
        Supports paletted formats: 8 (CI4) and 9 (CI8).
        Works zero-dependency (without Pillow).
        """
        if isinstance(image_or_path, str):
            if HAS_PIL:
                pil_img = Image.open(image_or_path).convert("RGBA")
                width, height = pil_img.size
                rgba_bytes = pil_img.tobytes()
            else:
                from miorom.graphics.png_codec import PNGCodec
                raw = open(image_or_path, "rb").read()
                width, height, rgba_bytes = PNGCodec.png_to_rgba(raw)
        elif HAS_PIL and isinstance(image_or_path, Image.Image):
            pil_img = image_or_path.convert("RGBA")
            width, height = pil_img.size
            rgba_bytes = pil_img.tobytes()
        else:
            from miorom.graphics.png_codec import PNGImage
            if isinstance(image_or_path, PNGImage):
                width, height = image_or_path.width, image_or_path.height
                rgba_bytes = image_or_path.to_rgba_bytes()
            elif hasattr(image_or_path, "convert"):
                pil_img = image_or_path.convert("RGBA")
                width, height = pil_img.size
                rgba_bytes = pil_img.tobytes()
            else:
                raise TypeError(f"Expected file path, PIL Image, or PNGImage, got {type(image_or_path)}")

        final_palette = palette
        if format_id in (8, 9):
            if final_palette is None:
                max_colors = 16 if format_id == 8 else 256
                final_palette, _ = extract_or_quantize_palette(rgba_bytes, width, height, max_colors=max_colors)
            raw_data = encode_gx_texture(rgba_bytes, width, height, format_id, palette=final_palette)
        else:
            raw_data = encode_gx_texture(rgba_bytes, width, height, format_id)

        tpl_img = TPLImage(
            index=0,
            width=width,
            height=height,
            format_id=format_id,
            data_offset=0,
            raw_data=raw_data,
            palette=final_palette,
            palette_format_id=palette_format_id,
        )
        return cls(images=[tpl_img])

    def to_bytes(self) -> bytes:
        """
        Serializes the TPLFile back into standard Nintendo GameCube/Wii TPL binary format.
        Preserves full 32-byte alignment for hardware DMA texture and palette transfers.
        """
        num_images = len(self.images)
        writer = BinaryWriter(endian=">")

        # 1. Main Header
        header = TPLHeaderStruct(
            magic=self.MAGIC,
            num_images=num_images,
            table_offset=TPLHeaderStruct.sizeof(),
        )
        writer.write_struct(header)

        # 2. Image Table Placeholder
        table_offset = writer.tell()
        for _ in range(num_images):
            writer.write_struct(
                TPLImageTableEntryStruct(image_header_offset=0, palette_header_offset=0)
            )

        # Pad table to 32 bytes
        writer.align(32)

        # 3. Palette Headers (if any)
        pal_header_offsets: List[int] = [0] * num_images
        for i, img in enumerate(self.images):
            if img.palette is not None and len(img.palette) > 0:
                pal_header_offsets[i] = writer.tell()
                writer.write_struct(
                    TPLPaletteHeaderStruct(
                        num_entries=len(img.palette),
                        unpacked=0,
                        pad=0,
                        format_id=img.palette_format_id,
                        data_offset=0,  # placeholder
                    )
                )

        if any(pal_header_offsets):
            writer.align(32)

        # 4. Palette Color Data (if any)
        pal_data_offsets: List[int] = [0] * num_images
        for i, img in enumerate(self.images):
            if pal_header_offsets[i] != 0 and img.palette:
                writer.align(32)
                pal_data_offsets[i] = writer.tell()
                pal_bytes = encode_gx_palette(img.palette, img.palette_format_id)
                writer.write_bytes(pal_bytes)

        # Patch palette headers with palette data offsets
        for i, h_off in enumerate(pal_header_offsets):
            if h_off != 0 and self.images[i].palette:
                img = self.images[i]
                with writer.at(h_off):
                    writer.write_struct(
                        TPLPaletteHeaderStruct(
                            num_entries=len(img.palette),
                            unpacked=0,
                            pad=0,
                            format_id=img.palette_format_id,
                            data_offset=pal_data_offsets[i],
                        )
                    )

        writer.align(32)

        # 5. Write Image Headers
        img_header_offsets: List[int] = []
        for img in self.images:
            img_header_offsets.append(writer.tell())
            writer.write_struct(
                TPLImageHeaderStruct(
                    height=img.height,
                    width=img.width,
                    format_id=img.format_id,
                    data_offset=0,  # placeholder
                    wrap_s=img.wrap_s,
                    wrap_t=img.wrap_t,
                    min_filter=img.min_filter,
                    mag_filter=img.mag_filter,
                )
            )

        writer.align(32)

        # 6. Write Texture Data
        data_offsets: List[int] = []
        for img in self.images:
            writer.align(32)
            data_offsets.append(writer.tell())
            writer.write_bytes(img.raw_data)

        # 7. Patch table with image header & palette header offsets
        with writer.at(table_offset):
            for i in range(num_images):
                writer.write_struct(
                    TPLImageTableEntryStruct(
                        image_header_offset=img_header_offsets[i],
                        palette_header_offset=pal_header_offsets[i],
                    )
                )

        # 8. Patch image headers with actual texture data offsets
        for i, h_off in enumerate(img_header_offsets):
            img = self.images[i]
            d_off = data_offsets[i]
            with writer.at(h_off):
                writer.write_struct(
                    TPLImageHeaderStruct(
                        height=img.height,
                        width=img.width,
                        format_id=img.format_id,
                        data_offset=d_off,
                        wrap_s=img.wrap_s,
                        wrap_t=img.wrap_t,
                        min_filter=img.min_filter,
                        mag_filter=img.mag_filter,
                    )
                )

        return writer.to_bytes()


# ===========================================================================
# NW4R BRRES (Binary Revolution Resource) & TEX0 / PLT0 Engine
# ===========================================================================


class BRRESHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)  # b"bres"
    bom = U16()          # 0xFEFF
    version = U16()      # 0
    file_size = U32()
    root_offset = U16()  # 0x0010
    num_sections = U16()


class BRRESRootHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)  # b"root"
    size = U32()


class BresIndexGroupHeaderStruct(BinaryStruct):
    _endian = ">"
    size = U32()
    num_entries = U32()


class BresIndexEntryStruct(BinaryStruct):
    _endian = ">"
    entry_id = U16()
    flag = U16()
    left_index = U16()
    right_index = U16()
    string_offset = U32()
    data_offset = U32()


class TEX0HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)          # b"TEX0"
    section_size = U32()
    version = U32()              # 1 or 3
    bres_offset = I32()          # Negative relative offset to bres header
    header_len = U32()           # 0x40
    string_offset = U32()
    has_palette = U32()
    width = U16()
    height = U16()
    format_id = U32()
    num_mipmaps = U32()
    min_lod = Float32()
    max_lod = Float32()
    orig_path_offset = U32()
    user_data_offset = U32()
    pad0 = U32()
    pad1 = U32()


class PLT0HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)          # b"PLT0"
    section_size = U32()
    version = U32()              # 1
    bres_offset = I32()          # Negative relative offset to bres header
    header_len = U32()           # 0x40
    string_offset = U32()
    format_id = U32()            # 0=IA8, 1=RGB565, 2=RGB5A3
    num_entries = U16()
    pad = U16()
    orig_path_offset = U32()
    pad_bytes = RawBytes(28)


def _compare_bits(b1: int, b2: int) -> int:
    """Finds highest bit index (7 down to 0) where two bytes differ."""
    for i in range(7, -1, -1):
        b = 1 << i
        if (b1 & b) != (b2 & b):
            return i
    return 0


class BresIndexEntry:
    """
    NW4R Patricia tree index entry (16 bytes).
    Used in BRRES index groups (res_dict) to look up resources by name in O(k) time.
    """

    def __init__(
        self,
        entry_id: int = 0xFFFF,
        flag: int = 0,
        left_index: int = 0,
        right_index: int = 0,
        string_offset: int = 0,
        data_offset: int = 0,
        name: str = "",
    ):
        self.entry_id = entry_id
        self.flag = flag
        self.left_index = left_index
        self.right_index = right_index
        self.string_offset = string_offset
        self.data_offset = data_offset
        self.name = name

    def to_bytes(self) -> bytes:
        return BresIndexEntryStruct(
            entry_id=self.entry_id,
            flag=self.flag,
            left_index=self.left_index,
            right_index=self.right_index,
            string_offset=self.string_offset,
            data_offset=self.data_offset,
        ).to_bytes()

    def __repr__(self) -> str:
        return (
            f"<BresIndexEntry name={self.name!r} id={hex(self.entry_id)} "
            f"left={self.left_index} right={self.right_index} "
            f"data_off={hex(self.data_offset)} str_off={hex(self.string_offset)}>"
        )


class BresIndexGroup:
    """
    NW4R Patricia Tree Index Group (Dictionary / Folder).
    Represents a directory node in a BRRES archive containing named sub-folders or asset sections.
    """

    def __init__(
        self,
        entries: Optional[List[BresIndexEntry]] = None,
        total_size: int = 0,
    ):
        self.entries: List[BresIndexEntry] = entries or []
        self.total_size = total_size
        self._raw_str_table: bytes = b""

    @classmethod
    def build(cls, items: List[Tuple[str, int]]) -> BresIndexGroup:
        """
        Builds a deterministic NW4R Patricia Tree index group from a list of (name, data_offset) pairs.
        Calculates tree bits and string table correctly according to NW4R specifications.
        """
        n = len(items)
        group = cls()
        if n == 0:
            group.entries = [BresIndexEntry(0xFFFF, 0, 0, 0, 0, 0, "")]
            group.total_size = 24
            group._raw_str_table = b""
            return group

        # 1. Precalculate string table layout
        str_table = bytearray()
        str_offsets: List[int] = []
        base_str_offset = 8 + (n + 1) * 16

        for name, _ in items:
            name_bytes = name.encode("ascii", errors="replace")
            str_offset = base_str_offset + len(str_table) + 4
            str_offsets.append(str_offset)
            writer = BinaryWriter(endian=">")
            writer.write_u32(len(name_bytes))
            str_table += writer.to_bytes()
            str_table += name_bytes + b"\x00"
            while len(str_table) % 4 != 0:
                str_table += b"\x00"

        total_size = base_str_offset + len(str_table)

        # 2. Build Patricia tree entries
        entries: List[BresIndexEntry] = [
            BresIndexEntry(0xFFFF, 0, 0, 0, 0, 0, "") for _ in range(n + 1)
        ]

        for index in range(1, n + 1):
            name, data_offset = items[index - 1]
            p_char = name.encode("ascii", errors="replace")
            str_len = len(p_char)
            data_addr = data_offset
            str_addr = str_offsets[index - 1]

            e_index = str_len - 1
            e_bits = _compare_bits(p_char[e_index], 0)

            entry = BresIndexEntry(
                entry_id=(e_index << 3) | e_bits,
                flag=0,
                left_index=index,
                right_index=index,
                string_offset=str_addr,
                data_offset=data_addr,
                name=name,
            )
            entries[index] = entry

            prev = entries[0]
            current_index = prev.left_index
            current = entries[current_index]
            is_right = False

            while entry.entry_id <= current.entry_id and prev.entry_id > current.entry_id:
                if entry.entry_id == current.entry_id:
                    s_char = current.name.encode("ascii", errors="replace")
                    for e_index in range(str_len - 1, -1, -1):
                        if e_index >= len(s_char) or p_char[e_index] != s_char[e_index]:
                            break
                    s_val = s_char[e_index] if e_index < len(s_char) else 0
                    e_bits = _compare_bits(p_char[e_index], s_val)
                    entry.entry_id = (e_index << 3) | e_bits
                    if ((s_val >> e_bits) & 1) != 0:
                        entry.left_index = index
                        entry.right_index = current_index
                    else:
                        entry.left_index = current_index
                        entry.right_index = index

                val = current.entry_id >> 3
                is_right = val < str_len and (((p_char[val] >> (current.entry_id & 7)) & 1) != 0)
                prev = current
                current_index = current.right_index if is_right else current.left_index
                current = entries[current_index]

            s_char = current.name.encode("ascii", errors="replace") if current.name else b""
            val = len(s_char)
            s_val = s_char[e_index] if (0 <= e_index < len(s_char)) else 0
            if val == str_len and (((s_val >> e_bits) & 1) != 0):
                entry.right_index = current_index
            else:
                entry.left_index = current_index

            if is_right:
                prev.right_index = index
            else:
                prev.left_index = index

        group.entries = entries
        group.total_size = total_size
        group._raw_str_table = bytes(str_table)
        return group

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> BresIndexGroup:
        if offset + 8 > len(data):
            raise ParseError("Index group data too short for header.")
        hdr = BresIndexGroupHeaderStruct.from_bytes(data[offset:offset + 8])
        entries: List[BresIndexEntry] = []
        for i in range(hdr.num_entries + 1):
            e_off = offset + 8 + i * 16
            if e_off + 16 > len(data):
                break
            es = BresIndexEntryStruct.from_bytes(data[e_off:e_off + 16])
            name = ""
            if i > 0 and es.string_offset != 0:
                str_addr = offset + es.string_offset
                if str_addr < len(data):
                    if str_addr >= offset + 4:
                        reader = BinaryReader(data[str_addr - 4:str_addr], endian=">")
                        str_len = reader.read_u32()
                        if 0 < str_len < 512 and str_addr + str_len <= len(data):
                            name = data[str_addr:str_addr + str_len].decode("ascii", errors="replace")
                    if not name:
                        end = data.find(b"\x00", str_addr)
                        if end != -1:
                            name = data[str_addr:end].decode("ascii", errors="replace")
                        else:
                            name = data[str_addr:str_addr + 64].decode("ascii", errors="replace")

            entries.append(
                BresIndexEntry(
                    entry_id=es.entry_id,
                    flag=es.flag,
                    left_index=es.left_index,
                    right_index=es.right_index,
                    string_offset=es.string_offset,
                    data_offset=es.data_offset,
                    name=name,
                )
            )
        group = cls(entries=entries, total_size=hdr.size)
        return group

    def find(self, name: str) -> Optional[BresIndexEntry]:
        """Looks up an entry by name using the Patricia Tree structure with linear fallback."""
        if not self.entries or len(self.entries) <= 1:
            return None
        p_bytes = name.encode("ascii", errors="replace")
        str_len = len(p_bytes)
        prev = self.entries[0]
        curr_idx = prev.left_index
        if curr_idx < len(self.entries):
            curr = self.entries[curr_idx]
            while prev.entry_id > curr.entry_id:
                val = curr.entry_id >> 3
                is_right = val < str_len and (((p_bytes[val] >> (curr.entry_id & 7)) & 1) != 0)
                prev = curr
                curr_idx = curr.right_index if is_right else curr.left_index
                if curr_idx >= len(self.entries):
                    break
                curr = self.entries[curr_idx]
            if curr.name == name:
                return curr

        for e in self.entries[1:]:
            if e.name == name:
                return e
        return None

    def to_bytes(self) -> bytes:
        writer = BinaryWriter(endian=">")
        n = len(self.entries) - 1 if self.entries else 0
        if n < 0:
            n = 0
        if not getattr(self, "_raw_str_table", None):
            str_table = bytearray()
            base_str_offset = 8 + (n + 1) * 16
            for e in self.entries[1:]:
                e.string_offset = base_str_offset + len(str_table) + 4
                name_bytes = e.name.encode("ascii", errors="replace")
                w = BinaryWriter(endian=">")
                w.write_u32(len(name_bytes))
                str_table += w.to_bytes()
                str_table += name_bytes + b"\x00"
                while len(str_table) % 4 != 0:
                    str_table += b"\x00"
            self._raw_str_table = bytes(str_table)
            self.total_size = base_str_offset + len(str_table)

        hdr = BresIndexGroupHeaderStruct(size=self.total_size, num_entries=n)
        writer.write_struct(hdr)
        for e in self.entries:
            entry_s = BresIndexEntryStruct(
                entry_id=e.entry_id,
                flag=e.flag,
                left_index=e.left_index,
                right_index=e.right_index,
                string_offset=e.string_offset,
                data_offset=e.data_offset,
            )
            writer.write_struct(entry_s)
        writer.write_bytes(self._raw_str_table)
        return writer.to_bytes()


class TEX0Image(MioRomResult):
    """
    NW4R TEX0 Texture Section.
    Standard texture format used in Wii NW4R BRRES resource archives.
    Header is 0x40 bytes, followed by Nintendo GX hardware tiled pixel data.
    """

    def __init__(
        self,
        name: str = "texture",
        width: int = 0,
        height: int = 0,
        format_id: int = 14,
        pixel_data: bytes = b"",
        has_palette: bool = False,
        palette_data: Optional[bytes] = None,
        palette_format: int = 2,
        num_mipmaps: int = 1,
        min_lod: float = 0.0,
        max_lod: float = 0.0,
        version: int = 1,
        orig_path: str = "",
    ):
        self.name = name
        self.width = width
        self.height = height
        self.format_id = format_id
        self.pixel_data = pixel_data
        self.has_palette = has_palette or (format_id in (8, 9, 10))
        self.palette_data = palette_data
        self.palette_format = palette_format
        self.num_mipmaps = num_mipmaps
        self.min_lod = min_lod
        self.max_lod = max_lod
        self.version = version
        self.orig_path = orig_path

    @property
    def format_name(self) -> str:
        return TPL_FORMAT_NAMES.get(self.format_id, f"GX_{self.format_id}")

    @property
    def palette_format_name(self) -> str:
        return TPL_PALETTE_FORMAT_NAMES.get(self.palette_format, f"PAL_{self.palette_format}")

    def is_paletted(self) -> bool:
        return self.format_id in (8, 9, 10) or self.has_palette

    def decode_rgba(self) -> bytes:
        palette_colors: Optional[List[Tuple[int, int, int, int]]] = None
        if self.is_paletted() and self.palette_data:
            num_colors = len(self.palette_data) // 2
            palette_colors = decode_gx_palette(self.palette_data, num_colors, self.palette_format)
        return decode_gx_texture(
            self.pixel_data,
            self.width,
            self.height,
            self.format_id,
            palette=palette_colors,
        )

    def to_image(self) -> Any:
        rgba = self.decode_rgba()
        if HAS_PIL:
            return Image.frombytes("RGBA", (self.width, self.height), rgba)
        from miorom.graphics.png_codec import PNGColorType, PNGImage

        return PNGImage(
            width=self.width,
            height=self.height,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=rgba,
        )

    def to_png(self, output_path: str) -> str:
        from miorom.graphics.png_codec import PNGCodec

        rgba = self.decode_rgba()
        png_bytes = PNGCodec.encode_rgba(self.width, self.height, rgba)
        with open(output_path, "wb") as f:
            f.write(png_bytes)
        return output_path

    def to_bytes(self, bres_offset: int = 0) -> bytes:
        writer = BinaryWriter(endian=">")
        hdr = TEX0HeaderStruct(
            magic=b"TEX0",
            section_size=0x40 + len(self.pixel_data),
            version=self.version,
            bres_offset=bres_offset,
            header_len=0x40,
            string_offset=0,
            has_palette=1 if self.is_paletted() else 0,
            width=self.width,
            height=self.height,
            format_id=self.format_id,
            num_mipmaps=self.num_mipmaps,
            min_lod=self.min_lod,
            max_lod=self.max_lod if self.max_lod > 0 else float(max(0, self.num_mipmaps - 1)),
            orig_path_offset=0,
            user_data_offset=0,
            pad0=0,
            pad1=0,
        )
        writer.write_struct(hdr)
        writer.write_bytes(self.pixel_data)
        writer.align(32)
        return writer.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes, name: str = "") -> TEX0Image:
        if len(data) < 0x40:
            raise ParseError(f"TEX0 data too short ({len(data)} bytes, expected at least 64 bytes).")
        if data[:4] != b"TEX0":
            raise ParseError(f"Invalid TEX0 magic: {data[:4]!r}")
        hdr = TEX0HeaderStruct.from_bytes(data[:0x40])
        extracted_name = name
        if not extracted_name and hdr.string_offset != 0 and hdr.string_offset < len(data):
            str_addr = hdr.string_offset
            end = data.find(b"\x00", str_addr)
            if end != -1:
                extracted_name = data[str_addr:end].decode("ascii", errors="replace")

        pixel_data = data[hdr.header_len:hdr.section_size] if hdr.section_size <= len(data) else data[hdr.header_len:]
        return cls(
            name=extracted_name,
            width=hdr.width,
            height=hdr.height,
            format_id=hdr.format_id,
            pixel_data=pixel_data,
            has_palette=hdr.has_palette != 0,
            num_mipmaps=hdr.num_mipmaps,
            min_lod=hdr.min_lod,
            max_lod=hdr.max_lod,
            version=hdr.version,
        )

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, Any],
        name: str = "texture",
        format_id: int = 14,
        palette_format: int = 2,
    ) -> TEX0Image:
        """
        Creates a TEX0Image from a file path, PIL Image, or PNGImage.
        Default format: 14 (CMPR / DXT1).
        Supports paletted formats (CI4, CI8) with automatic color quantization.
        """
        if isinstance(image_or_path, str):
            if HAS_PIL:
                pil_img = Image.open(image_or_path).convert("RGBA")
                width, height = pil_img.size
                rgba_bytes = pil_img.tobytes()
            else:
                from miorom.graphics.png_codec import PNGCodec

                with open(image_or_path, "rb") as f:
                    raw = f.read()
                width, height, rgba_bytes = PNGCodec.png_to_rgba(raw)
        elif HAS_PIL and isinstance(image_or_path, Image.Image):
            pil_img = image_or_path.convert("RGBA")
            width, height = pil_img.size
            rgba_bytes = pil_img.tobytes()
        else:
            from miorom.graphics.png_codec import PNGImage

            if isinstance(image_or_path, PNGImage):
                width, height = image_or_path.width, image_or_path.height
                rgba_bytes = image_or_path.to_rgba_bytes()
            elif hasattr(image_or_path, "convert"):
                pil_img = image_or_path.convert("RGBA")
                width, height = pil_img.size
                rgba_bytes = pil_img.tobytes()
            else:
                raise TypeError(f"Expected file path, PIL Image, or PNGImage, got {type(image_or_path)}")

        pal_data: Optional[bytes] = None
        if format_id in (8, 9):
            max_colors = 16 if format_id == 8 else 256
            palette_colors, _ = extract_or_quantize_palette(rgba_bytes, width, height, max_colors=max_colors)
            pixel_data = encode_gx_texture(rgba_bytes, width, height, format_id, palette=palette_colors)
            pal_data = encode_gx_palette(palette_colors, palette_format)
        else:
            pixel_data = encode_gx_texture(rgba_bytes, width, height, format_id)

        return cls(
            name=name,
            width=width,
            height=height,
            format_id=format_id,
            pixel_data=pixel_data,
            has_palette=format_id in (8, 9),
            palette_data=pal_data,
            palette_format=palette_format,
            num_mipmaps=1,
            version=1,
        )

    def summary(self) -> str:
        lines = [
            f"TEX0 '{self.name}':",
            f"  Dimensions: {self.width}x{self.height}",
            f"  Format:     {self.format_name} (ID {self.format_id})",
            f"  Mipmaps:    {self.num_mipmaps}",
            f"  Pixel Data: {len(self.pixel_data):,} bytes",
            f"  Paletted:   {self.is_paletted()}",
        ]
        if self.palette_data:
            lines.append(f"  Palette:    {len(self.palette_data):,} bytes ({self.palette_format_name})")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"<TEX0Image '{self.name}' {self.width}x{self.height} {self.format_name}>"


class PLT0Palette(MioRomResult):
    """
    NW4R PLT0 Palette Section.
    Color LookUp Table (CLUT) used with CI4 and CI8 paletted textures.
    Header is 0x40 bytes, followed by 16-bit color entries.
    """

    def __init__(
        self,
        name: str = "palette",
        format_id: int = 2,
        num_entries: int = 16,
        data: bytes = b"",
        version: int = 1,
    ):
        self.name = name
        self.format_id = format_id
        self.num_entries = num_entries
        self.data = data
        self.version = version

    @property
    def format_name(self) -> str:
        return TPL_PALETTE_FORMAT_NAMES.get(self.format_id, f"PAL_{self.format_id}")

    def decode_colors(self) -> List[Tuple[int, int, int, int]]:
        return decode_gx_palette(self.data, self.num_entries, self.format_id)

    def to_bytes(self, bres_offset: int = 0) -> bytes:
        writer = BinaryWriter(endian=">")
        hdr = PLT0HeaderStruct(
            magic=b"PLT0",
            section_size=0x40 + len(self.data),
            version=self.version,
            bres_offset=bres_offset,
            header_len=0x40,
            string_offset=0,
            format_id=self.format_id,
            num_entries=self.num_entries,
            pad=0,
            orig_path_offset=0,
            pad_bytes=b"\x00" * 28,
        )
        writer.write_struct(hdr)
        writer.write_bytes(self.data)
        writer.align(32)
        return writer.to_bytes()

    @classmethod
    def from_bytes(cls, data: bytes, name: str = "") -> PLT0Palette:
        if len(data) < 0x40:
            raise ParseError(f"PLT0 data too short ({len(data)} bytes, expected at least 64 bytes).")
        if data[:4] != b"PLT0":
            raise ParseError(f"Invalid PLT0 magic: {data[:4]!r}")
        hdr = PLT0HeaderStruct.from_bytes(data[:0x40])
        extracted_name = name
        if not extracted_name and hdr.string_offset != 0 and hdr.string_offset < len(data):
            str_addr = hdr.string_offset
            end = data.find(b"\x00", str_addr)
            if end != -1:
                extracted_name = data[str_addr:end].decode("ascii", errors="replace")

        palette_bytes = data[hdr.header_len:hdr.section_size] if hdr.section_size <= len(data) else data[hdr.header_len:]
        return cls(
            name=extracted_name,
            format_id=hdr.format_id,
            num_entries=hdr.num_entries,
            data=palette_bytes,
            version=hdr.version,
        )

    def summary(self) -> str:
        return (
            f"PLT0 '{self.name}':\n"
            f"  Format:  {self.format_name} (ID {self.format_id})\n"
            f"  Entries: {self.num_entries}\n"
            f"  Size:    {len(self.data)} bytes"
        )

    def __repr__(self) -> str:
        return f"<PLT0Palette '{self.name}' {self.num_entries} entries {self.format_name}>"


class BRRESFile(MioRomResult):
    """
    Nintendo Wii NW4R BRRES (Binary Revolution Resource) Container.
    Maintains textures (TEX0), palettes (PLT0), and non-texture sections
    (3DModels MDL0, CHR0, CLR0, PAT0, etc.) with byte-exact fidelity.
    """

    MAGIC = b"bres"

    def __init__(
        self,
        textures: Optional[Dict[str, TEX0Image]] = None,
        palettes: Optional[Dict[str, PLT0Palette]] = None,
        other_sections: Optional[Dict[str, Dict[str, bytes]]] = None,
        version: int = 0,
        byte_order: int = 0xFEFF,
    ):
        self.textures: Dict[str, TEX0Image] = textures or {}
        self.palettes: Dict[str, PLT0Palette] = palettes or {}
        self.other_sections: Dict[str, Dict[str, bytes]] = other_sections or {}
        self.version = version
        self.byte_order = byte_order
        self._folder_order: List[str] = []

    @classmethod
    def from_bytes(cls, data: bytes) -> BRRESFile:
        if len(data) < 0x18:
            raise ParseError(f"BRRES data too short ({len(data)} bytes).")
        if data[:4] != cls.MAGIC:
            raise ParseError(f"Invalid BRRES magic: {data[:4]!r}, expected {cls.MAGIC!r}")

        hdr = BRRESHeaderStruct.from_bytes(data[:0x10])
        root_off = hdr.root_offset
        if root_off + 8 > len(data):
            raise ParseError(f"Invalid root offset {root_off} in BRRES archive.")

        root_hdr = BRRESRootHeaderStruct.from_bytes(data[root_off:root_off + 8])
        if root_hdr.magic != b"root":
            raise ParseError(f"Invalid root magic: {root_hdr.magic!r}, expected b'root'")

        master_group_off = root_off + 8
        master_group = BresIndexGroup.from_bytes(data, offset=master_group_off)

        textures: Dict[str, TEX0Image] = {}
        palettes: Dict[str, PLT0Palette] = {}
        other_sections: Dict[str, Dict[str, bytes]] = {}
        folder_order: List[str] = []

        for folder_entry in master_group.entries[1:]:
            folder_name = folder_entry.name
            folder_order.append(folder_name)
            child_group_off = master_group_off + folder_entry.data_offset
            if child_group_off >= len(data):
                continue
            child_group = BresIndexGroup.from_bytes(data, offset=child_group_off)

            for asset_entry in child_group.entries[1:]:
                asset_name = asset_entry.name
                payload_off = child_group_off + asset_entry.data_offset
                if payload_off >= len(data):
                    continue

                magic = data[payload_off:payload_off + 4]
                sec_size = 0
                if payload_off + 8 <= len(data):
                    sec_size_reader = BinaryReader(data[payload_off + 4:payload_off + 8], endian=">")
                    sec_size = sec_size_reader.read_u32()

                if sec_size == 0 or payload_off + sec_size > len(data):
                    sec_data = data[payload_off:]
                else:
                    sec_data = data[payload_off:payload_off + sec_size]

                if magic == b"TEX0":
                    tex = TEX0Image.from_bytes(sec_data, name=asset_name)
                    textures[asset_name] = tex
                elif magic == b"PLT0":
                    plt = PLT0Palette.from_bytes(sec_data, name=asset_name)
                    palettes[asset_name] = plt
                else:
                    if folder_name not in other_sections:
                        other_sections[folder_name] = {}
                    other_sections[folder_name][asset_name] = sec_data

        for t_name, tex in textures.items():
            if tex.is_paletted() and not tex.palette_data:
                if t_name in palettes:
                    tex.palette_data = palettes[t_name].data
                    tex.palette_format = palettes[t_name].format_id

        inst = cls(
            textures=textures,
            palettes=palettes,
            other_sections=other_sections,
            version=hdr.version,
            byte_order=hdr.bom,
        )
        inst._folder_order = folder_order
        return inst

    @classmethod
    def from_file(cls, filepath: str) -> BRRESFile:
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def get_texture(self, name: str) -> TEX0Image:
        if name not in self.textures:
            raise KeyError(f"Texture '{name}' not found in BRRES archive. Available: {list(self.textures.keys())}")
        return self.textures[name]

    def set_texture(
        self,
        name: str,
        img_or_tex0: Union[TEX0Image, Any],
        format_id: Optional[int] = None,
    ) -> None:
        """
        Replaces or inserts a texture in the BRRES archive.
        Preserves existing format if format_id is None and img_or_tex0 is not a TEX0Image.
        """
        if isinstance(img_or_tex0, TEX0Image):
            img_or_tex0.name = name
            self.textures[name] = img_or_tex0
            if img_or_tex0.palette_data:
                self.palettes[name] = PLT0Palette(
                    name=name,
                    format_id=img_or_tex0.palette_format,
                    num_entries=len(img_or_tex0.palette_data) // 2,
                    data=img_or_tex0.palette_data,
                )
        else:
            target_format = format_id
            if target_format is None and name in self.textures:
                target_format = self.textures[name].format_id
            if target_format is None:
                target_format = 14  # default CMPR

            tex = TEX0Image.from_image(img_or_tex0, name=name, format_id=target_format)
            self.textures[name] = tex
            if tex.palette_data:
                self.palettes[name] = PLT0Palette(
                    name=name,
                    format_id=tex.palette_format,
                    num_entries=len(tex.palette_data) // 2,
                    data=tex.palette_data,
                )

    def to_bytes(self) -> bytes:
        writer = BinaryWriter(endian=">")

        folders_dict: Dict[str, List[Tuple[str, bytes]]] = {}
        if "3DModels(NW4R)" in self.other_sections:
            folders_dict["3DModels(NW4R)"] = list(self.other_sections["3DModels(NW4R)"].items())

        if self.textures:
            tex_items: List[Tuple[str, bytes]] = []
            for name, tex in self.textures.items():
                tex_items.append((name, tex.to_bytes()))
            folders_dict["Textures(NW4R)"] = tex_items

        if self.palettes:
            plt_items: List[Tuple[str, bytes]] = []
            for name, plt in self.palettes.items():
                plt_items.append((name, plt.to_bytes()))
            folders_dict["Palettes(NW4R)"] = plt_items

        for folder_name, items in self.other_sections.items():
            if folder_name not in folders_dict:
                folders_dict[folder_name] = list(items.items())

        # Determine order of folders
        ordered_names: List[str] = []
        if self._folder_order:
            for fn in self._folder_order:
                if fn in folders_dict and fn not in ordered_names:
                    ordered_names.append(fn)
        for fn in folders_dict:
            if fn not in ordered_names:
                ordered_names.append(fn)

        folders: List[Tuple[str, List[Tuple[str, bytes]]]] = [
            (fn, folders_dict[fn]) for fn in ordered_names if folders_dict[fn]
        ]

        master_group_off = 0x18

        def calc_group_size(names: List[str]) -> int:
            sz = 8 + (len(names) + 1) * 16
            for n in names:
                nb = n.encode("ascii", errors="replace")
                str_block = 4 + len(nb) + 1
                str_block = (str_block + 3) & ~3
                sz += str_block
            return sz

        folder_names = [f[0] for f in folders]
        master_group_size = calc_group_size(folder_names)

        child_group_offsets: List[int] = []
        curr_group_off = master_group_off + master_group_size
        for _, items in folders:
            child_group_offsets.append(curr_group_off)
            curr_group_off += calc_group_size([it[0] for it in items])

        payload_start_off = (curr_group_off + 31) & ~31
        root_size = payload_start_off - 0x10

        payload_offsets: List[List[int]] = []
        curr_payload_off = payload_start_off
        for f_idx, (_, items) in enumerate(folders):
            f_offsets: List[int] = []
            for _, item_bytes in items:
                curr_payload_off = (curr_payload_off + 31) & ~31
                f_offsets.append(curr_payload_off)
                curr_payload_off += len(item_bytes)
            payload_offsets.append(f_offsets)

        total_file_size = (curr_payload_off + 31) & ~31
        total_sections = sum(len(items) for _, items in folders)

        # 1. BRRES Header
        brres_hdr = BRRESHeaderStruct(
            magic=self.MAGIC,
            bom=self.byte_order,
            version=self.version,
            file_size=total_file_size,
            root_offset=0x10,
            num_sections=total_sections + 1,
        )
        writer.write_struct(brres_hdr)

        # 2. Root Header
        root_hdr = BRRESRootHeaderStruct(magic=b"root", size=root_size)
        writer.write_struct(root_hdr)

        # 3. Master IndexGroup
        master_items: List[Tuple[str, int]] = []
        for f_idx, (f_name, _) in enumerate(folders):
            rel_data_off = child_group_offsets[f_idx] - master_group_off
            master_items.append((f_name, rel_data_off))
        master_group = BresIndexGroup.build(master_items)
        writer.write_bytes(master_group.to_bytes())

        # 4. Child IndexGroups
        for f_idx, (f_name, items) in enumerate(folders):
            c_group_off = child_group_offsets[f_idx]
            child_items: List[Tuple[str, int]] = []
            for it_idx, (it_name, _) in enumerate(items):
                rel_data_off = payload_offsets[f_idx][it_idx] - c_group_off
                child_items.append((it_name, rel_data_off))
            child_group = BresIndexGroup.build(child_items)
            writer.write_bytes(child_group.to_bytes())

        # Pad to payload start
        writer.align(32)

        # 5. Payloads
        for f_idx, (f_name, items) in enumerate(folders):
            for it_idx, (it_name, item_bytes) in enumerate(items):
                writer.align(32)
                p_off = payload_offsets[f_idx][it_idx]
                if f_name == "Textures(NW4R)" and it_name in self.textures:
                    tex = self.textures[it_name]
                    writer.write_bytes(tex.to_bytes(bres_offset=-p_off))
                elif f_name == "Palettes(NW4R)" and it_name in self.palettes:
                    plt = self.palettes[it_name]
                    writer.write_bytes(plt.to_bytes(bres_offset=-p_off))
                else:
                    if len(item_bytes) >= 16 and item_bytes[:4].isalpha():
                        w_s32 = BinaryWriter(endian=">")
                        w_s32.write_s32(-p_off)
                        item_bytes = item_bytes[:12] + w_s32.to_bytes() + item_bytes[16:]
                    writer.write_bytes(item_bytes)

        writer.align(32)
        return writer.to_bytes()

    def save(self, filepath: str) -> None:
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())

    def summary(self) -> str:
        lines = [
            "=== Nintendo Wii BRRES Archive ===",
            f"Version:     {self.version}",
            f"Textures:    {len(self.textures)}",
        ]
        for name, tex in self.textures.items():
            lines.append(f"  - {tex.name} ({tex.width}x{tex.height}, {tex.format_name})")
        if self.palettes:
            lines.append(f"Palettes:    {len(self.palettes)}")
            for name, plt in self.palettes.items():
                lines.append(f"  - {plt.name} ({plt.num_entries} colors, {plt.format_name})")
        if self.other_sections:
            lines.append("Other Sections (preserved):")
            for folder, items in self.other_sections.items():
                lines.append(f"  - {folder}: {len(items)} items ({list(items.keys())})")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return (
            f"<BRRESFile textures={len(self.textures)} "
            f"palettes={len(self.palettes)} "
            f"other={sum(len(v) for v in self.other_sections.values())}>"
        )
