"""
miorom.graphics.png_codec
~~~~~~~~~~~~~~~~~~~~~~~~~
Pure-Python PNG encoder/decoder using only the standard library (zlib).

This module provides a minimal but complete PNG I/O layer so that MioROM
graphics functions work without Pillow installed.  When Pillow *is* installed,
callers should prefer the richer ``ImageBridge`` API; this module is the
zero-dependency fallback.

Supported formats
-----------------
Encode
    * 8-bit Grayscale (color type 0)
    * 8-bit Grayscale+Alpha (color type 4)
    * 8-bit RGB  (color type 2)
    * 8-bit RGBA (color type 6)
    * 1/2/4/8-bit Indexed (color type 3) — with PLTE and optional tRNS

Decode
    * All PNG filter types (None, Sub, Up, Average, Paeth)
    * Color types: 0 (grayscale), 2 (RGB), 3 (indexed), 4 (gray+alpha), 6 (RGBA)
    * Bit depths: 1, 2, 4, 8 (16-bit depth is rejected with a clear error)
    * PLTE and tRNS chunks are handled

Limitations
-----------
* Interlaced PNG (Adam7) is not decoded.
* 16-bit channel depth is not supported on decode.
* Encoding always uses filter type 0 (None) for simplicity.
"""

from __future__ import annotations

import math
import zlib
from pathlib import Path
from typing import List, Optional, Tuple, Union

from miorom.core import schema
from miorom.errors import ParseError

__all__ = [
    "PNGColorType",
    "PNGImage",
    "PNGCodec",
]

# ---------------------------------------------------------------------------
# Color-type constants (same as PNG spec)
# ---------------------------------------------------------------------------

class PNGColorType:
    GRAYSCALE       = 0
    RGB             = 2
    INDEXED         = 3
    GRAYSCALE_ALPHA = 4
    RGBA            = 6


# ---------------------------------------------------------------------------
# Data container
# ---------------------------------------------------------------------------

class PNGImage:
    """
    Lightweight container returned by :meth:`PNGCodec.decode`.

    Attributes
    ----------
    width, height : int
        Image dimensions in pixels.
    color_type : int
        PNG color type (see :class:`PNGColorType`).
    bit_depth : int
        Bits per channel (1, 2, 4, or 8).
    pixels : bytes
        Unfiltered, uncompressed pixel data.  Layout depends on color_type:

        * Grayscale     → 1 byte/pixel  (8-bit) or bit-packed (1/2/4-bit)
        * Grayscale+α   → 2 bytes/pixel
        * RGB           → 3 bytes/pixel
        * RGBA          → 4 bytes/pixel
        * Indexed       → 1 byte/pixel (index into palette)

    palette : list[tuple[int,int,int]] or None
        RGB palette entries for indexed images; ``None`` otherwise.
    transparency : bytes or None
        Raw tRNS chunk data when present.
    """

    def __init__(
        self,
        width: int,
        height: int,
        color_type: int,
        bit_depth: int,
        pixels: bytes,
        palette: Optional[List[Tuple[int, int, int]]] = None,
        transparency: Optional[bytes] = None,
    ) -> None:
        self.width = width
        self.height = height
        self.color_type = color_type
        self.bit_depth = bit_depth
        self.pixels = pixels
        self.palette = palette
        self.transparency = transparency

    def __iter__(self):
        """Allow tuple unpacking: width, height, pixels, color_type = img."""
        yield self.width
        yield self.height
        yield self.pixels
        yield self.color_type

    # ------------------------------------------------------------------
    # Convenience conversions
    # ------------------------------------------------------------------

    def to_rgba_bytes(self) -> bytes:
        """Convert any supported color type to a flat RGBA byte buffer."""
        ct = self.color_type
        w, h = self.width, self.height
        px = self.pixels

        if ct == PNGColorType.RGBA:
            return px

        out = bytearray(w * h * 4)

        if ct == PNGColorType.RGB:
            for i in range(w * h):
                out[i * 4]     = px[i * 3]
                out[i * 4 + 1] = px[i * 3 + 1]
                out[i * 4 + 2] = px[i * 3 + 2]
                out[i * 4 + 3] = 255
            return bytes(out)

        if ct == PNGColorType.GRAYSCALE:
            if self.bit_depth == 8:
                for i in range(w * h):
                    v = px[i]
                    out[i * 4]     = v
                    out[i * 4 + 1] = v
                    out[i * 4 + 2] = v
                    out[i * 4 + 3] = 255
            else:
                # expand bit-packed grayscale to 8-bit per pixel first
                expanded = _expand_bitdepth(px, self.bit_depth, w * h)
                for i in range(w * h):
                    v = expanded[i]
                    out[i * 4]     = v
                    out[i * 4 + 1] = v
                    out[i * 4 + 2] = v
                    out[i * 4 + 3] = 255
            return bytes(out)

        if ct == PNGColorType.GRAYSCALE_ALPHA:
            for i in range(w * h):
                v = px[i * 2]
                a = px[i * 2 + 1]
                out[i * 4]     = v
                out[i * 4 + 1] = v
                out[i * 4 + 2] = v
                out[i * 4 + 3] = a
            return bytes(out)

        if ct == PNGColorType.INDEXED:
            pal = self.palette or []
            trans_map: bytes = self.transparency or b""
            if self.bit_depth == 8:
                indices = px
            else:
                indices = _expand_bitdepth(px, self.bit_depth, w * h)
            for i, idx in enumerate(indices):
                if idx < len(pal):
                    r, g, b = pal[idx]
                else:
                    r, g, b = 0, 0, 0
                a = trans_map[idx] if idx < len(trans_map) else 255
                out[i * 4]     = r
                out[i * 4 + 1] = g
                out[i * 4 + 2] = b
                out[i * 4 + 3] = a
            return bytes(out)

        raise ParseError(f"to_rgba_bytes: unsupported color type {ct}")

    def to_rgb_bytes(self) -> bytes:
        """Convert any supported color type to a flat RGB byte buffer (drops alpha)."""
        rgba = self.to_rgba_bytes()
        w, h = self.width, self.height
        out = bytearray(w * h * 3)
        for i in range(w * h):
            out[i * 3]     = rgba[i * 4]
            out[i * 3 + 1] = rgba[i * 4 + 1]
            out[i * 3 + 2] = rgba[i * 4 + 2]
        return bytes(out)

    def to_png(self, compress_level: int = 6) -> bytes:
        """Encode this image to a PNG byte stream."""
        return PNGCodec.encode_rgba(self.width, self.height, self.to_rgba_bytes(), compress_level=compress_level)

    def save(self, filepath: Union[str, Path], compress_level: int = 6) -> None:
        """Save this image to a PNG file."""
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(self.to_png(compress_level=compress_level))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _expand_bitdepth(data: bytes, bit_depth: int, num_pixels: int) -> bytes:
    """Expand bit-packed data (1/2/4 bpp) to one byte per pixel."""
    out = bytearray(num_pixels)
    pixels_per_byte = 8 // bit_depth
    mask = (1 << bit_depth) - 1
    shift_table = [8 - bit_depth * (k + 1) for k in range(pixels_per_byte)]
    idx = 0
    for byte in data:
        for shift in shift_table:
            if idx >= num_pixels:
                break
            out[idx] = (byte >> shift) & mask
            idx += 1
    return bytes(out)


def _paeth_predictor(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa = abs(p - a)
    pb = abs(p - b)
    pc = abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _apply_filters(scanlines: bytes, row_bytes: int, height: int, bpp: int) -> bytearray:
    """Reconstruct raw pixel rows from PNG-filtered scanlines.

    Parameters
    ----------
    scanlines : bytes
        Raw filtered scanlines including filter-type prefix byte per row.
    row_bytes : int
        Width of each row in bytes (already accounting for channels & bit depth).
    height : int
        Number of rows.
    bpp : int
        Bytes per pixel used for filter math (1 for sub-8-bit depths).
    """
    stride = 1 + row_bytes
    out = bytearray(height * row_bytes)
    prev_row = bytearray(row_bytes)

    for y in range(height):
        line = scanlines[y * stride : (y + 1) * stride]
        filter_type = line[0]
        curr_row = bytearray(line[1:])

        if filter_type == 0:  # None
            pass
        elif filter_type == 1:  # Sub
            for x in range(bpp, row_bytes):
                curr_row[x] = (curr_row[x] + curr_row[x - bpp]) & 0xFF
        elif filter_type == 2:  # Up
            for x in range(row_bytes):
                curr_row[x] = (curr_row[x] + prev_row[x]) & 0xFF
        elif filter_type == 3:  # Average
            for x in range(row_bytes):
                a = curr_row[x - bpp] if x >= bpp else 0
                b = prev_row[x]
                curr_row[x] = (curr_row[x] + ((a + b) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for x in range(row_bytes):
                a = curr_row[x - bpp] if x >= bpp else 0
                b = prev_row[x]
                c = prev_row[x - bpp] if x >= bpp else 0
                curr_row[x] = (curr_row[x] + _paeth_predictor(a, b, c)) & 0xFF
        else:
            raise ParseError(f"Unknown PNG filter type {filter_type} at row {y}")

        out[y * row_bytes : (y + 1) * row_bytes] = curr_row
        prev_row = curr_row

    return out


# Channels per pixel for each color type (at 8-bit depth)
_COLOR_TYPE_CHANNELS = {
    PNGColorType.GRAYSCALE:       1,
    PNGColorType.RGB:             3,
    PNGColorType.INDEXED:         1,
    PNGColorType.GRAYSCALE_ALPHA: 2,
    PNGColorType.RGBA:            4,
}

# Valid bit depths per color type (PNG spec §11.2.2)
_VALID_BIT_DEPTHS = {
    PNGColorType.GRAYSCALE:       {1, 2, 4, 8},
    PNGColorType.RGB:             {8},
    PNGColorType.INDEXED:         {1, 2, 4, 8},
    PNGColorType.GRAYSCALE_ALPHA: {8},
    PNGColorType.RGBA:            {8},
}


# ---------------------------------------------------------------------------
# Public codec
# ---------------------------------------------------------------------------

class PNGCodec:
    """
    Pure-Python PNG encoder and decoder (zero external dependencies).

    All encode methods return ``bytes`` containing a valid PNG file.
    :meth:`decode` returns a :class:`PNGImage` instance.
    """

    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _make_chunk(cls, chunk_type: bytes, data: bytes) -> bytes:
        length = len(data)
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return schema.pack(">I", length) + chunk_type + data + schema.pack(">I", crc)

    @classmethod
    def _encode_raw(
        cls,
        width: int,
        height: int,
        color_type: int,
        bit_depth: int,
        raw_rows: List[bytes],
        palette_chunk: Optional[bytes] = None,
        transparency_chunk: Optional[bytes] = None,
        compress_level: int = 6,
    ) -> bytes:
        """Low-level encoder shared by all public encode methods."""
        ihdr = schema.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, 0)
        chunks: List[bytes] = [cls.PNG_SIGNATURE, cls._make_chunk(b"IHDR", ihdr)]

        if palette_chunk is not None:
            chunks.append(cls._make_chunk(b"PLTE", palette_chunk))
        if transparency_chunk is not None:
            chunks.append(cls._make_chunk(b"tRNS", transparency_chunk))

        scanlines = bytearray()
        for row in raw_rows:
            scanlines.append(0)  # filter type: None
            scanlines.extend(row)

        compressed = zlib.compress(bytes(scanlines), level=compress_level)
        chunks.append(cls._make_chunk(b"IDAT", compressed))
        chunks.append(cls._make_chunk(b"IEND", b""))
        return b"".join(chunks)

    # ------------------------------------------------------------------
    # Encode
    # ------------------------------------------------------------------

    @classmethod
    def encode_grayscale(cls, width: int, height: int, pixels: bytes, compress_level: int = 6) -> bytes:
        """
        Encode an 8-bit grayscale pixel buffer (row-major, 1 byte/pixel).

        Parameters
        ----------
        pixels : bytes
            Must be exactly ``width * height`` bytes.
        compress_level : int
            zlib compression level (0–9).
        """
        expected = width * height
        if len(pixels) != expected:
            raise ValueError(f"Pixel buffer size ({len(pixels)}) != {width}×{height} ({expected})")
        rows = [pixels[y * width : (y + 1) * width] for y in range(height)]
        return cls._encode_raw(width, height, PNGColorType.GRAYSCALE, 8, rows,
                               compress_level=compress_level)

    @classmethod
    def encode_rgb(cls, width: int, height: int, pixels: bytes, compress_level: int = 6) -> bytes:
        """
        Encode an 8-bit RGB pixel buffer (row-major, 3 bytes/pixel).

        Parameters
        ----------
        pixels : bytes
            Must be exactly ``width * height * 3`` bytes.
        """
        expected = width * height * 3
        if len(pixels) != expected:
            raise ValueError(f"Pixel buffer size ({len(pixels)}) != {width}×{height}×3 ({expected})")
        row_len = width * 3
        rows = [pixels[y * row_len : (y + 1) * row_len] for y in range(height)]
        return cls._encode_raw(width, height, PNGColorType.RGB, 8, rows,
                               compress_level=compress_level)

    @classmethod
    def encode_rgba(cls, width: int, height: int, pixels: bytes, compress_level: int = 6) -> bytes:
        """
        Encode an 8-bit RGBA pixel buffer (row-major, 4 bytes/pixel).

        Parameters
        ----------
        pixels : bytes
            Must be exactly ``width * height * 4`` bytes.
        """
        expected = width * height * 4
        if len(pixels) != expected:
            raise ValueError(f"Pixel buffer size ({len(pixels)}) != {width}×{height}×4 ({expected})")
        row_len = width * 4
        rows = [pixels[y * row_len : (y + 1) * row_len] for y in range(height)]
        return cls._encode_raw(width, height, PNGColorType.RGBA, 8, rows,
                               compress_level=compress_level)

    @classmethod
    def encode_indexed(
        cls,
        width: int,
        height: int,
        indices: bytes,
        palette: List[Tuple[int, int, int]],
        transparency: Optional[List[int]] = None,
        compress_level: int = 6,
    ) -> bytes:
        """
        Encode an 8-bit indexed (paletted) pixel buffer.

        Parameters
        ----------
        indices : bytes
            Must be exactly ``width * height`` bytes; each byte is a palette index.
        palette : list of (R, G, B) tuples
            Up to 256 entries.
        transparency : list of int or None
            Per-palette-entry alpha values (0–255).  If None, no tRNS chunk is written.
        """
        if len(indices) != width * height:
            raise ValueError(f"Indices size ({len(indices)}) != {width}×{height}")
        if len(palette) > 256:
            raise ValueError(f"Palette has {len(palette)} entries; PNG indexed max is 256")

        plte = bytearray()
        for r, g, b in palette:
            plte.extend([r & 0xFF, g & 0xFF, b & 0xFF])

        trns: Optional[bytes] = None
        if transparency is not None:
            trns = bytes([a & 0xFF for a in transparency])

        rows = [indices[y * width : (y + 1) * width] for y in range(height)]
        return cls._encode_raw(width, height, PNGColorType.INDEXED, 8, rows,
                               palette_chunk=bytes(plte),
                               transparency_chunk=trns,
                               compress_level=compress_level)

    @classmethod
    def encode_grayscale_alpha(
        cls, width: int, height: int, pixels: bytes, compress_level: int = 6
    ) -> bytes:
        """
        Encode an 8-bit grayscale+alpha pixel buffer (2 bytes/pixel: Y, A).
        """
        expected = width * height * 2
        if len(pixels) != expected:
            raise ValueError(f"Pixel buffer size ({len(pixels)}) != {width}×{height}×2 ({expected})")
        row_len = width * 2
        rows = [pixels[y * row_len : (y + 1) * row_len] for y in range(height)]
        return cls._encode_raw(width, height, PNGColorType.GRAYSCALE_ALPHA, 8, rows,
                               compress_level=compress_level)

    # ------------------------------------------------------------------
    # Decode
    # ------------------------------------------------------------------

    @classmethod
    def decode(cls, png_data: bytes) -> PNGImage:
        """
        Decode a PNG byte stream.

        Returns a :class:`PNGImage` with unfiltered, uncompressed pixel data.

        Raises
        ------
        ParseError
            On invalid or unsupported PNG data.
        """
        if len(png_data) < 8 or not png_data.startswith(cls.PNG_SIGNATURE):
            raise ParseError("Invalid PNG signature")

        offset = 8
        width = height = 0
        bit_depth = 8
        color_type = 0
        interlace = 0
        idat_parts: List[bytes] = []
        palette: Optional[List[Tuple[int, int, int]]] = None
        transparency: Optional[bytes] = None

        while offset + 8 <= len(png_data):
            length = schema.unpack_from(">I", png_data, offset)[0]
            chunk_type = png_data[offset + 4 : offset + 8]
            data = png_data[offset + 8 : offset + 8 + length]
            offset += 12 + length

            if chunk_type == b"IHDR":
                if len(data) < 13:
                    raise ParseError("IHDR chunk too short")
                width, height, bit_depth, color_type, _, _, interlace = schema.unpack(">IIBBBBB", data[:13])

            elif chunk_type == b"PLTE":
                if len(data) % 3 != 0:
                    raise ParseError("PLTE chunk length must be a multiple of 3")
                palette = [
                    (data[i], data[i + 1], data[i + 2])
                    for i in range(0, len(data), 3)
                ]

            elif chunk_type == b"tRNS":
                transparency = bytes(data)

            elif chunk_type == b"IDAT":
                idat_parts.append(bytes(data))

            elif chunk_type == b"IEND":
                break

        # Validate
        if not idat_parts or width == 0 or height == 0:
            raise ParseError("PNG contains no valid image data")
        if interlace != 0:
            raise ParseError("Interlaced PNG (Adam7) is not supported by PNGCodec")
        if bit_depth == 16:
            raise ParseError("16-bit PNG is not supported by PNGCodec")
        if color_type not in _COLOR_TYPE_CHANNELS:
            raise ParseError(f"Unsupported PNG color type: {color_type}")
        valid_depths = _VALID_BIT_DEPTHS.get(color_type, set())
        if bit_depth not in valid_depths:
            raise ParseError(f"Bit depth {bit_depth} invalid for color type {color_type}")
        if color_type == PNGColorType.INDEXED and palette is None:
            raise ParseError("Indexed PNG has no PLTE chunk")

        # Determine bytes-per-pixel for filter reconstruction
        channels = _COLOR_TYPE_CHANNELS[color_type]
        if bit_depth < 8:
            # For sub-byte depths, filter is applied per-byte (bpp=1 for filter math)
            bpp_filter = 1
            # row width in bytes (ceil)
            row_bytes = math.ceil(width * bit_depth / 8)
        else:
            bpp_filter = channels
            row_bytes = width * channels

        decompressed = zlib.decompress(b"".join(idat_parts))
        # Reconstruct filtered scanlines
        raw = _apply_filters(decompressed, row_bytes, height, bpp_filter)

        # For sub-byte depths the pixel data is bit-packed per row; return as-is.
        # Callers can use to_rgba_bytes() which handles expansion.
        return PNGImage(
            width=width,
            height=height,
            color_type=color_type,
            bit_depth=bit_depth,
            pixels=bytes(raw),
            palette=palette,
            transparency=transparency,
        )

    # ------------------------------------------------------------------
    # Convenience round-trip helpers
    # ------------------------------------------------------------------

    @classmethod
    def rgba_to_png(cls, width: int, height: int, rgba_pixels: bytes, compress_level: int = 6) -> bytes:
        """Shorthand for :meth:`encode_rgba`."""
        return cls.encode_rgba(width, height, rgba_pixels, compress_level=compress_level)

    @classmethod
    def png_to_rgba(cls, png_data: bytes) -> Tuple[int, int, bytes]:
        """
        Decode a PNG file and convert to a flat RGBA byte buffer.

        Returns
        -------
        (width, height, rgba_bytes)
        """
        img = cls.decode(png_data)
        return img.width, img.height, img.to_rgba_bytes()
