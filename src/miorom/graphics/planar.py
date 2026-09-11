from typing import List, Sequence, Tuple
from miorom.errors import ParseError


class PlanarTileCodec:
    """
    Pure-Python planar bitplane and chunky tile codec for retro consoles.
    Operates on 8x8 pixel tiles (64 indexed pixels) and raw byte streams.
    Supports bitplane extraction, recombination, and bulk linear conversions.
    """

    FORMAT_SIZES = {
        "mono_1bpp": 8,
        "1bpp": 8,
        "nes_2bpp": 16,
        "gb_2bpp": 16,
        "gameboy_2bpp": 16,
        "snes_2bpp": 16,
        "2bpp": 16,
        "snes_3bpp": 24,
        "3bpp": 24,
        "snes_4bpp": 32,
        "snes": 32,
        "4bpp_planar": 32,
        "genesis_4bpp": 32,
        "megadrive_4bpp": 32,
        "gba_4bpp": 32,
        "snes_8bpp": 64,
        "mode7": 64,
        "gba_8bpp": 64,
        "linear_8bpp": 64,
    }

    FORMAT_BPP = {
        "mono_1bpp": 1,
        "1bpp": 1,
        "nes_2bpp": 2,
        "gb_2bpp": 2,
        "gameboy_2bpp": 2,
        "snes_2bpp": 2,
        "2bpp": 2,
        "snes_3bpp": 3,
        "3bpp": 3,
        "snes_4bpp": 4,
        "snes": 4,
        "4bpp_planar": 4,
        "genesis_4bpp": 4,
        "megadrive_4bpp": 4,
        "gba_4bpp": 4,
        "snes_8bpp": 8,
        "mode7": 8,
        "gba_8bpp": 8,
        "linear_8bpp": 8,
    }

    @classmethod
    def get_tile_size(cls, format: str) -> int:
        fmt = format.lower().replace("-", "_")
        if fmt not in cls.FORMAT_SIZES:
            raise ValueError(f"Unknown tile format: {format}")
        return cls.FORMAT_SIZES[fmt]

    @classmethod
    def get_bpp(cls, format: str) -> int:
        fmt = format.lower().replace("-", "_")
        if fmt not in cls.FORMAT_BPP:
            raise ValueError(f"Unknown tile format: {format}")
        return cls.FORMAT_BPP[fmt]

    @classmethod
    def decode_tile(cls, data: bytes, format: str) -> List[int]:
        """Decodes 8x8 tile into 64 indexed pixel values (0 to 2^bpp - 1)."""
        fmt = format.lower().replace("-", "_")
        expected_size = cls.get_tile_size(fmt)
        if len(data) < expected_size:
            raise ParseError(f"Data too short for {format}: expected {expected_size} bytes, got {len(data)}")

        pixels = [0] * 64

        if fmt in ("mono_1bpp", "1bpp"):
            for y in range(8):
                b = data[y]
                for x in range(8):
                    pixels[y * 8 + x] = (b >> (7 - x)) & 1

        elif fmt in ("nes_2bpp", "gb_2bpp", "gameboy_2bpp", "snes_2bpp", "2bpp"):
            for y in range(8):
                p0 = data[y * 2]
                p1 = data[y * 2 + 1]
                for x in range(8):
                    bit = 7 - x
                    pixels[y * 8 + x] = ((p0 >> bit) & 1) | (((p1 >> bit) & 1) << 1)

        elif fmt in ("snes_3bpp", "3bpp"):
            for y in range(8):
                p0 = data[y * 2]
                p1 = data[y * 2 + 1]
                p2 = data[16 + y]
                for x in range(8):
                    bit = 7 - x
                    pixels[y * 8 + x] = (
                        ((p0 >> bit) & 1)
                        | (((p1 >> bit) & 1) << 1)
                        | (((p2 >> bit) & 1) << 2)
                    )

        elif fmt in ("snes_4bpp", "snes", "4bpp_planar"):
            for y in range(8):
                p0 = data[y * 2]
                p1 = data[y * 2 + 1]
                p2 = data[16 + y * 2]
                p3 = data[16 + y * 2 + 1]
                for x in range(8):
                    bit = 7 - x
                    pixels[y * 8 + x] = (
                        ((p0 >> bit) & 1)
                        | (((p1 >> bit) & 1) << 1)
                        | (((p2 >> bit) & 1) << 2)
                        | (((p3 >> bit) & 1) << 3)
                    )

        elif fmt in ("genesis_4bpp", "megadrive_4bpp"):
            for i in range(32):
                b = data[i]
                pixels[i * 2] = (b >> 4) & 0x0F
                pixels[i * 2 + 1] = b & 0x0F

        elif fmt == "gba_4bpp":
            for i in range(32):
                b = data[i]
                pixels[i * 2] = b & 0x0F
                pixels[i * 2 + 1] = (b >> 4) & 0x0F

        elif fmt in ("snes_8bpp", "mode7"):
            for y in range(8):
                p0 = data[y * 2]
                p1 = data[y * 2 + 1]
                p2 = data[16 + y * 2]
                p3 = data[16 + y * 2 + 1]
                p4 = data[32 + y * 2]
                p5 = data[32 + y * 2 + 1]
                p6 = data[48 + y * 2]
                p7 = data[48 + y * 2 + 1]
                for x in range(8):
                    bit = 7 - x
                    pixels[y * 8 + x] = (
                        ((p0 >> bit) & 1)
                        | (((p1 >> bit) & 1) << 1)
                        | (((p2 >> bit) & 1) << 2)
                        | (((p3 >> bit) & 1) << 3)
                        | (((p4 >> bit) & 1) << 4)
                        | (((p5 >> bit) & 1) << 5)
                        | (((p6 >> bit) & 1) << 6)
                        | (((p7 >> bit) & 1) << 7)
                    )

        elif fmt in ("gba_8bpp", "linear_8bpp"):
            pixels = list(data[:64])

        return pixels

    @classmethod
    def encode_tile(cls, pixels: Sequence[int], format: str) -> bytes:
        """Encodes 64 indexed pixel values into raw 8x8 tile bytes."""
        if len(pixels) != 64:
            raise ValueError(f"Tile pixels must be exactly 64 elements, got {len(pixels)}")

        fmt = format.lower().replace("-", "_")
        cls.get_tile_size(fmt)

        out = bytearray()

        if fmt in ("mono_1bpp", "1bpp"):
            for y in range(8):
                row_byte = 0
                for x in range(8):
                    if pixels[y * 8 + x] & 1:
                        row_byte |= (1 << (7 - x))
                out.append(row_byte)

        elif fmt in ("nes_2bpp", "gb_2bpp", "gameboy_2bpp", "snes_2bpp", "2bpp"):
            for y in range(8):
                p0 = 0
                p1 = 0
                for x in range(8):
                    val = pixels[y * 8 + x]
                    bit = 7 - x
                    if val & 1:
                        p0 |= (1 << bit)
                    if val & 2:
                        p1 |= (1 << bit)
                out.extend([p0, p1])

        elif fmt in ("snes_3bpp", "3bpp"):
            planes_01 = bytearray()
            plane_2 = bytearray()
            for y in range(8):
                p0 = 0
                p1 = 0
                p2 = 0
                for x in range(8):
                    val = pixels[y * 8 + x]
                    bit = 7 - x
                    if val & 1:
                        p0 |= (1 << bit)
                    if val & 2:
                        p1 |= (1 << bit)
                    if val & 4:
                        p2 |= (1 << bit)
                planes_01.extend([p0, p1])
                plane_2.append(p2)
            out.extend(planes_01)
            out.extend(plane_2)

        elif fmt in ("snes_4bpp", "snes", "4bpp_planar"):
            p01 = bytearray()
            p23 = bytearray()
            for y in range(8):
                p0 = 0
                p1 = 0
                p2 = 0
                p3 = 0
                for x in range(8):
                    val = pixels[y * 8 + x]
                    bit = 7 - x
                    if val & 1:
                        p0 |= (1 << bit)
                    if val & 2:
                        p1 |= (1 << bit)
                    if val & 4:
                        p2 |= (1 << bit)
                    if val & 8:
                        p3 |= (1 << bit)
                p01.extend([p0, p1])
                p23.extend([p2, p3])
            out.extend(p01)
            out.extend(p23)

        elif fmt in ("genesis_4bpp", "megadrive_4bpp"):
            for i in range(32):
                p0 = pixels[i * 2] & 0x0F
                p1 = pixels[i * 2 + 1] & 0x0F
                out.append((p0 << 4) | p1)

        elif fmt == "gba_4bpp":
            for i in range(32):
                p0 = pixels[i * 2] & 0x0F
                p1 = pixels[i * 2 + 1] & 0x0F
                out.append((p1 << 4) | p0)

        elif fmt in ("snes_8bpp", "mode7"):
            p01 = bytearray()
            p23 = bytearray()
            p45 = bytearray()
            p67 = bytearray()
            for y in range(8):
                p = [0] * 8
                for x in range(8):
                    val = pixels[y * 8 + x]
                    bit = 7 - x
                    for plane_idx in range(8):
                        if val & (1 << plane_idx):
                            p[plane_idx] |= (1 << bit)
                p01.extend([p[0], p[1]])
                p23.extend([p[2], p[3]])
                p45.extend([p[4], p[5]])
                p67.extend([p[6], p[7]])
            out.extend(p01)
            out.extend(p23)
            out.extend(p45)
            out.extend(p67)

        elif fmt in ("gba_8bpp", "linear_8bpp"):
            out.extend([p & 0xFF for p in pixels])

        return bytes(out)

    @classmethod
    def split_bitplanes(cls, data: bytes, format: str) -> List[bytes]:
        """
        Splits tile bytes into individual 8-byte bitplanes.
        Each bitplane has 8 bytes (1 byte per row, bit 7 to bit 0).
        """
        pixels = cls.decode_tile(data, format)
        bpp = cls.get_bpp(format)
        planes = []

        for p in range(bpp):
            plane_bytes = bytearray(8)
            for y in range(8):
                row_byte = 0
                for x in range(8):
                    if pixels[y * 8 + x] & (1 << p):
                        row_byte |= (1 << (7 - x))
                plane_bytes[y] = row_byte
            planes.append(bytes(plane_bytes))

        return planes

    @classmethod
    def combine_bitplanes(cls, planes: Sequence[bytes], format: str) -> bytes:
        """
        Combines individual 8-byte bitplanes into console tile byte representation.
        """
        bpp = cls.get_bpp(format)
        if len(planes) < bpp:
            raise ValueError(f"Expected at least {bpp} bitplanes for {format}, got {len(planes)}")

        pixels = [0] * 64
        for p in range(bpp):
            plane_data = planes[p]
            for y in range(8):
                b = plane_data[y]
                for x in range(8):
                    if (b >> (7 - x)) & 1:
                        pixels[y * 8 + x] |= (1 << p)

        return cls.encode_tile(pixels, format)

    @classmethod
    def planar_to_linear(cls, tiles_data: bytes, format: str) -> bytes:
        """
        Bulk converts raw planar tile byte stream to linear indexed bytes (1 byte per pixel).
        """
        tile_size = cls.get_tile_size(format)
        num_tiles = len(tiles_data) // tile_size
        out = bytearray()

        for i in range(num_tiles):
            tile_chunk = tiles_data[i * tile_size : (i + 1) * tile_size]
            pixels = cls.decode_tile(tile_chunk, format)
            out.extend(pixels)

        return bytes(out)

    @classmethod
    def linear_to_planar(cls, linear_data: bytes, format: str) -> bytes:
        """
        Bulk converts linear indexed bytes (64 bytes per tile) to console planar tile stream.
        """
        num_tiles = len(linear_data) // 64
        out = bytearray()

        for i in range(num_tiles):
            pixels = list(linear_data[i * 64 : (i + 1) * 64])
            out.extend(cls.encode_tile(pixels, format))

        return bytes(out)


def decode_planar_tile(data: bytes, format: str) -> List[int]:
    return PlanarTileCodec.decode_tile(data, format)


def encode_planar_tile(pixels: Sequence[int], format: str) -> bytes:
    return PlanarTileCodec.encode_tile(pixels, format)


def split_tile_bitplanes(data: bytes, format: str) -> List[bytes]:
    return PlanarTileCodec.split_bitplanes(data, format)


def combine_tile_bitplanes(planes: Sequence[bytes], format: str) -> bytes:
    return PlanarTileCodec.combine_bitplanes(planes, format)
