"""
from miorom.errors import ParseError
miorom.graphics.tilesheet
~~~~~~~~~~~~~~~~~~~~~~~~~
Palette-Aware Tile Sheet Visualizer & Pure-Python BMP Transcoder.
Provides high-performance 2D grid tiling, color palette indexing,
and lossless export/import of retro ROM graphics without external GUI dependencies.
"""

import math
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile, decode_tileset, encode_tileset


def _create_default_palette(num_colors: int = 16) -> Palette:
    """Creates a grayscale gradient palette for unpaletteized tiles."""
    colors = []
    max_val = max(1, num_colors - 1)
    for i in range(num_colors):
        v = (i * 255) // max_val
        colors.append(Color(v, v, v))
    return Palette(colors)


class TileSheet:
    """
    Represents an indexed 2D grid of 8x8 Tile objects with associated Color Palette.
    Supports lossless serialization to and from pure-Python uncompressed BMP.
    """

    def __init__(
        self,
        tiles: Optional[List[Tile]] = None,
        columns: int = 16,
        palette: Optional[Palette] = None,
    ):
        self.tiles: List[Tile] = tiles or []
        self.columns: int = max(1, columns)
        self.palette: Palette = palette or _create_default_palette(16)

    @property
    def rows(self) -> int:
        if not self.tiles:
            return 0
        return math.ceil(len(self.tiles) / self.columns)

    @property
    def pixel_width(self) -> int:
        return self.columns * 8

    @property
    def pixel_height(self) -> int:
        return self.rows * 8

    def get_tile(self, col: int, row: int) -> Optional[Tile]:
        idx = row * self.columns + col
        if 0 <= idx < len(self.tiles):
            return self.tiles[idx]
        return None

    def set_tile(self, col: int, row: int, tile: Tile) -> None:
        idx = row * self.columns + col
        while len(self.tiles) <= idx:
            self.tiles.append(Tile())
        self.tiles[idx] = tile

    def get_pixel(self, x: int, y: int) -> int:
        col = x // 8
        row = y // 8
        tile = self.get_tile(col, row)
        if tile is None:
            return 0
        return tile.get_pixel(x % 8, y % 8)

    def set_pixel(self, x: int, y: int, val: int) -> None:
        col = x // 8
        row = y // 8
        tile = self.get_tile(col, row)
        if tile is None:
            tile = Tile()
            self.set_tile(col, row, tile)
        tile.set_pixel(x % 8, y % 8, val)

    def to_tileset_bytes(self, bpp: int = 4, planar: bool = False) -> bytes:
        """Encodes all tiles in the sheet into raw ROM tile binary."""
        return encode_tileset(self.tiles, bpp=bpp, planar=planar)

    @classmethod
    def from_tileset_bytes(
        cls,
        data: bytes,
        bpp: int = 4,
        planar: bool = False,
        columns: int = 16,
        palette: Optional[Palette] = None,
    ) -> "TileSheet":
        """Decodes raw ROM tile binary into a TileSheet."""
        tiles = decode_tileset(data, bpp=bpp, planar=planar)
        return cls(tiles=tiles, columns=columns, palette=palette)

    def to_bmp(self, output_path: Optional[str] = None) -> bytes:
        """
        Renders the entire tile sheet using its active palette into standard
        uncompressed 24-bit RGB BMP bytes. Optionally writes to output_path.
        """
        w = self.pixel_width
        h = self.pixel_height
        if w == 0 or h == 0:
            w, h = 8, 8

        row_bytes = w * 3
        padding_len = (4 - (row_bytes % 4)) % 4
        stride = row_bytes + padding_len
        image_data_size = stride * h
        file_size = 54 + image_data_size

        # BMP 14-byte File Header
        file_header = struct.pack(
            "<2sIHHI",
            b"BM",
            file_size,
            0,
            0,
            54,  # Offset to pixel array
        )

        # BITMAPINFOHEADER 40 bytes
        info_header = struct.pack(
            "<IIIHHIIIIII",
            40,          # biSize
            w,           # biWidth
            h,           # biHeight (positive = bottom-up)
            1,           # biPlanes
            24,          # biBitCount
            0,           # biCompression (BI_RGB)
            image_data_size,  # biSizeImage
            2835,        # biXPelsPerMeter (72 dpi)
            2835,        # biYPelsPerMeter
            0,           # biClrUsed
            0,           # biClrImportant
        )

        # Bottom-up pixel data
        pixel_bytes = bytearray(image_data_size)
        pad = b"\x00" * padding_len

        pal_len = len(self.palette)

        for y in range(h):
            # In standard bottom-up BMP, row 0 is the bottom row
            src_y = (h - 1) - y
            row_offset = y * stride
            row_slice = bytearray()
            for x in range(w):
                idx = self.get_pixel(x, src_y)
                if idx < pal_len:
                    c = self.palette[idx]
                else:
                    c = Color(0, 0, 0)
                # BMP stores B, G, R
                row_slice.extend((c.b, c.g, c.r))
            row_slice.extend(pad)
            pixel_bytes[row_offset : row_offset + len(row_slice)] = row_slice

        bmp_data = file_header + info_header + bytes(pixel_bytes)
        if output_path:
            with open(output_path, "wb") as f:
                f.write(bmp_data)
        return bmp_data

    @classmethod
    def from_bmp(
        cls,
        bmp_data_or_path: Union[str, bytes],
        bpp: int = 4,
        palette: Optional[Palette] = None,
        columns: Optional[int] = None,
    ) -> "TileSheet":
        """
        Parses an uncompressed 24-bit or 32-bit BMP and quantizes/maps pixels
        back to 8x8 Tile indexed elements.
        """
        if isinstance(bmp_data_or_path, str):
            with open(bmp_data_or_path, "rb") as f:
                data = f.read()
        else:
            data = bytes(bmp_data_or_path)

        if len(data) < 54 or data[:2] != b"BM":
            raise ParseError("Invalid BMP header: magic 'BM' not found")

        offset_bits = struct.unpack_from("<I", data, 10)[0]
        bi_size = struct.unpack_from("<I", data, 14)[0]
        w = struct.unpack_from("<i", data, 18)[0]
        h_signed = struct.unpack_from("<i", data, 22)[0]
        bit_count = struct.unpack_from("<H", data, 28)[0]
        compression = struct.unpack_from("<I", data, 30)[0]

        if compression != 0:
            raise ParseError(f"Compressed BMP (compression={compression}) is not supported")
        if bit_count not in (24, 32):
            raise ParseError(f"Unsupported BMP bit depth: {bit_count}bpp (only 24/32 supported)")

        is_top_down = h_signed < 0
        h = abs(h_signed)

        bytes_per_pixel = bit_count // 8
        row_bytes = w * bytes_per_pixel
        padding_len = (4 - (row_bytes % 4)) % 4 if bit_count == 24 else 0
        stride = row_bytes + padding_len

        # Extract 2D RGB grid
        rgb_rows: List[List[Color]] = [[Color(0, 0, 0) for _ in range(w)] for _ in range(h)]
        for y_idx in range(h):
            actual_y = y_idx if is_top_down else (h - 1 - y_idx)
            row_start = offset_bits + y_idx * stride
            for x in range(w):
                px_offset = row_start + x * bytes_per_pixel
                b = data[px_offset]
                g = data[px_offset + 1]
                r = data[px_offset + 2]
                rgb_rows[actual_y][x] = Color(r, g, b)

        # Palette
        num_colors = 1 << bpp
        active_palette = palette or _create_default_palette(num_colors)

        # Slice into 8x8 tiles
        tiles_x = (w + 7) // 8
        tiles_y = (h + 7) // 8
        sheet_columns = columns or tiles_x

        tiles: List[Tile] = []
        for ty in range(tiles_y):
            for tx in range(tiles_x):
                t_pixels = [0] * 64
                for py in range(8):
                    for px in range(8):
                        gx = tx * 8 + px
                        gy = ty * 8 + py
                        if gx < w and gy < h:
                            color = rgb_rows[gy][gx]
                            matched_idx = active_palette.match_color(color)
                            t_pixels[py * 8 + px] = min(matched_idx, num_colors - 1)
                tiles.append(Tile(t_pixels))

        return cls(tiles=tiles, columns=sheet_columns, palette=active_palette)


class TileSheetRenderer:
    """
    Rendering utility for visual inspection of TileSheets with zoom,
    grid lines, and custom color overlays.
    """

    @classmethod
    def render_to_bmp(
        cls,
        sheet: TileSheet,
        output_path: Optional[str] = None,
        scale: int = 1,
        show_grid: bool = False,
        grid_color: Color = Color(128, 128, 128),
    ) -> bytes:
        """
        Renders a TileSheet to 24-bit BMP with scaling and optional grid delimiters.
        """
        scale = max(1, scale)
        orig_w = sheet.pixel_width
        orig_h = sheet.pixel_height
        w = orig_w * scale
        h = orig_h * scale

        row_bytes = w * 3
        padding_len = (4 - (row_bytes % 4)) % 4
        stride = row_bytes + padding_len
        image_data_size = stride * h
        file_size = 54 + image_data_size

        file_header = struct.pack("<2sIHHI", b"BM", file_size, 0, 0, 54)
        info_header = struct.pack("<IIIHHIIIIII", 40, w, h, 1, 24, 0, image_data_size, 2835, 2835, 0, 0)

        pixel_bytes = bytearray(image_data_size)
        pad = b"\x00" * padding_len
        pal_len = len(sheet.palette)

        for y in range(h):
            src_y = (h - 1) - y
            orig_y = src_y // scale
            row_offset = y * stride
            row_slice = bytearray()

            for x in range(w):
                orig_x = x // scale
                # Grid check on 8x8 tile boundaries
                if show_grid and (orig_x % 8 == 0 or orig_y % 8 == 0):
                    c = grid_color
                else:
                    idx = sheet.get_pixel(orig_x, orig_y)
                    c = sheet.palette[idx] if idx < pal_len else Color(0, 0, 0)

                row_slice.extend((c.b, c.g, c.r))

            row_slice.extend(pad)
            pixel_bytes[row_offset : row_offset + len(row_slice)] = row_slice

        bmp_data = file_header + info_header + bytes(pixel_bytes)
        if output_path:
            with open(output_path, "wb") as f:
                f.write(bmp_data)
        return bmp_data
