import struct
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict
from miorom.graphics.tiles import Tile


@dataclass
class TilemapEntry:
    tile_index: int
    flip_x: bool = False
    flip_y: bool = False
    palette_bank: int = 0
    priority: int = 0

    def to_u16(self, fmt: str = "gba") -> int:
        if fmt.lower() in ("gba", "nds"):
            # Bits 0-9: tile index (0-1023)
            # Bit 10: Horizontal flip
            # Bit 11: Vertical flip
            # Bits 12-15: Palette bank
            val = (self.tile_index & 0x3FF)
            if self.flip_x:
                val |= 1 << 10
            if self.flip_y:
                val |= 1 << 11
            val |= (self.palette_bank & 0x0F) << 12
            return val
        elif fmt.lower() == "snes":
            # SNES tilemap entry:
            # Bits 0-9: tile index
            # Bits 10-12: palette (0-7)
            # Bit 13: priority
            # Bit 14: flip X
            # Bit 15: flip Y
            val = (self.tile_index & 0x3FF)
            val |= (self.palette_bank & 0x07) << 10
            if self.priority:
                val |= 1 << 13
            if self.flip_x:
                val |= 1 << 14
            if self.flip_y:
                val |= 1 << 15
            return val
        else:
            raise ValueError(f"Unknown tilemap format: {fmt}")

    @classmethod
    def from_u16(cls, val: int, fmt: str = "gba") -> "TilemapEntry":
        if fmt.lower() in ("gba", "nds"):
            tile_idx = val & 0x3FF
            flip_x = bool(val & (1 << 10))
            flip_y = bool(val & (1 << 11))
            pal = (val >> 12) & 0x0F
            return cls(tile_index=tile_idx, flip_x=flip_x, flip_y=flip_y, palette_bank=pal)
        elif fmt.lower() == "snes":
            tile_idx = val & 0x3FF
            pal = (val >> 10) & 0x07
            priority = 1 if (val & (1 << 13)) else 0
            flip_x = bool(val & (1 << 14))
            flip_y = bool(val & (1 << 15))
            return cls(tile_index=tile_idx, flip_x=flip_x, flip_y=flip_y, palette_bank=pal, priority=priority)
        else:
            raise ValueError(f"Unknown tilemap format: {fmt}")


class Tilemap:
    """Represents a 2D tilemap (screen block)."""

    def __init__(self, width: int, height: int, entries: Optional[List[TilemapEntry]] = None):
        self.width = width
        self.height = height
        self.entries = entries or []

    def get_entry(self, x: int, y: int) -> TilemapEntry:
        return self.entries[y * self.width + x]

    def set_entry(self, x: int, y: int, entry: TilemapEntry):
        self.entries[y * self.width + x] = entry

    def to_bytes(self, fmt: str = "gba") -> bytes:
        out = bytearray()
        for e in self.entries:
            out.extend(struct.pack("<H", e.to_u16(fmt=fmt)))
        return bytes(out)

    @classmethod
    def from_bytes(cls, data: bytes, width: int, height: int, fmt: str = "gba") -> "Tilemap":
        entries = []
        count = width * height
        for i in range(count):
            val = struct.unpack_from("<H", data, i * 2)[0]
            entries.append(TilemapEntry.from_u16(val, fmt=fmt))
        return cls(width=width, height=height, entries=entries)


class TileReducer:
    """
    Optimizes tile sets by eliminating duplicate tiles and detecting horizontal/vertical flips.
    Crucial for fitting translated graphics into limited VRAM and ROM space.
    """

    @classmethod
    def reduce(
        cls, tiles: List[Tile], allow_flip: bool = True
    ) -> Tuple[List[Tile], List[TilemapEntry]]:
        unique_tiles: List[Tile] = []
        tile_lookup: Dict[Tile, int] = {}
        entries: List[TilemapEntry] = []

        for tile in tiles:
            # Check direct match
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

            # New unique tile
            new_idx = len(unique_tiles)
            unique_tiles.append(tile)
            tile_lookup[tile] = new_idx
            entries.append(TilemapEntry(tile_index=new_idx))

        return unique_tiles, entries
