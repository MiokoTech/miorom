"""
miorom.platforms.wii.tpl
~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo TPL (Texture Palette Library) Parser and Builder.
Standard texture image container used in Nintendo GameCube and Wii titles
(e.g., Super Smash Bros. Melee, Mario Kart Double Dash, Super Mario Galaxy, Twilight Princess).
Pure Python, using MioROM declarative binary primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, U16, U32
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


class TPLHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = U32()
    num_images = U32()
    table_offset = U32()


class TPLImageTableEntryStruct(BinaryStruct):
    _endian = ">"
    image_header_offset = U32()
    palette_header_offset = U32()


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


def decode_gx_texture(raw: bytes, width: int, height: int, format_id: int) -> bytes:
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

    return bytes(out)


def encode_gx_texture(rgba: bytes, width: int, height: int, format_id: int) -> bytes:
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
                            c0, c1 = max(1, c_max + 1), c_min
                        else:
                            c0, c1 = c_max, c_min

                    bits = 0
                    for p_i, p in enumerate(block_pixels):
                        if p[3] < 128:
                            code = 3 if c0 <= c1 else 1
                        else:
                            d0 = abs(p[0] - max_p[0]) + abs(p[1] - max_p[1]) + abs(p[2] - max_p[2])
                            d1 = abs(p[0] - min_p[0]) + abs(p[1] - min_p[1]) + abs(p[2] - min_p[2])
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

    @property
    def format_name(self) -> str:
        return TPL_FORMAT_NAMES.get(self.format_id, f"Unknown (0x{self.format_id:X})")

    def __repr__(self) -> str:
        return (
            f"<TPLImage #{self.index} {self.width}x{self.height} "
            f"format={self.format_name} offset=0x{self.data_offset:06X} "
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
    def from_file(cls, filepath: str) -> "TPLFile":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "TPLFile":
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
        return decode_gx_texture(img.raw_data, img.width, img.height, img.format_id)

    def to_image(self, image_index: int = 0) -> "Image.Image":
        """
        Renders the specified TPL image to a PIL Image.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for TPLFile.to_image().")

        if image_index >= len(self.images):
            raise IndexError(f"Image index {image_index} out of range.")

        img = self.images[image_index]
        rgba = self.decode_rgba(image_index)
        return Image.frombytes("RGBA", (img.width, img.height), rgba)

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, "Image.Image"],
        format_id: int = 5,
    ) -> "TPLFile":
        """
        Creates a TPLFile container containing a single encoded image.
        Default format: 5 (RGB5A3).
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for TPLFile.from_image().")

        if isinstance(image_or_path, str):
            pil_img = Image.open(image_or_path)
        else:
            pil_img = image_or_path

        pil_img = pil_img.convert("RGBA")
        width, height = pil_img.size
        rgba_bytes = pil_img.tobytes()

        raw_data = encode_gx_texture(rgba_bytes, width, height, format_id)
        tpl_img = TPLImage(
            index=0,
            width=width,
            height=height,
            format_id=format_id,
            data_offset=0,
            raw_data=raw_data,
        )
        return cls(images=[tpl_img])

    def to_bytes(self) -> bytes:
        """
        Serializes the TPLFile back into standard Nintendo GameCube/Wii TPL binary format.
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

        # 3. Write Image Headers
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

        # 4. Write Texture Data
        data_offsets: List[int] = []
        for img in self.images:
            writer.align(32)
            data_offsets.append(writer.tell())
            writer.write_bytes(img.raw_data)

        # 5. Patch table and headers with actual offsets
        with writer.at(table_offset):
            for h_off in img_header_offsets:
                writer.write_struct(
                    TPLImageTableEntryStruct(image_header_offset=h_off, palette_header_offset=0)
                )

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
