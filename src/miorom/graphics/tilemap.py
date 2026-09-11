"""
miorom.graphics.tilemap
~~~~~~~~~~~~~~~~~~~~~~~
Multi-console tilemap and nametable compositor, attribute table decoder,
and 2D tile matrix renderer for NES, SNES, Genesis, Game Boy, and GBA/NDS.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union
import struct

from miorom.errors import ParseError
from miorom.graphics.tiles import Tile
from miorom.result import MioRomResult


@dataclass
class TilemapEntry(MioRomResult):
    """
    Represents a single tile entry in a 2D tilemap with placement attributes.
    """
    tile_index: int
    flip_x: bool = False
    flip_y: bool = False
    palette_bank: int = 0
    priority: int = 0
    vram_bank: int = 0

    def __hash__(self) -> int:
        return hash((self.tile_index, self.flip_x, self.flip_y, self.palette_bank, self.priority, self.vram_bank))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TilemapEntry):
            return False
        return (
            self.tile_index == other.tile_index
            and self.flip_x == other.flip_x
            and self.flip_y == other.flip_y
            and self.palette_bank == other.palette_bank
            and self.priority == other.priority
            and self.vram_bank == other.vram_bank
        )

    def to_u16(self, fmt: str = "gba") -> int:
        """Encode entry attributes into a 16-bit integer word."""
        fmt_lower = fmt.lower()
        if fmt_lower in ("gba", "nds"):
            val = self.tile_index & 0x3FF
            if self.flip_x:
                val |= 1 << 10
            if self.flip_y:
                val |= 1 << 11
            val |= (self.palette_bank & 0x0F) << 12
            return val
        elif fmt_lower == "snes":
            val = self.tile_index & 0x3FF
            val |= (self.palette_bank & 0x07) << 10
            if self.priority:
                val |= 1 << 13
            if self.flip_x:
                val |= 1 << 14
            if self.flip_y:
                val |= 1 << 15
            return val
        elif fmt_lower in ("genesis", "md", "megadrive"):
            val = self.tile_index & 0x7FF
            if self.flip_x:
                val |= 1 << 11
            if self.flip_y:
                val |= 1 << 12
            val |= (self.palette_bank & 0x03) << 13
            if self.priority:
                val |= 1 << 15
            return val
        elif fmt_lower == "gbc":
            # GBC packed 16-bit format
            attr = self.palette_bank & 0x07
            if self.vram_bank:
                attr |= 1 << 3
            if self.flip_x:
                attr |= 1 << 5
            if self.flip_y:
                attr |= 1 << 6
            if self.priority:
                attr |= 1 << 7
            return (self.tile_index & 0xFF) | (attr << 8)
        else:
            raise ParseError(f"Unknown tilemap format: {fmt}")

    @classmethod
    def from_u16(cls, val: int, fmt: str = "gba") -> "TilemapEntry":
        """Decode a 16-bit integer word into a TilemapEntry."""
        fmt_lower = fmt.lower()
        if fmt_lower in ("gba", "nds"):
            tile_idx = val & 0x3FF
            flip_x = bool(val & (1 << 10))
            flip_y = bool(val & (1 << 11))
            pal = (val >> 12) & 0x0F
            return cls(tile_index=tile_idx, flip_x=flip_x, flip_y=flip_y, palette_bank=pal)
        elif fmt_lower == "snes":
            tile_idx = val & 0x3FF
            pal = (val >> 10) & 0x07
            priority = 1 if (val & (1 << 13)) else 0
            flip_x = bool(val & (1 << 14))
            flip_y = bool(val & (1 << 15))
            return cls(
                tile_index=tile_idx,
                flip_x=flip_x,
                flip_y=flip_y,
                palette_bank=pal,
                priority=priority,
            )
        elif fmt_lower in ("genesis", "md", "megadrive"):
            tile_idx = val & 0x7FF
            flip_x = bool(val & (1 << 11))
            flip_y = bool(val & (1 << 12))
            pal = (val >> 13) & 0x03
            priority = 1 if (val & (1 << 15)) else 0
            return cls(
                tile_index=tile_idx,
                flip_x=flip_x,
                flip_y=flip_y,
                palette_bank=pal,
                priority=priority,
            )
        elif fmt_lower == "gbc":
            tile_idx = val & 0xFF
            attr = (val >> 8) & 0xFF
            pal = attr & 0x07
            vram_bank = 1 if (attr & (1 << 3)) else 0
            flip_x = bool(attr & (1 << 5))
            flip_y = bool(attr & (1 << 6))
            priority = 1 if (attr & (1 << 7)) else 0
            return cls(
                tile_index=tile_idx,
                flip_x=flip_x,
                flip_y=flip_y,
                palette_bank=pal,
                priority=priority,
                vram_bank=vram_bank,
            )
        else:
            raise ParseError(f"Unknown tilemap format: {fmt}")


class Tilemap(MioRomResult):
    """
    Represents a 2D tilemap matrix of configurable width and height.
    """

    def __init__(
        self,
        width: int,
        height: int,
        entries: Optional[List[TilemapEntry]] = None,
    ):
        self.width = width
        self.height = height
        total = width * height
        if entries is not None:
            if len(entries) != total:
                raise ValueError(
                    f"Entry count {len(entries)} does not match grid dimensions {width}x{height} ({total})"
                )
            self.entries: List[TilemapEntry] = list(entries)
        else:
            self.entries = [TilemapEntry(tile_index=0) for _ in range(total)]

    def get_entry(self, x: int, y: int) -> TilemapEntry:
        """Get entry at column x and row y."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            raise IndexError(f"Coordinates ({x}, {y}) out of range for {self.width}x{self.height} tilemap")
        return self.entries[y * self.width + x]

    def set_entry(self, x: int, y: int, entry: TilemapEntry) -> None:
        """Set entry at column x and row y."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            raise IndexError(f"Coordinates ({x}, {y}) out of range for {self.width}x{self.height} tilemap")
        self.entries[y * self.width + x] = entry

    def submap(self, x: int, y: int, w: int, h: int) -> "Tilemap":
        """Extract a rectangular region as an independent submap."""
        if x < 0 or y < 0 or x + w > self.width or y + h > self.height:
            raise ValueError("Submap rectangle exceeds tilemap boundaries")
        sub_entries: List[TilemapEntry] = []
        for row in range(y, y + h):
            for col in range(x, x + w):
                sub_entries.append(self.get_entry(col, row))
        return Tilemap(width=w, height=h, entries=sub_entries)

    def paste(self, source: "Tilemap", dest_x: int, dest_y: int) -> None:
        """Paste another tilemap into this tilemap at destination coordinates."""
        for sy in range(source.height):
            dy = dest_y + sy
            if 0 <= dy < self.height:
                for sx in range(source.width):
                    dx = dest_x + sx
                    if 0 <= dx < self.width:
                        self.set_entry(dx, dy, source.get_entry(sx, sy))

    def to_bytes(self, fmt: str = "gba", endian: Optional[str] = None) -> bytes:
        """Serialize entries to binary bytes."""
        if endian is None:
            endian = ">" if fmt.lower() in ("genesis", "md", "megadrive") else "<"
        out = bytearray()
        for e in self.entries:
            val = e.to_u16(fmt=fmt)
            out.extend(struct.pack(f"{endian}H", val))
        return bytes(out)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        width: int,
        height: int,
        fmt: str = "gba",
        endian: Optional[str] = None,
        offset: int = 0,
    ) -> "Tilemap":
        """Deserialize tilemap from raw binary bytes."""
        if endian is None:
            endian = ">" if fmt.lower() in ("genesis", "md", "megadrive") else "<"
        count = width * height
        needed = offset + count * 2
        if len(data) < needed:
            raise ValueError(
                f"Data length {len(data)} is insufficient for {count} entries at offset {offset}"
            )

        entries: List[TilemapEntry] = []
        pos = offset
        for _ in range(count):
            val = struct.unpack_from(f"{endian}H", data, pos)[0]
            entries.append(TilemapEntry.from_u16(val, fmt=fmt))
            pos += 2
        return cls(width=width, height=height, entries=entries)

    def render_pixels(
        self,
        tiles: Sequence[Tile],
        combine_palette: bool = False,
        colors_per_palette: int = 16,
    ) -> List[List[int]]:
        """
        Composite the tilemap into a 2D pixel grid of shape (height * 8, width * 8).
        """
        pixel_width = self.width * 8
        pixel_height = self.height * 8
        canvas = [[0] * pixel_width for _ in range(pixel_height)]

        num_tiles = len(tiles)
        for ty in range(self.height):
            for tx in range(self.width):
                entry = self.get_entry(tx, ty)
                if 0 <= entry.tile_index < num_tiles:
                    tile = tiles[entry.tile_index]
                else:
                    tile = Tile([0] * 64)

                if entry.flip_x:
                    tile = tile.flip_x()
                if entry.flip_y:
                    tile = tile.flip_y()

                palette_offset = entry.palette_bank * colors_per_palette if combine_palette else 0
                base_y = ty * 8
                base_x = tx * 8
                for py in range(8):
                    for px in range(8):
                        raw_color = tile.get_pixel(px, py)
                        if combine_palette and raw_color > 0:
                            canvas[base_y + py][base_x + px] = palette_offset + raw_color
                        else:
                            canvas[base_y + py][base_x + px] = raw_color

        return canvas

    def render_flat_pixels(
        self,
        tiles: Sequence[Tile],
        combine_palette: bool = False,
        colors_per_palette: int = 16,
    ) -> List[int]:
        """
        Composite the tilemap into a 1D flat pixel array of length (width * 8 * height * 8).
        """
        rows = self.render_pixels(
            tiles=tiles,
            combine_palette=combine_palette,
            colors_per_palette=colors_per_palette,
        )
        flat: List[int] = []
        for row in rows:
            flat.extend(row)
        return flat


def decode_nes_nametable(data: bytes, offset: int = 0) -> Tilemap:
    """
    Decode a standard NES nametable (960 tile bytes + 64 attribute bytes = 1024 bytes).
    Constructs a 32x30 Tilemap with palette assignments derived from attribute data.
    """
    needed = offset + 1024
    if len(data) < needed:
        raise ValueError(f"NES nametable requires 1024 bytes, available {len(data) - offset}")

    nametable_bytes = data[offset : offset + 960]
    attribute_bytes = data[offset + 960 : offset + 1024]

    entries: List[TilemapEntry] = []
    for y in range(30):
        for x in range(32):
            tile_idx = nametable_bytes[y * 32 + x]
            attr_x = x // 4
            attr_y = y // 4
            sub_x = (x % 4) // 2
            sub_y = (y % 4) // 2
            shift = (sub_y * 2 + sub_x) * 2
            attr_val = attribute_bytes[attr_y * 8 + attr_x]
            pal = (attr_val >> shift) & 0x03
            entries.append(TilemapEntry(tile_index=tile_idx, palette_bank=pal))

    return Tilemap(width=32, height=30, entries=entries)


def encode_nes_nametable(tilemap: Tilemap) -> bytes:
    """
    Encode a 32x30 Tilemap into a standard NES nametable + attribute table (1024 bytes).
    """
    if tilemap.width != 32 or tilemap.height != 30:
        raise ValueError(
            f"NES nametable must be 32x30 tiles, got {tilemap.width}x{tilemap.height}"
        )

    out = bytearray(1024)
    # Write 960 bytes of nametable tile indices
    for i, entry in enumerate(tilemap.entries):
        out[i] = entry.tile_index & 0xFF

    # Synthesize 64 bytes of attribute table
    for y in range(30):
        for x in range(32):
            entry = tilemap.get_entry(x, y)
            attr_x = x // 4
            attr_y = y // 4
            sub_x = (x % 4) // 2
            sub_y = (y % 4) // 2
            shift = (sub_y * 2 + sub_x) * 2
            mask = 0x03 << shift
            pal_bits = (entry.palette_bank & 0x03) << shift
            attr_pos = 960 + (attr_y * 8 + attr_x)
            out[attr_pos] = (out[attr_pos] & ~mask) | pal_bits

    return bytes(out)


def decode_genesis_tilemap(
    data: bytes,
    width: int,
    height: int,
    offset: int = 0,
    endian: str = ">",
) -> Tilemap:
    """
    Decode a Sega Genesis VDP Plane tilemap from 16-bit entries.
    """
    return Tilemap.from_bytes(data, width=width, height=height, fmt="genesis", endian=endian, offset=offset)


def encode_genesis_tilemap(tilemap: Tilemap, endian: str = ">") -> bytes:
    """
    Encode a Tilemap into Sega Genesis VDP Plane 16-bit entries.
    """
    return tilemap.to_bytes(fmt="genesis", endian=endian)


def decode_gbc_tilemap(
    vram0_data: bytes,
    vram1_data: bytes,
    width: int = 32,
    height: int = 32,
    offset0: int = 0,
    offset1: int = 0,
) -> Tilemap:
    """
    Decode Game Boy Color tilemap from parallel VRAM bank 0 (tiles) and bank 1 (attributes).
    """
    total = width * height
    if len(vram0_data) < offset0 + total:
        raise ValueError("vram0_data too short for GBC tile indices")
    if len(vram1_data) < offset1 + total:
        raise ValueError("vram1_data too short for GBC attributes")

    entries: List[TilemapEntry] = []
    for i in range(total):
        tile_idx = vram0_data[offset0 + i]
        attr = vram1_data[offset1 + i]
        pal = attr & 0x07
        vram_bank = 1 if (attr & (1 << 3)) else 0
        flip_x = bool(attr & (1 << 5))
        flip_y = bool(attr & (1 << 6))
        priority = 1 if (attr & (1 << 7)) else 0
        entries.append(
            TilemapEntry(
                tile_index=tile_idx,
                flip_x=flip_x,
                flip_y=flip_y,
                palette_bank=pal,
                priority=priority,
                vram_bank=vram_bank,
            )
        )
    return Tilemap(width=width, height=height, entries=entries)


def encode_gbc_tilemap(tilemap: Tilemap) -> Tuple[bytes, bytes]:
    """
    Encode a Tilemap into parallel GBC VRAM bank 0 (tile indices) and bank 1 (attributes).
    """
    vram0 = bytearray(tilemap.width * tilemap.height)
    vram1 = bytearray(tilemap.width * tilemap.height)
    for i, entry in enumerate(tilemap.entries):
        vram0[i] = entry.tile_index & 0xFF
        attr = entry.palette_bank & 0x07
        if entry.vram_bank:
            attr |= 1 << 3
        if entry.flip_x:
            attr |= 1 << 5
        if entry.flip_y:
            attr |= 1 << 6
        if entry.priority:
            attr |= 1 << 7
        vram1[i] = attr
    return bytes(vram0), bytes(vram1)


class TileReducer:
    """
    Optimizes tile sets by eliminating duplicate tiles and detecting horizontal/vertical flips.
    Crucial for fitting translated graphics into limited VRAM and ROM space.
    """

    @classmethod
    def reduce(
        cls, tiles: List[Tile], allow_flip: bool = True
    ) -> Tuple[List[Tile], List[TilemapEntry]]:
        """Deduplicate tile list while producing corresponding tilemap entries."""
        unique_tiles: List[Tile] = []
        tile_lookup: Dict[Tile, int] = {}
        entries: List[TilemapEntry] = []

        for tile in tiles:
            if tile in tile_lookup:
                entries.append(TilemapEntry(tile_index=tile_lookup[tile]))
                continue

            if allow_flip:
                fx = tile.flip_x()
                if fx in tile_lookup:
                    entries.append(TilemapEntry(tile_index=tile_lookup[fx], flip_x=True))
                    continue

                fy = tile.flip_y()
                if fy in tile_lookup:
                    entries.append(TilemapEntry(tile_index=tile_lookup[fy], flip_y=True))
                    continue

                fxy = fx.flip_y()
                if fxy in tile_lookup:
                    entries.append(TilemapEntry(tile_index=tile_lookup[fxy], flip_x=True, flip_y=True))
                    continue

            new_idx = len(unique_tiles)
            unique_tiles.append(tile)
            tile_lookup[tile] = new_idx
            entries.append(TilemapEntry(tile_index=new_idx))

        return unique_tiles, entries
