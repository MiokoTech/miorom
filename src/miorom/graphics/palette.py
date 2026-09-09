import math
from miorom.errors import ParseError
import struct
from dataclasses import dataclass
from typing import List, Tuple, Union, Optional


@dataclass(frozen=True)
class Color:
    r: int
    g: int
    b: int
    a: int = 255

    def to_bgr555(self) -> int:
        """Converts RGBA color to 15-bit BGR555 integer (Nintendo GBA/NDS/SNES)."""
        r5 = (self.r * 31 + 127) // 255
        g5 = (self.g * 31 + 127) // 255
        b5 = (self.b * 31 + 127) // 255
        return (b5 << 10) | (g5 << 5) | r5

    @classmethod
    def from_bgr555(cls, val: int, alpha: int = 255) -> "Color":
        """Converts 15-bit BGR555 integer into 32-bit RGBA Color."""
        r5 = val & 0x1F
        g5 = (val >> 5) & 0x1F
        b5 = (val >> 10) & 0x1F
        r = (r5 * 255 + 15) // 31
        g = (g5 * 255 + 15) // 31
        b = (b5 * 255 + 15) // 31
        return cls(r, g, b, alpha)

    def to_rgb565(self) -> int:
        """Converts RGBA color to 16-bit RGB565 integer."""
        r5 = (self.r * 31 + 127) // 255
        g6 = (self.g * 63 + 127) // 255
        b5 = (self.b * 31 + 127) // 255
        return (r5 << 11) | (g6 << 5) | b5

    @classmethod
    def from_rgb565(cls, val: int, alpha: int = 255) -> "Color":
        r5 = (val >> 11) & 0x1F
        g6 = (val >> 5) & 0x3F
        b5 = val & 0x1F
        r = (r5 * 255 + 15) // 31
        g = (g6 * 255 + 31) // 63
        b = (b5 * 255 + 15) // 31
        return cls(r, g, b, alpha)

    def distance_squared(self, other: "Color") -> int:
        """Weighted Euclidean color distance (approximates human perception)."""
        dr = self.r - other.r
        dg = self.g - other.g
        db = self.b - other.b
        # 30% Red, 59% Green, 11% Blue weighting
        return (2 * dr * dr) + (4 * dg * dg) + (3 * db * db)


class Palette:
    """Represents an indexed color palette."""

    def __init__(self, colors: Optional[List[Color]] = None):
        self.colors: List[Color] = colors or []

    def __len__(self) -> int:
        return len(self.colors)

    def __getitem__(self, idx: int) -> Color:
        return self.colors[idx]

    def __setitem__(self, idx: int, value: Color):
        self.colors[idx] = value

    def append(self, color: Color):
        self.colors.append(color)

    @classmethod
    def from_bgr555_bytes(cls, data: bytes) -> "Palette":
        """Reads a list of BGR555 16-bit little-endian values."""
        colors = []
        for i in range(0, len(data) - 1, 2):
            val = struct.unpack_from("<H", data, i)[0]
            colors.append(Color.from_bgr555(val))
        return cls(colors)

    def to_bgr555_bytes(self) -> bytes:
        """Serializes palette into BGR555 16-bit little-endian binary bytes."""
        out = bytearray()
        for col in self.colors:
            out.extend(struct.pack("<H", col.to_bgr555()))
        return bytes(out)

    def match_color(self, color: Color, start_index: int = 0) -> int:
        """Finds closest color index in palette."""
        if not self.colors:
            raise ParseError("Palette is empty")
        best_idx = start_index
        best_dist = float("inf")
        for i in range(start_index, len(self.colors)):
            d = self.colors[i].distance_squared(color)
            if d < best_dist:
                best_dist = d
                best_idx = i
                if d == 0:
                    break
        return best_idx


class FloydSteinbergDitherer:
    """
    Pure-Python Floyd-Steinberg error-diffusion dithering for palette color reduction.
    Requires no external dependencies.
    """

    @classmethod
    def dither(
        cls,
        pixels: list[list[tuple[int, int, int]]],
        palette: Palette,
    ) -> list[list[int]]:
        """
        Applies Floyd-Steinberg dithering across 2D RGB pixel matrix, returning 2D palette index matrix.
        """
        height = len(pixels)
        if height == 0:
            return []
        width = len(pixels[0])

        # Convert to float buffers
        r_buf = [[float(pixels[y][x][0]) for x in range(width)] for y in range(height)]
        g_buf = [[float(pixels[y][x][1]) for x in range(width)] for y in range(height)]
        b_buf = [[float(pixels[y][x][2]) for x in range(width)] for y in range(height)]

        result: list[list[int]] = [[0 for _ in range(width)] for _ in range(height)]

        for y in range(height):
            for x in range(width):
                old_r = max(0.0, min(255.0, r_buf[y][x]))
                old_g = max(0.0, min(255.0, g_buf[y][x]))
                old_b = max(0.0, min(255.0, b_buf[y][x]))

                best_idx = palette.match_color(Color(int(old_r), int(old_g), int(old_b)))
                matched = palette[best_idx]
                result[y][x] = best_idx

                err_r = old_r - matched.r
                err_g = old_g - matched.g
                err_b = old_b - matched.b

                def add_err(nx, ny, factor):
                    if 0 <= nx < width and 0 <= ny < height:
                        r_buf[ny][nx] += err_r * factor
                        g_buf[ny][nx] += err_g * factor
                        b_buf[ny][nx] += err_b * factor

                add_err(x + 1, y, 7.0 / 16.0)
                add_err(x - 1, y + 1, 3.0 / 16.0)
                add_err(x, y + 1, 5.0 / 16.0)
                add_err(x + 1, y + 1, 1.0 / 16.0)

        return result
