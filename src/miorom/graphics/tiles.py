from typing import List, Tuple, Optional
from miorom.errors import ParseError


class Tile:
    """Represents an 8x8 indexed pixel tile."""

    def __init__(self, pixels: Optional[List[int]] = None):
        if pixels is not None:
            if len(pixels) != 64:
                raise ParseError("Tile pixels must be exactly 64 elements (8x8).")
            self.pixels = list(pixels)
        else:
            self.pixels = [0] * 64

    def get_pixel(self, x: int, y: int) -> int:
        return self.pixels[y * 8 + x]

    def set_pixel(self, x: int, y: int, val: int):
        self.pixels[y * 8 + x] = val

    def flip_x(self) -> "Tile":
        new_pixels = [0] * 64
        for y in range(8):
            for x in range(8):
                new_pixels[y * 8 + (7 - x)] = self.pixels[y * 8 + x]
        return Tile(new_pixels)

    def flip_y(self) -> "Tile":
        new_pixels = [0] * 64
        for y in range(8):
            for x in range(8):
                new_pixels[(7 - y) * 8 + x] = self.pixels[y * 8 + x]
        return Tile(new_pixels)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Tile):
            return False
        return self.pixels == other.pixels

    def __hash__(self) -> int:
        return hash(tuple(self.pixels))


def decode_tile(data: bytes, bpp: int = 4, planar: bool = False) -> Tile:
    """Decodes 8x8 tile from raw binary data according to bit depth."""
    pixels = [0] * 64

    if bpp == 1:
        # 1 bit per pixel: 8 bytes per tile (1 byte per row, MSB to LSB)
        for y in range(8):
            b = data[y]
            for x in range(8):
                pixels[y * 8 + x] = (b >> (7 - x)) & 1

    elif bpp == 2:
        # 2bpp planar (Game Boy / NES): 16 bytes per tile
        # 2 bytes per row: plane0, plane1
        for y in range(8):
            p0 = data[y * 2]
            p1 = data[y * 2 + 1]
            for x in range(8):
                bit = 7 - x
                val = ((p0 >> bit) & 1) | (((p1 >> bit) & 1) << 1)
                pixels[y * 8 + x] = val

    elif bpp == 4:
        if planar:
            # SNES 4bpp planar: 32 bytes per tile
            # Bytes 0-15: bitplanes 0, 1 (interleaved like 2bpp)
            # Bytes 16-31: bitplanes 2, 3 (interleaved)
            for y in range(8):
                p0 = data[y * 2]
                p1 = data[y * 2 + 1]
                p2 = data[16 + y * 2]
                p3 = data[16 + y * 2 + 1]
                for x in range(8):
                    bit = 7 - x
                    val = (
                        ((p0 >> bit) & 1)
                        | (((p1 >> bit) & 1) << 1)
                        | (((p2 >> bit) & 1) << 2)
                        | (((p3 >> bit) & 1) << 3)
                    )
                    pixels[y * 8 + x] = val
        else:
            # GBA / NDS 4bpp chunky: 32 bytes per tile (2 pixels per byte, low nibble first)
            for i in range(32):
                b = data[i]
                pixels[i * 2] = b & 0x0F
                pixels[i * 2 + 1] = (b >> 4) & 0x0F

    elif bpp == 8:
        # 8bpp linear: 64 bytes per tile (1 byte per pixel)
        pixels = list(data[:64])
    else:
        raise ParseError(f"Unsupported bit depth: {bpp}bpp")

    return Tile(pixels)


def encode_tile(tile: Tile, bpp: int = 4, planar: bool = False) -> bytes:
    """Encodes 8x8 tile into raw binary data."""
    out = bytearray()

    if bpp == 1:
        for y in range(8):
            row_byte = 0
            for x in range(8):
                if tile.get_pixel(x, y) & 1:
                    row_byte |= 1 << (7 - x)
            out.append(row_byte)

    elif bpp == 2:
        for y in range(8):
            p0 = 0
            p1 = 0
            for x in range(8):
                val = tile.get_pixel(x, y)
                bit = 7 - x
                if val & 1:
                    p0 |= 1 << bit
                if val & 2:
                    p1 |= 1 << bit
            out.extend([p0, p1])

    elif bpp == 4:
        if planar:
            plane0_1 = bytearray()
            plane2_3 = bytearray()
            for y in range(8):
                p0 = 0
                p1 = 0
                p2 = 0
                p3 = 0
                for x in range(8):
                    val = tile.get_pixel(x, y)
                    bit = 7 - x
                    if val & 1:
                        p0 |= 1 << bit
                    if val & 2:
                        p1 |= 1 << bit
                    if val & 4:
                        p2 |= 1 << bit
                    if val & 8:
                        p3 |= 1 << bit
                plane0_1.extend([p0, p1])
                plane2_3.extend([p2, p3])
            out.extend(plane0_1)
            out.extend(plane2_3)
        else:
            for i in range(32):
                p0 = tile.pixels[i * 2] & 0x0F
                p1 = tile.pixels[i * 2 + 1] & 0x0F
                out.append(p0 | (p1 << 4))

    elif bpp == 8:
        for val in tile.pixels:
            out.append(val & 0xFF)
    else:
        raise ParseError(f"Unsupported bit depth: {bpp}bpp")

    return bytes(out)


def decode_tileset(data: bytes, bpp: int = 4, planar: bool = False) -> List[Tile]:
    tile_sizes = {1: 8, 2: 16, 4: 32, 8: 64}
    size = tile_sizes.get(bpp)
    if not size:
        raise ParseError(f"Unsupported bpp: {bpp}")

    tiles = []
    for i in range(0, len(data) - size + 1, size):
        tiles.append(decode_tile(data[i : i + size], bpp=bpp, planar=planar))
    return tiles


def encode_tileset(tiles: List[Tile], bpp: int = 4, planar: bool = False) -> bytes:
    out = bytearray()
    for t in tiles:
        out.extend(encode_tile(t, bpp=bpp, planar=planar))
    return bytes(out)
