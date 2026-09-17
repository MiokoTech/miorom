"""
miorom.platforms.psp.pbp
~~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation Portable (PSP) EBOOT.PBP container unpacker/repacker,
GIM (Graphic Image Map) texture parser/synthesizer, and GE VRAM swizzle codec.

PBP files bundle executable binaries (DATA.PSP), game ISO/archives (DATA.PSAR),
metadata (PARAM.SFO), and GUI media assets (ICON0.PNG, PIC1.PNG) for PSP homebrew
and PS1 Classics.

GIM is Sony's standard image container for PSP games (textures, UI graphics, font sheets),
supporting hardware VRAM swizzled (micro-tiled 16x8 byte block) and linear pixel orders,
indexed CLUT palettes (Index4, Index8), and direct color formats (RGBA8888, RGBA4444, RGBA5551, RGB565).
"""

import io
import os
from enum import IntEnum
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.core import schema
from miorom.errors import ParseError
from miorom.graphics.palette import Color, Palette
from miorom.graphics.png_codec import PNGCodec, PNGColorType, PNGImage
from miorom.platforms.psp.sfo import SFOFile
from miorom.result import MioRomResult

try:
    from PIL import Image

    HAS_PIL = True
except ImportError:
    HAS_PIL = False

PBP_MAGIC = b"\x00PBP"
PBP_HEADER_SIZE = 40

PBP_SECTION_NAMES = [
    "PARAM.SFO",
    "ICON0.PNG",
    "ICON1.PMF",
    "PIC0.PNG",
    "PIC1.PNG",
    "SND0.AT3",
    "DATA.PSP",
    "DATA.PSAR",
]

# GIM Chunk Constants (16-byte magic)
GIM_MAGIC = b"MIG.00.1PSP\x00\x00\x00\x00\x00"

GIM_CHUNK_ROOT = 0x02
GIM_CHUNK_PICTURE = 0x03
GIM_CHUNK_IMAGE = 0x04
GIM_CHUNK_PALETTE = 0x05
GIM_CHUNK_SEQUENCE = 0x06
GIM_CHUNK_FILE_END = 0xFF


class GIMFormat(IntEnum):
    """Sony PSP GIM texture pixel color format identifiers."""

    RGBA5650 = 0x00  # 16-bit direct RGB (R5, G6, B5, A0)
    RGBA5551 = 0x01  # 16-bit direct RGBA (R5, G5, B5, A1)
    RGBA4444 = 0x02  # 16-bit direct RGBA (R4, G4, B4, A4)
    RGBA8888 = 0x03  # 32-bit true color RGBA (R8, G8, B8, A8)
    INDEX4 = 0x04  # 4-bit indexed color with 16-color CLUT
    INDEX8 = 0x05  # 8-bit indexed color with 256-color CLUT
    INDEX16 = 0x06  # 16-bit indexed color
    INDEX32 = 0x07  # 32-bit indexed color


class GIMPixelOrder(IntEnum):
    """Memory layout order for PSP GIM texture pixels."""

    NORMAL = 0  # Linear raster row-major layout
    SWIZZLED = 1  # PSP GE micro-tiled 16x8 byte block layout


# ==============================================================================
# PSP Hardware GE VRAM Swizzle & Unswizzle Codecs
# ==============================================================================


def psp_swizzle(
    data: bytes,
    width: int,
    height: int,
    bpp: int,
    pitch_align: int = 16,
) -> bytes:
    """
    Swizzles a linear texture buffer into Sony PSP GE (Graphics Engine) VRAM micro-tiled format.

    PSP GE organizes textures in micro-tile blocks of 16 bytes wide by 8 rows tall (128 bytes/block).
    This function operates with zero external dependencies and supports 4bpp, 8bpp, 16bpp, and 32bpp.

    :param data: Linear pixel bytes (either tight width*height or aligned stride).
    :param width: Texture width in pixels.
    :param height: Texture height in pixels.
    :param bpp: Bits per pixel (4, 8, 16, 32).
    :param pitch_align: Row pitch byte alignment (default 16 bytes).
    :return: Swizzled bytearray payload aligned to 128-byte block boundaries.
    """
    row_bytes = (width * bpp + 7) // 8
    pitch = (row_bytes + (pitch_align - 1)) & ~(pitch_align - 1)
    aligned_h = (height + 7) & ~7
    blocks_per_row = max(1, pitch // 16)
    out_size = pitch * aligned_h
    out = bytearray(out_size)

    # Determine input row stride
    in_stride = pitch if len(data) >= pitch * height else row_bytes

    for y in range(height):
        block_y = y // 8
        in_block_y = y % 8
        in_row_start = y * in_stride

        for bx in range(row_bytes):
            block_x = bx // 16
            in_block_x = bx % 16
            block_idx = block_y * blocks_per_row + block_x
            swizzled_offset = block_idx * 128 + in_block_y * 16 + in_block_x
            src_offset = in_row_start + bx

            if src_offset < len(data) and swizzled_offset < out_size:
                out[swizzled_offset] = data[src_offset]

    return bytes(out)


def psp_unswizzle(
    data: bytes,
    width: int,
    height: int,
    bpp: int,
    pitch_align: int = 16,
    crop_to_dims: bool = False,
) -> bytes:
    """
    Unswizzles a Sony PSP GE micro-tiled VRAM buffer into linear row-major order.

    :param data: Swizzled pixel bytes from PSP GE or GIM file.
    :param width: Texture width in pixels.
    :param height: Texture height in pixels.
    :param bpp: Bits per pixel (4, 8, 16, 32).
    :param pitch_align: Row pitch byte alignment (default 16 bytes).
    :param crop_to_dims: If True, crops output to tight `(width*bpp+7)//8 * height`.
                         If False, returns full `pitch * aligned_height` buffer.
    :return: Unswizzled linear pixel bytes.
    """
    row_bytes = (width * bpp + 7) // 8
    pitch = (row_bytes + (pitch_align - 1)) & ~(pitch_align - 1)
    aligned_h = (height + 7) & ~7
    blocks_per_row = max(1, pitch // 16)

    out_stride = row_bytes if crop_to_dims else pitch
    out_size = out_stride * (height if crop_to_dims else aligned_h)
    out = bytearray(out_size)

    for y in range(height):
        block_y = y // 8
        in_block_y = y % 8
        out_row_start = y * out_stride

        for bx in range(row_bytes):
            block_x = bx // 16
            in_block_x = bx % 16
            block_idx = block_y * blocks_per_row + block_x
            swizzled_offset = block_idx * 128 + in_block_y * 16 + in_block_x

            if swizzled_offset < len(data):
                out_offset = out_row_start + bx
                if out_offset < out_size:
                    out[out_offset] = data[swizzled_offset]

    return bytes(out)


# ==============================================================================
# Helper Color Transcoders
# ==============================================================================


def _decode_color_16(fmt: GIMFormat, raw: bytes, offset: int) -> Tuple[int, int, int, int]:
    val = schema.unpack_from("<H", raw, offset)[0]
    if fmt == GIMFormat.RGBA5551:
        r = ((val >> 0) & 0x1F) * 255 // 31
        g = ((val >> 5) & 0x1F) * 255 // 31
        b = ((val >> 10) & 0x1F) * 255 // 31
        a = 255 if ((val >> 15) & 1) else 0
        return r, g, b, a
    elif fmt == GIMFormat.RGBA4444:
        r = ((val >> 0) & 0x0F) * 17
        g = ((val >> 4) & 0x0F) * 17
        b = ((val >> 8) & 0x0F) * 17
        a = ((val >> 12) & 0x0F) * 17
        return r, g, b, a
    elif fmt == GIMFormat.RGBA5650:
        r = ((val >> 0) & 0x1F) * 255 // 31
        g = ((val >> 5) & 0x3F) * 255 // 63
        b = ((val >> 11) & 0x1F) * 255 // 31
        return r, g, b, 255
    return 0, 0, 0, 255


def _encode_color_16(fmt: GIMFormat, r: int, g: int, b: int, a: int) -> int:
    if fmt == GIMFormat.RGBA5551:
        a_bit = 1 if a >= 128 else 0
        return (
            ((r * 31 // 255) & 0x1F)
            | (((g * 31 // 255) & 0x1F) << 5)
            | (((b * 31 // 255) & 0x1F) << 10)
            | (a_bit << 15)
        )
    elif fmt == GIMFormat.RGBA4444:
        return (
            ((r // 17) & 0x0F)
            | (((g // 17) & 0x0F) << 4)
            | (((b // 17) & 0x0F) << 8)
            | (((a // 17) & 0x0F) << 12)
        )
    elif fmt == GIMFormat.RGBA5650:
        return (
            ((r * 31 // 255) & 0x1F)
            | (((g * 63 // 255) & 0x3F) << 5)
            | (((b * 31 // 255) & 0x1F) << 11)
        )
    return 0


# ==============================================================================
# GIMImage Class
# ==============================================================================


class GIMImage(MioRomResult):
    """
    Parser, builder, and surgical editor for Sony PSP GIM (Graphic Image Map) textures.

    Supports reading, writing, unswizzling/swizzling, and surgical sub-region patching
    for Japanese PSP dialogue font sheets, UI textures, and game art.
    """

    def __init__(
        self,
        width: int = 0,
        height: int = 0,
        format: GIMFormat = GIMFormat.RGBA8888,
        pixel_order: GIMPixelOrder = GIMPixelOrder.NORMAL,
        pixel_data: Optional[Union[bytes, bytearray]] = None,
        clut_palettes: Optional[List[Palette]] = None,
        pitch_align: int = 16,
        height_align: int = 8,
    ):
        self.width = width
        self.height = height
        self.format = format
        self.pixel_order = pixel_order
        self.pixel_data = bytearray(pixel_data) if pixel_data else bytearray()
        self.clut_palettes: List[Palette] = clut_palettes if clut_palettes else []
        self.pitch_align = pitch_align
        self.height_align = height_align

    @property
    def bpp(self) -> int:
        """Returns bits per pixel corresponding to current format."""
        mapping = {
            GIMFormat.RGBA8888: 32,
            GIMFormat.RGBA5551: 16,
            GIMFormat.RGBA4444: 16,
            GIMFormat.RGBA5650: 16,
            GIMFormat.INDEX8: 8,
            GIMFormat.INDEX4: 4,
            GIMFormat.INDEX16: 16,
            GIMFormat.INDEX32: 32,
        }
        return mapping.get(self.format, 32)

    @property
    def palette(self) -> Optional[Palette]:
        """Returns primary CLUT palette if available."""
        return self.clut_palettes[0] if self.clut_palettes else None

    @classmethod
    def from_bytes(cls, data: bytes) -> "GIMImage":
        """
        Parses a Sony PSP GIM binary file buffer.
        Traverses Root (0x02), Picture (0x03), Image (0x04), and Palette (0x05) chunks.
        """
        if len(data) < 16:
            raise ParseError("Data too small for GIM header (minimum 16 bytes).")

        start_offset = 0
        if data[:12] == b"MIG.00.1PSP\x00":
            start_offset = 16
        else:
            first_chunk = schema.unpack_from("<H", data, 0)[0]
            if first_chunk not in (GIM_CHUNK_ROOT, GIM_CHUNK_PICTURE, GIM_CHUNK_IMAGE):
                raise ParseError(f"Invalid GIM signature: {data[:12]!r}")

        parsed_image: Optional[GIMImage] = None
        palettes: List[Palette] = []

        def _traverse_chunks(offset: int, limit: int):
            nonlocal parsed_image, palettes
            curr = offset

            while curr + 16 <= limit:
                chunk_type, _, chunk_size, next_chunk_off, payload_off = schema.unpack_from(
                    "<HHIII", data, curr
                )

                if chunk_size < 16:
                    break

                payload_start = curr + payload_off
                chunk_end = curr + chunk_size

                if chunk_type in (GIM_CHUNK_ROOT, GIM_CHUNK_PICTURE):
                    # Recurse into container children
                    _traverse_chunks(payload_start, min(chunk_end, limit))

                elif chunk_type == GIM_CHUNK_IMAGE:
                    if payload_start + 48 <= limit:
                        hdr = schema.unpack_from("<12H", data, payload_start)
                        img_format = GIMFormat(hdr[2]) if hdr[2] in GIMFormat._value2member_map_ else GIMFormat.RGBA8888
                        img_order = GIMPixelOrder(hdr[3]) if hdr[3] in (0, 1) else GIMPixelOrder.NORMAL
                        img_w = hdr[4]
                        img_h = hdr[5]
                        pitch_align = hdr[7] or 16
                        height_align = hdr[8] or 8

                        frame_off_rel = schema.unpack_from("<I", data, payload_start + 24)[0]
                        img_data_size = schema.unpack_from("<I", data, payload_start + 32)[0]

                        # Locate pixel data start
                        if frame_off_rel > 0 and payload_start + frame_off_rel + 4 <= limit:
                            first_frame_rel = schema.unpack_from(
                                "<I", data, payload_start + frame_off_rel
                            )[0]
                            pix_start = payload_start + first_frame_rel
                        else:
                            pix_start = payload_start + 0x40

                        pix_end = pix_start + img_data_size if img_data_size > 0 else chunk_end
                        if pix_end > limit:
                            pix_end = limit

                        raw_pixels = data[pix_start:pix_end]
                        parsed_image = cls(
                            width=img_w,
                            height=img_h,
                            format=img_format,
                            pixel_order=img_order,
                            pixel_data=raw_pixels,
                            pitch_align=pitch_align,
                            height_align=height_align,
                        )

                elif chunk_type == GIM_CHUNK_PALETTE:
                    if payload_start + 48 <= limit:
                        pal_hdr = schema.unpack_from("<9H", data, payload_start)
                        pal_fmt = GIMFormat(pal_hdr[2]) if pal_hdr[2] in GIMFormat._value2member_map_ else GIMFormat.RGBA8888
                        colors_per_pal = pal_hdr[4]
                        pal_count = pal_hdr[5] or 1

                        frame_off_rel = schema.unpack_from("<I", data, payload_start + 24)[0]
                        if frame_off_rel > 0 and payload_start + frame_off_rel + 4 <= limit:
                            first_frame_rel = schema.unpack_from(
                                "<I", data, payload_start + frame_off_rel
                            )[0]
                            pal_start = payload_start + first_frame_rel
                        else:
                            pal_start = payload_start + 0x40

                        # Decode CLUT palettes
                        color_step = 4 if pal_fmt == GIMFormat.RGBA8888 else 2
                        for p_idx in range(pal_count):
                            p_colors: List[Color] = []
                            base = pal_start + p_idx * colors_per_pal * color_step
                            for c_idx in range(colors_per_pal):
                                c_off = base + c_idx * color_step
                                if c_off + color_step <= limit:
                                    if pal_fmt == GIMFormat.RGBA8888:
                                        p_colors.append(
                                            Color(
                                                data[c_off],
                                                data[c_off + 1],
                                                data[c_off + 2],
                                                data[c_off + 3],
                                            )
                                        )
                                    else:
                                        r, g, b, a = _decode_color_16(pal_fmt, data, c_off)
                                        p_colors.append(Color(r, g, b, a))
                            if p_colors:
                                palettes.append(Palette(p_colors))

                # Advance to next sibling
                advance = next_chunk_off if next_chunk_off >= 16 else chunk_size
                curr += advance

        _traverse_chunks(start_offset, len(data))

        if parsed_image is None:
            raise ParseError("No valid GIM Image chunk (0x04) found in data.")

        parsed_image.clut_palettes = palettes
        return parsed_image

    @classmethod
    def from_file(cls, path: str) -> "GIMImage":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        """
        Synthesizes this GIMImage into a compliant, deterministic Sony PSP GIM binary.
        Generates Root -> Picture -> Image (and Palette if indexed) chunks.
        """
        # 1. Palette Chunk (if indexed with CLUT)
        pal_chunk_bytes = bytearray()
        if self.format in (GIMFormat.INDEX4, GIMFormat.INDEX8) and self.clut_palettes:
            pal_colors = self.clut_palettes[0]
            num_colors = 16 if self.format == GIMFormat.INDEX4 else 256
            pal_color_bytes = bytearray()
            for i in range(num_colors):
                if i < len(pal_colors):
                    c = pal_colors[i]
                    pal_color_bytes.extend(bytes([c.r, c.g, c.b, c.a]))
                else:
                    pal_color_bytes.extend(b"\x00\x00\x00\x00")

            # Align palette data to 16 bytes
            pad_pal = (16 - (len(pal_color_bytes) % 16)) % 16
            pal_color_bytes.extend(b"\x00" * pad_pal)

            # Palette header (0x30 bytes)
            pal_hdr = bytearray(0x30)
            schema.pack_into(
                "<12H",
                pal_hdr,
                0,
                0x30,  # header_size
                0,  # ref
                GIMFormat.RGBA8888,  # palette color format
                0,  # linear
                num_colors,  # colors per palette
                1,  # palette count
                32,  # bpp
                16,  # pitch align
                8,  # height align
                2,  # dim count
                0,  # reserved
                1,  # frames
            )
            schema.pack_into(
                "<IIII",
                pal_hdr,
                24,
                0x30,  # frame table offset
                0,  # mipmap offset
                len(pal_color_bytes),  # data size
                len(pal_color_bytes),  # frame size
            )

            # Palette frame table (16 bytes): points to 0x40 (offset from header start)
            pal_frame_table = bytearray(16)
            schema.pack_into("<I", pal_frame_table, 0, 0x40)

            pal_payload = pal_hdr + pal_frame_table + pal_color_bytes
            pal_total_size = 16 + len(pal_payload)
            pal_chunk_header = bytearray(16)
            schema.pack_into("<HHIII", pal_chunk_header, 0, GIM_CHUNK_PALETTE, 0, pal_total_size, pal_total_size, 16)
            pal_chunk_bytes = pal_chunk_header + pal_payload

        # 2. Image Chunk
        img_payload_data = bytearray(self.pixel_data)
        pad_img = (16 - (len(img_payload_data) % 16)) % 16
        img_payload_data.extend(b"\x00" * pad_img)

        img_hdr = bytearray(0x30)
        schema.pack_into(
            "<12H",
            img_hdr,
            0,
            0x30,  # header_size
            0,  # ref
            int(self.format),
            int(self.pixel_order),
            self.width,
            self.height,
            self.bpp,
            self.pitch_align,
            self.height_align,
            2,  # dim count
            0,  # reserved
            1,  # frames
        )
        schema.pack_into(
            "<IIII",
            img_hdr,
            24,
            0x30,  # frame table offset
            0,  # mipmap offset
            len(img_payload_data),  # data size
            len(img_payload_data),  # frame size
        )

        img_frame_table = bytearray(16)
        schema.pack_into("<I", img_frame_table, 0, 0x40)

        img_payload = img_hdr + img_frame_table + img_payload_data
        img_total_size = 16 + len(img_payload)
        img_chunk_header = bytearray(16)
        schema.pack_into("<HHIII", img_chunk_header, 0, GIM_CHUNK_IMAGE, 0, img_total_size, img_total_size, 16)
        img_chunk_bytes = img_chunk_header + img_payload

        # 3. Picture Chunk
        pic_payload = img_chunk_bytes + pal_chunk_bytes
        pic_total_size = 16 + len(pic_payload)
        pic_chunk_header = bytearray(16)
        schema.pack_into("<HHIII", pic_chunk_header, 0, GIM_CHUNK_PICTURE, 0, pic_total_size, pic_total_size, 16)
        pic_chunk_bytes = pic_chunk_header + pic_payload

        # 4. Root Chunk
        root_payload = pic_chunk_bytes
        root_total_size = 16 + len(root_payload)
        root_chunk_header = bytearray(16)
        schema.pack_into("<HHIII", root_chunk_header, 0, GIM_CHUNK_ROOT, 0, root_total_size, root_total_size, 16)
        root_chunk_bytes = root_chunk_header + root_payload

        return GIM_MAGIC + bytes(root_chunk_bytes)

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    # ==========================================================================
    # Swizzle State Mutators
    # ==========================================================================

    def unswizzle(self) -> "GIMImage":
        """Converts pixel layout in-place to linear order if currently swizzled."""
        if self.pixel_order == GIMPixelOrder.SWIZZLED:
            self.pixel_data = bytearray(
                psp_unswizzle(
                    self.pixel_data,
                    self.width,
                    self.height,
                    self.bpp,
                    self.pitch_align,
                    crop_to_dims=False,
                )
            )
            self.pixel_order = GIMPixelOrder.NORMAL
        return self

    def swizzle(self) -> "GIMImage":
        """Converts pixel layout in-place to PSP GE micro-tiled order if linear."""
        if self.pixel_order == GIMPixelOrder.NORMAL:
            self.pixel_data = bytearray(
                psp_swizzle(
                    self.pixel_data,
                    self.width,
                    self.height,
                    self.bpp,
                    self.pitch_align,
                )
            )
            self.pixel_order = GIMPixelOrder.SWIZZLED
        return self

    # ==========================================================================
    # High-Level Image Rendering & Ingestion
    # ==========================================================================

    def to_image(self, palette_index: int = 0) -> Any:
        """
        Renders the GIM image to an RGBA image.
        Returns a PIL Image when Pillow is installed, or a PNGImage (zero-dependency fallback).
        """
        if self.pixel_order == GIMPixelOrder.SWIZZLED:
            linear_bytes = psp_unswizzle(
                self.pixel_data,
                self.width,
                self.height,
                self.bpp,
                self.pitch_align,
                crop_to_dims=False,
            )
        else:
            linear_bytes = bytes(self.pixel_data)

        row_bytes = (self.width * self.bpp + 7) // 8
        pitch = (row_bytes + (self.pitch_align - 1)) & ~(self.pitch_align - 1)
        rgba_out = bytearray(self.width * self.height * 4)

        pal = (
            self.clut_palettes[palette_index]
            if (self.clut_palettes and palette_index < len(self.clut_palettes))
            else None
        )

        for y in range(self.height):
            row_start = y * pitch
            out_row_start = y * (self.width * 4)

            if self.format == GIMFormat.RGBA8888:
                for x in range(self.width):
                    in_off = row_start + x * 4
                    out_off = out_row_start + x * 4
                    if in_off + 4 <= len(linear_bytes):
                        rgba_out[out_off : out_off + 4] = linear_bytes[in_off : in_off + 4]

            elif self.format in (GIMFormat.RGBA5551, GIMFormat.RGBA4444, GIMFormat.RGBA5650):
                for x in range(self.width):
                    in_off = row_start + x * 2
                    out_off = out_row_start + x * 4
                    if in_off + 2 <= len(linear_bytes):
                        r, g, b, a = _decode_color_16(self.format, linear_bytes, in_off)
                        rgba_out[out_off : out_off + 4] = bytes([r, g, b, a])

            elif self.format == GIMFormat.INDEX8:
                for x in range(self.width):
                    in_off = row_start + x
                    out_off = out_row_start + x * 4
                    if in_off < len(linear_bytes):
                        idx = linear_bytes[in_off]
                        if pal and idx < len(pal):
                            c = pal[idx]
                            rgba_out[out_off : out_off + 4] = bytes([c.r, c.g, c.b, c.a])
                        else:
                            rgba_out[out_off : out_off + 4] = bytes([idx, idx, idx, 255])

            elif self.format == GIMFormat.INDEX4:
                for x in range(self.width):
                    byte_off = row_start + (x // 2)
                    out_off = out_row_start + x * 4
                    if byte_off < len(linear_bytes):
                        b = linear_bytes[byte_off]
                        idx = (b & 0x0F) if (x % 2 == 0) else ((b >> 4) & 0x0F)
                        if pal and idx < len(pal):
                            c = pal[idx]
                            rgba_out[out_off : out_off + 4] = bytes([c.r, c.g, c.b, c.a])
                        else:
                            val = idx * 17
                            rgba_out[out_off : out_off + 4] = bytes([val, val, val, 255])

        if HAS_PIL:
            return Image.frombytes("RGBA", (self.width, self.height), bytes(rgba_out))

        return PNGImage(
            width=self.width,
            height=self.height,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=bytes(rgba_out),
        )

    def to_png(self, output_path: str, palette_index: int = 0) -> str:
        """Renders GIM to a PNG file on disk (zero-dependency)."""
        img = self.to_image(palette_index=palette_index)
        if hasattr(img, "save"):
            img.save(output_path, format="PNG")
        else:
            png_bytes = PNGCodec.encode_rgba(img.width, img.height, img.to_rgba_bytes())
            with open(output_path, "wb") as f:
                f.write(png_bytes)
        return output_path

    @classmethod
    def from_image(
        cls,
        image_or_path: Any,
        format: GIMFormat = GIMFormat.RGBA8888,
        swizzle: bool = True,
        pitch_align: int = 16,
        height_align: int = 8,
    ) -> "GIMImage":
        """
        Creates a GIMImage from a file path, PIL Image, or PNGImage.
        Zero-dependency (works cleanly without Pillow).
        """
        if isinstance(image_or_path, str):
            if HAS_PIL:
                img = Image.open(image_or_path).convert("RGBA")
                width, height = img.size
                get_pixel = img.getpixel
            else:
                with open(image_or_path, "rb") as f:
                    _w, _h, rgba = PNGCodec.png_to_rgba(f.read())
                width, height = _w, _h

                def get_pixel(xy):
                    off = (xy[1] * _w + xy[0]) * 4
                    return tuple(rgba[off : off + 4])

        elif HAS_PIL and isinstance(image_or_path, Image.Image):
            img = image_or_path.convert("RGBA")
            width, height = img.size
            get_pixel = img.getpixel
        elif isinstance(image_or_path, PNGImage):
            width, height = image_or_path.width, image_or_path.height
            rgba = image_or_path.to_rgba_bytes()

            def get_pixel(xy):
                off = (xy[1] * width + xy[0]) * 4
                return tuple(rgba[off : off + 4])

        elif hasattr(image_or_path, "convert"):
            img = image_or_path.convert("RGBA")
            width, height = img.size
            get_pixel = img.getpixel
        else:
            raise TypeError(f"Expected file path, PIL Image, or PNGImage, got {type(image_or_path)}")

        bpp_map = {
            GIMFormat.RGBA8888: 32,
            GIMFormat.RGBA5551: 16,
            GIMFormat.RGBA4444: 16,
            GIMFormat.RGBA5650: 16,
            GIMFormat.INDEX8: 8,
            GIMFormat.INDEX4: 4,
        }
        bpp = bpp_map.get(format, 32)
        row_bytes = (width * bpp + 7) // 8
        pitch = (row_bytes + (pitch_align - 1)) & ~(pitch_align - 1)
        aligned_h = (height + (height_align - 1)) & ~(height_align - 1)

        palettes: List[Palette] = []
        linear_bytes = bytearray(pitch * aligned_h)

        if format in (GIMFormat.INDEX4, GIMFormat.INDEX8):
            max_colors = 16 if format == GIMFormat.INDEX4 else 256
            unique_colors: List[Color] = []
            seen = set()
            for y in range(height):
                for x in range(width):
                    c = Color(*get_pixel((x, y)))
                    if c not in seen and len(unique_colors) < max_colors:
                        seen.add(c)
                        unique_colors.append(c)
            while len(unique_colors) < max_colors:
                unique_colors.append(Color(0, 0, 0, 0))
            pal = Palette(unique_colors)
            palettes = [pal]

            for y in range(height):
                row_start = y * pitch
                for x in range(width):
                    c = Color(*get_pixel((x, y)))
                    idx = pal.match_color(c)
                    if format == GIMFormat.INDEX8:
                        linear_bytes[row_start + x] = idx & 0xFF
                    else:
                        byte_off = row_start + (x // 2)
                        curr = linear_bytes[byte_off]
                        if x % 2 == 0:
                            linear_bytes[byte_off] = (curr & 0xF0) | (idx & 0x0F)
                        else:
                            linear_bytes[byte_off] = (curr & 0x0F) | ((idx & 0x0F) << 4)

        elif format == GIMFormat.RGBA8888:
            for y in range(height):
                row_start = y * pitch
                for x in range(width):
                    r, g, b, a = get_pixel((x, y))
                    linear_bytes[row_start + x * 4 : row_start + x * 4 + 4] = bytes([r, g, b, a])

        elif format in (GIMFormat.RGBA5551, GIMFormat.RGBA4444, GIMFormat.RGBA5650):
            for y in range(height):
                row_start = y * pitch
                for x in range(width):
                    r, g, b, a = get_pixel((x, y))
                    c16 = _encode_color_16(format, r, g, b, a)
                    schema.pack_into("<H", linear_bytes, row_start + x * 2, c16)

        if swizzle:
            pixel_data = bytearray(psp_swizzle(linear_bytes, width, height, bpp, pitch_align))
            order = GIMPixelOrder.SWIZZLED
        else:
            pixel_data = linear_bytes
            order = GIMPixelOrder.NORMAL

        return cls(
            width=width,
            height=height,
            format=format,
            pixel_order=order,
            pixel_data=pixel_data,
            clut_palettes=palettes,
            pitch_align=pitch_align,
            height_align=height_align,
        )

    # ==========================================================================
    # Surgical ROM Hacking Sub-Region Patching & Extraction
    # ==========================================================================

    def patch_region(
        self,
        x: int,
        y: int,
        patch: Any,
        palette_index: int = 0,
    ) -> None:
        """
        Surgically patches a sub-image (e.g. translated font glyph or UI button) at (x, y).

        If this texture is currently swizzled, this method transparently unswizzles,
        modifies the linear raster canvas, and swizzles back with zero data loss.

        :param x: Horizontal coordinate in pixels.
        :param y: Vertical coordinate in pixels.
        :param patch: PNGImage, PIL Image, GIMImage, or file path.
        :param palette_index: Target palette index to match colors against if indexed.
        """
        # Ingest patch image
        if isinstance(patch, str):
            if HAS_PIL:
                p_img = Image.open(patch).convert("RGBA")
                pw, ph = p_img.size
                get_patch_pixel = p_img.getpixel
            else:
                with open(patch, "rb") as f:
                    pw, ph, rgba = PNGCodec.png_to_rgba(f.read())

                def get_patch_pixel(xy):
                    off = (xy[1] * pw + xy[0]) * 4
                    return tuple(rgba[off : off + 4])
        elif isinstance(patch, GIMImage):
            rendered = patch.to_image(palette_index=0)
            return self.patch_region(x, y, rendered, palette_index=palette_index)
        elif isinstance(patch, PNGImage):
            pw, ph = patch.width, patch.height
            rgba = patch.to_rgba_bytes()

            def get_patch_pixel(xy):
                off = (xy[1] * pw + xy[0]) * 4
                return tuple(rgba[off : off + 4])
        elif HAS_PIL and isinstance(patch, Image.Image):
            p_img = patch.convert("RGBA")
            pw, ph = p_img.size
            get_patch_pixel = p_img.getpixel
        elif hasattr(patch, "convert"):
            p_img = patch.convert("RGBA")
            pw, ph = p_img.size
            get_patch_pixel = p_img.getpixel
        else:
            raise TypeError(f"Unsupported patch image type: {type(patch)}")

        if x < 0 or y < 0 or x + pw > self.width or y + ph > self.height:
            raise ValueError(
                f"Patch ({x}, {y}, {pw}, {ph}) exceeds image dimensions ({self.width}, {self.height})"
            )

        was_swizzled = self.pixel_order == GIMPixelOrder.SWIZZLED
        if was_swizzled:
            canvas = bytearray(
                psp_unswizzle(
                    self.pixel_data,
                    self.width,
                    self.height,
                    self.bpp,
                    self.pitch_align,
                    crop_to_dims=False,
                )
            )
        else:
            canvas = bytearray(self.pixel_data)

        row_bytes = (self.width * self.bpp + 7) // 8
        pitch = (row_bytes + (self.pitch_align - 1)) & ~(self.pitch_align - 1)
        pal = (
            self.clut_palettes[palette_index]
            if (self.clut_palettes and palette_index < len(self.clut_palettes))
            else None
        )

        for py in range(ph):
            target_y = y + py
            row_start = target_y * pitch
            for px in range(pw):
                target_x = x + px
                r, g, b, a = get_patch_pixel((px, py))

                if self.format == GIMFormat.RGBA8888:
                    off = row_start + target_x * 4
                    canvas[off : off + 4] = bytes([r, g, b, a])

                elif self.format in (GIMFormat.RGBA5551, GIMFormat.RGBA4444, GIMFormat.RGBA5650):
                    c16 = _encode_color_16(self.format, r, g, b, a)
                    schema.pack_into("<H", canvas, row_start + target_x * 2, c16)

                elif self.format == GIMFormat.INDEX8:
                    idx = pal.match_color(Color(r, g, b, a)) if pal else (r & 0xFF)
                    canvas[row_start + target_x] = idx & 0xFF

                elif self.format == GIMFormat.INDEX4:
                    idx = (pal.match_color(Color(r, g, b, a)) & 0x0F) if pal else (r & 0x0F)
                    byte_off = row_start + (target_x // 2)
                    curr = canvas[byte_off]
                    if target_x % 2 == 0:
                        canvas[byte_off] = (curr & 0xF0) | (idx & 0x0F)
                    else:
                        canvas[byte_off] = (curr & 0x0F) | ((idx & 0x0F) << 4)

        if was_swizzled:
            self.pixel_data = bytearray(
                psp_swizzle(canvas, self.width, self.height, self.bpp, self.pitch_align)
            )
        else:
            self.pixel_data = canvas

    def extract_region(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        palette_index: int = 0,
    ) -> Any:
        """
        Extracts an unswizzled sub-region of the GIM texture as an RGBA image.
        """
        if x < 0 or y < 0 or x + width > self.width or y + height > self.height:
            raise ValueError(
                f"Crop ({x}, {y}, {width}, {height}) exceeds image bounds ({self.width}, {self.height})"
            )

        full_img = self.to_image(palette_index=palette_index)
        crop_rgba = bytearray(width * height * 4)

        if hasattr(full_img, "crop"):
            return full_img.crop((x, y, x + width, y + height))

        # PNGImage fallback
        src_rgba = full_img.to_rgba_bytes()
        for cy in range(height):
            src_off = ((y + cy) * self.width + x) * 4
            dst_off = cy * (width * 4)
            crop_rgba[dst_off : dst_off + width * 4] = src_rgba[src_off : src_off + width * 4]

        return PNGImage(
            width=width,
            height=height,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=bytes(crop_rgba),
        )

    def summary(self) -> str:
        """Returns a formatted diagnostic summary of this GIM texture."""
        lines = [
            f"GIM Texture [{self.width}x{self.height}]",
            f"  Format: {self.format.name} ({self.bpp} bpp)",
            f"  Pixel Order: {self.pixel_order.name}",
            f"  Data Size: {len(self.pixel_data)} bytes (Pitch Align: {self.pitch_align})",
            f"  Palettes: {len(self.clut_palettes)} CLUT table(s)",
        ]
        if self.clut_palettes:
            lines.append(f"  Primary Palette Colors: {len(self.clut_palettes[0])}")
        return "\n".join(lines)


# ==============================================================================
# Sony PSP EBOOT.PBP Container Archive
# ==============================================================================


class PBPFile(MioRomResult):
    """
    Parser, extractor, and synthesizer for Sony PSP EBOOT.PBP container archives.
    """

    def __init__(self, sections: Optional[Dict[str, bytes]] = None, version: int = 0x00010000):
        self.version = version
        self.sections: Dict[str, bytes] = {}
        for name in PBP_SECTION_NAMES:
            self.sections[name] = b""
        if sections:
            for k, v in sections.items():
                self.sections[k.upper()] = bytes(v)

    @classmethod
    def from_bytes(cls, data: bytes) -> "PBPFile":
        """Parses a raw binary EBOOT.PBP buffer."""
        if len(data) < PBP_HEADER_SIZE:
            raise ParseError("Data too small for PBP header (minimum 40 bytes).")

        magic = data[:4]
        if magic != PBP_MAGIC:
            raise ParseError(f"Invalid PBP magic: {magic!r}, expected {PBP_MAGIC!r}")

        version = schema.unpack_from("<I", data, 4)[0]
        offsets = list(schema.unpack_from("<8I", data, 8))

        sections: Dict[str, bytes] = {}
        for i in range(8):
            name = PBP_SECTION_NAMES[i]
            start = offsets[i]
            end = offsets[i + 1] if i + 1 < 8 else len(data)

            if start < PBP_HEADER_SIZE or start > len(data):
                sections[name] = b""
            elif end < start:
                sections[name] = b""
            else:
                sections[name] = data[start:end]

        return cls(sections, version=version)

    @classmethod
    def from_file(cls, path: str) -> "PBPFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def get_section(self, name: str) -> bytes:
        """Returns payload bytes of specified PBP section."""
        return self.sections.get(name.upper(), b"")

    def set_section(self, name: str, data: bytes):
        """Sets payload bytes of specified PBP section."""
        self.sections[name.upper()] = bytes(data)

    @property
    def sfo(self) -> Optional[SFOFile]:
        """Convenience property parsing PARAM.SFO section if present."""
        sfo_data = self.get_section("PARAM.SFO")
        if len(sfo_data) >= 20 and sfo_data[:4] == b"\x00PSF":
            try:
                return SFOFile.from_bytes(sfo_data)
            except Exception:
                return None
        return None

    def get_icon(self) -> Optional[Any]:
        """Decodes ICON0.PNG to a PIL Image or PNGImage."""
        icon_data = self.get_section("ICON0.PNG")
        if not icon_data:
            return None
        if HAS_PIL:
            return Image.open(io.BytesIO(icon_data))
        return PNGCodec.decode(icon_data)

    def set_icon(self, image_or_bytes: Any) -> None:
        """Sets and encodes ICON0.PNG from raw bytes, PNGImage, or PIL Image."""
        if isinstance(image_or_bytes, (bytes, bytearray)):
            self.set_section("ICON0.PNG", bytes(image_or_bytes))
        elif isinstance(image_or_bytes, PNGImage):
            png_bytes = PNGCodec.encode_rgba(
                image_or_bytes.width, image_or_bytes.height, image_or_bytes.to_rgba_bytes()
            )
            self.set_section("ICON0.PNG", png_bytes)
        elif HAS_PIL and isinstance(image_or_bytes, Image.Image):
            buf = io.BytesIO()
            image_or_bytes.save(buf, format="PNG")
            self.set_section("ICON0.PNG", buf.getvalue())
        else:
            raise TypeError(f"Expected bytes, PNGImage, or PIL Image, got {type(image_or_bytes)}")

    def find_gim_textures(self) -> List[Tuple[str, int, GIMImage]]:
        """
        Scans all sections in this PBP archive for embedded GIM textures.
        Returns a list of (section_name, byte_offset, gim_instance).
        """
        results: List[Tuple[str, int, GIMImage]] = []
        sig = GIM_MAGIC[:12]  # b"MIG.00.1PSP\x00"

        for sec_name, payload in self.sections.items():
            if len(payload) < 16:
                continue
            offset = 0
            while offset < len(payload):
                idx = payload.find(sig, offset)
                if idx == -1:
                    break
                try:
                    gim = GIMImage.from_bytes(payload[idx:])
                    results.append((sec_name, idx, gim))
                    offset = idx + max(16, len(gim.pixel_data))
                except Exception:
                    offset = idx + 4

        return results

    def extract_all(self, output_dir: str):
        """Extracts all non-empty sections to directory on disk."""
        os.makedirs(output_dir, exist_ok=True)
        for name, data in self.sections.items():
            if len(data) > 0:
                out_path = os.path.join(output_dir, name)
                with open(out_path, "wb") as f:
                    f.write(data)

    def to_bytes(self) -> bytes:
        """Synthesizes all sections into a valid EBOOT.PBP binary."""
        offsets: List[int] = []
        curr_offset = PBP_HEADER_SIZE

        # Calculate offsets
        for name in PBP_SECTION_NAMES:
            offsets.append(curr_offset)
            curr_offset += len(self.sections.get(name, b""))

        out = bytearray(PBP_HEADER_SIZE)
        out[0:4] = PBP_MAGIC
        schema.pack_into("<I", out, 4, self.version)
        schema.pack_into("<8I", out, 8, *offsets)

        for name in PBP_SECTION_NAMES:
            out.extend(self.sections.get(name, b""))

        return bytes(out)

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def summary(self) -> str:
        """Returns a diagnostic summary of sections and metadata in this PBP."""
        lines = [f"EBOOT.PBP (v{hex(self.version)})"]
        sfo = self.sfo
        if sfo:
            title = sfo.get("TITLE", "Unknown")
            disc_id = sfo.get("DISC_ID", sfo.get("TITLE_ID", "Unknown"))
            lines.append(f"  Title: {title} [{disc_id}]")
        for name in PBP_SECTION_NAMES:
            size = len(self.sections.get(name, b""))
            if size > 0:
                lines.append(f"  {name:10}: {size:,} bytes")
        return "\n".join(lines)
