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

    def to_md_color(self) -> int:
        """Converts RGBA color to 9-bit RGB333 integer for Sega Genesis / Mega Drive VDP."""
        r3 = (self.r * 7 + 127) // 255
        g3 = (self.g * 7 + 127) // 255
        b3 = (self.b * 7 + 127) // 255
        return (b3 << 9) | (g3 << 5) | (r3 << 1)

    @classmethod
    def from_md_color(cls, val: int, alpha: int = 255) -> "Color":
        """Converts Sega Genesis / Mega Drive 9-bit RGB333 VDP word into 32-bit RGBA Color."""
        r3 = (val >> 1) & 0x07
        g3 = (val >> 5) & 0x07
        b3 = (val >> 9) & 0x07
        r = (r3 * 255 + 3) // 7
        g = (g3 * 255 + 3) // 7
        b = (b3 * 255 + 3) // 7
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

    @classmethod
    def from_md_bytes(cls, data: bytes, endian: str = ">") -> "Palette":
        """Reads Sega Genesis / Mega Drive VDP 9-bit RGB333 CRAM words (2 bytes per color)."""
        colors = []
        fmt = f"{endian}H"
        for i in range(0, len(data) - 1, 2):
            val = struct.unpack_from(fmt, data, i)[0]
            colors.append(Color.from_md_color(val))
        return cls(colors)

    def to_md_bytes(self, endian: str = ">") -> bytes:
        """Serializes palette into Sega Genesis / Mega Drive VDP CRAM binary words."""
        out = bytearray()
        fmt = f"{endian}H"
        for col in self.colors:
            out.extend(struct.pack(fmt, col.to_md_color()))
        return bytes(out)

    def to_act(self) -> bytes:
        """Serializes palette into Adobe Color Table (.act) binary format (768 bytes)."""
        out = bytearray()
        for i in range(256):
            if i < len(self.colors):
                c = self.colors[i]
                out.extend([c.r, c.g, c.b])
            else:
                out.extend([0, 0, 0])
        # ACT 4-byte footer
        out.extend(struct.pack(">HH", min(256, len(self.colors)), 0xFFFF))
        return bytes(out)

    @classmethod
    def from_act(cls, data: bytes) -> "Palette":
        """Parses an Adobe Color Table (.act) binary file."""
        if len(data) < 768:
            raise ParseError(f"Data too short for ACT palette: expected at least 768 bytes, got {len(data)}")
        count = 256
        if len(data) >= 772:
            count_in_file = struct.unpack_from(">H", data, 768)[0]
            if 0 < count_in_file <= 256:
                count = count_in_file
        colors = []
        for i in range(count):
            r, g, b = data[i * 3], data[i * 3 + 1], data[i * 3 + 2]
            colors.append(Color(r, g, b))
        return cls(colors)

    def to_jasc_pal(self) -> str:
        """Serializes palette to JASC Paint Shop Pro ASCII (.pal) format."""
        lines = ["JASC-PAL", "0100", str(len(self.colors))]
        for c in self.colors:
            lines.append(f"{c.r} {c.g} {c.b}")
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jasc_pal(cls, text: str) -> "Palette":
        """Parses JASC Paint Shop Pro ASCII (.pal) text format."""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) < 3 or lines[0] != "JASC-PAL" or lines[1] != "0100":
            raise ParseError("Invalid JASC-PAL header: must start with 'JASC-PAL' and '0100'")
        try:
            count = int(lines[2])
        except ValueError:
            raise ParseError(f"Invalid JASC-PAL count: {lines[2]!r}")
        colors = []
        for line in lines[3 : 3 + count]:
            parts = line.split()
            if len(parts) >= 3:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                colors.append(Color(r, g, b))
        return cls(colors)

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

                # Floyd-Steinberg error diffusion
                if x + 1 < width:
                    r_buf[y][x + 1] += err_r * (7.0 / 16.0)
                    g_buf[y][x + 1] += err_g * (7.0 / 16.0)
                    b_buf[y][x + 1] += err_b * (7.0 / 16.0)
                if y + 1 < height:
                    if x > 0:
                        r_buf[y + 1][x - 1] += err_r * (3.0 / 16.0)
                        g_buf[y + 1][x - 1] += err_g * (3.0 / 16.0)
                        b_buf[y + 1][x - 1] += err_b * (3.0 / 16.0)
                    r_buf[y + 1][x] += err_r * (5.0 / 16.0)
                    g_buf[y + 1][x] += err_g * (5.0 / 16.0)
                    b_buf[y + 1][x] += err_b * (5.0 / 16.0)
                    if x + 1 < width:
                        r_buf[y + 1][x + 1] += err_r * (1.0 / 16.0)
                        g_buf[y + 1][x + 1] += err_g * (1.0 / 16.0)
                        b_buf[y + 1][x + 1] += err_b * (1.0 / 16.0)

        return result
