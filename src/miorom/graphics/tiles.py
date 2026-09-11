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


def decode_tile(
    data: bytes,
    bpp: int = 4,
    planar: bool = False,
    high_nibble_first: bool = False,
    format: Optional[str] = None,
) -> Tile:
    """Decodes 8x8 tile from raw binary data according to bit depth and layout."""
    if format:
        fmt = format.lower().replace("-", "_")
        from miorom.graphics.planar import PlanarTileCodec
        format_map = {
            "md": "genesis_4bpp",
            "genesis": "genesis_4bpp",
            "megadrive": "genesis_4bpp",
            "snes4": "snes_4bpp",
            "snes_4bpp": "snes_4bpp",
            "snes": "snes_4bpp",
            "snes8": "snes_8bpp",
            "snes_8bpp": "snes_8bpp",
            "mode7": "mode7",
            "gb": "gb_2bpp",
            "nes": "nes_2bpp",
            "gameboy": "gb_2bpp",
            "gba": "gba_4bpp",
            "nds": "gba_4bpp",
        }
        target_fmt = format_map.get(fmt, fmt)
        if target_fmt in PlanarTileCodec.FORMAT_SIZES:
            pixels = PlanarTileCodec.decode_tile(data, target_fmt)
            return Tile(pixels)

    tile_sizes = {1: 8, 2: 16, 4: 32, 8: 64}
    expected_size = tile_sizes.get(bpp)
    if not expected_size:
        raise ParseError(f"Unsupported bit depth: {bpp}bpp")

    if len(data) < expected_size:
        raise ParseError(f"Data too short for {bpp}bpp tile: expected {expected_size} bytes, got {len(data)}")

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
            if high_nibble_first:
                # Sega Genesis / Mega Drive 4bpp chunky: high nibble first
                for i in range(32):
                    b = data[i]
                    pixels[i * 2] = (b >> 4) & 0x0F
                    pixels[i * 2 + 1] = b & 0x0F
            else:
                # GBA / NDS 4bpp chunky: 2 pixels per byte, low nibble first
                for i in range(32):
                    b = data[i]
                    pixels[i * 2] = b & 0x0F
                    pixels[i * 2 + 1] = (b >> 4) & 0x0F

    elif bpp == 8:
        if planar:
            # SNES 8bpp planar (Mode 3/4/7): 64 bytes per tile
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
                    val = (
                        ((p0 >> bit) & 1)
                        | (((p1 >> bit) & 1) << 1)
                        | (((p2 >> bit) & 1) << 2)
                        | (((p3 >> bit) & 1) << 3)
                        | (((p4 >> bit) & 1) << 4)
                        | (((p5 >> bit) & 1) << 5)
                        | (((p6 >> bit) & 1) << 6)
                        | (((p7 >> bit) & 1) << 7)
                    )
                    pixels[y * 8 + x] = val
        else:
            # 8bpp linear: 64 bytes per tile (1 byte per pixel)
            pixels = list(data[:64])

    return Tile(pixels)


def encode_tile(
    tile: Tile,
    bpp: int = 4,
    planar: bool = False,
    high_nibble_first: bool = False,
    format: Optional[str] = None,
) -> bytes:
    """Encodes 8x8 tile into raw binary data."""
    if format:
        fmt = format.lower().replace("-", "_")
        from miorom.graphics.planar import PlanarTileCodec
        format_map = {
            "md": "genesis_4bpp",
            "genesis": "genesis_4bpp",
            "megadrive": "genesis_4bpp",
            "snes4": "snes_4bpp",
            "snes_4bpp": "snes_4bpp",
            "snes": "snes_4bpp",
            "snes8": "snes_8bpp",
            "snes_8bpp": "snes_8bpp",
            "mode7": "mode7",
            "gb": "gb_2bpp",
            "nes": "nes_2bpp",
            "gameboy": "gb_2bpp",
            "gba": "gba_4bpp",
            "nds": "gba_4bpp",
        }
        target_fmt = format_map.get(fmt, fmt)
        if target_fmt in PlanarTileCodec.FORMAT_SIZES:
            return PlanarTileCodec.encode_tile(tile.pixels, target_fmt)

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
            if high_nibble_first:
                for i in range(32):
                    p0 = tile.pixels[i * 2] & 0x0F
                    p1 = tile.pixels[i * 2 + 1] & 0x0F
                    out.append((p0 << 4) | p1)
            else:
                for i in range(32):
                    p0 = tile.pixels[i * 2] & 0x0F
                    p1 = tile.pixels[i * 2 + 1] & 0x0F
                    out.append(p0 | (p1 << 4))

    elif bpp == 8:
        if planar:
            plane0_1 = bytearray()
            plane2_3 = bytearray()
            plane4_5 = bytearray()
            plane6_7 = bytearray()
            for y in range(8):
                p0 = p1 = p2 = p3 = p4 = p5 = p6 = p7 = 0
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
                    if val & 16:
                        p4 |= 1 << bit
                    if val & 32:
                        p5 |= 1 << bit
                    if val & 64:
                        p6 |= 1 << bit
                    if val & 128:
                        p7 |= 1 << bit
                plane0_1.extend([p0, p1])
                plane2_3.extend([p2, p3])
                plane4_5.extend([p4, p5])
                plane6_7.extend([p6, p7])
            out.extend(plane0_1)
            out.extend(plane2_3)
            out.extend(plane4_5)
            out.extend(plane6_7)
        else:
            for val in tile.pixels:
                out.append(val & 0xFF)
    else:
        raise ParseError(f"Unsupported bit depth: {bpp}bpp")

    return bytes(out)


def decode_tileset(
    data: bytes,
    bpp: int = 4,
    planar: bool = False,
    high_nibble_first: bool = False,
    format: Optional[str] = None,
) -> List[Tile]:
    if format:
        fmt = format.lower().replace("-", "_")
        if fmt in ("md", "genesis", "megadrive"):
            bpp = 4
            planar = False
            high_nibble_first = True
        elif fmt in ("snes4", "snes_4bpp", "snes"):
            bpp = 4
            planar = True
        elif fmt in ("snes8", "snes_8bpp", "mode7"):
            bpp = 8
            planar = True
        elif fmt in ("gb", "nes", "gameboy"):
            bpp = 2
            planar = True
        elif fmt in ("gba", "nds"):
            bpp = 4
            planar = False
            high_nibble_first = False

    tile_sizes = {1: 8, 2: 16, 4: 32, 8: 64}
    size = tile_sizes.get(bpp)
    if not size:
        raise ParseError(f"Unsupported bpp: {bpp}")

    tiles = []
    for i in range(0, len(data) - size + 1, size):
        tiles.append(
            decode_tile(
                data[i : i + size],
                bpp=bpp,
                planar=planar,
                high_nibble_first=high_nibble_first,
            )
        )
    return tiles


def encode_tileset(
    tiles: List[Tile],
    bpp: int = 4,
    planar: bool = False,
    high_nibble_first: bool = False,
    format: Optional[str] = None,
) -> bytes:
    out = bytearray()
    for t in tiles:
        out.extend(
            encode_tile(
                t,
                bpp=bpp,
                planar=planar,
                high_nibble_first=high_nibble_first,
                format=format,
            )
        )
    return bytes(out)
