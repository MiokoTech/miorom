"""
miorom.graphics.metatile
~~~~~~~~~~~~~~~~~~~~~~~~
16x16 and 32x32 metatile assembly, level map expansion, and compression
engine for retro console architectures (NES, Game Boy, SNES, Genesis, GBA).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union
import struct

from miorom.graphics.tilemap import Tilemap, TilemapEntry
from miorom.result import MioRomResult


@dataclass
class Metatile16(MioRomResult):
    """
    A 16x16 pixel metatile composed of four 8x8 TilemapEntry blocks.
    """
    index: int
    tl: TilemapEntry
    tr: TilemapEntry
    bl: TilemapEntry
    br: TilemapEntry

    @property
    def tiles(self) -> Tuple[TilemapEntry, TilemapEntry, TilemapEntry, TilemapEntry]:
        """Return the four corner tiles as a tuple."""
        return self.tl, self.tr, self.bl, self.br


class MetatileTable(MioRomResult):
    """
    Dictionary and registry of 16x16 metatile definitions.
    """

    def __init__(self, metatiles: Optional[Dict[int, Metatile16]] = None):
        self.metatiles: Dict[int, Metatile16] = metatiles or {}

    def get(self, index: int) -> Optional[Metatile16]:
        """Retrieve metatile by index."""
        return self.metatiles.get(index)

    def add(self, metatile: Metatile16) -> None:
        """Register or overwrite a metatile definition."""
        self.metatiles[metatile.index] = metatile

    def __len__(self) -> int:
        return len(self.metatiles)

    def __iter__(self):
        return iter(self.metatiles.values())

    @classmethod
    def unpack_sequential_bytes(
        cls,
        data: bytes,
        count: int,
        offset: int = 0,
        fmt: str = "nes",
        endian: str = "<",
    ) -> "MetatileTable":
        """
        Unpack metatiles from sequential binary records.
        For 8-bit consoles (NES/GB), each metatile is 4 bytes [tl, tr, bl, br].
        For 16-bit consoles (SNES/Genesis/GBA), each metatile is 4 u16 words (8 bytes).
        """
        table = cls()
        pos = offset
        is_16bit = fmt.lower() in ("snes", "genesis", "md", "megadrive", "gba", "nds", "gbc")
        stride = 8 if is_16bit else 4

        for idx in range(count):
            if pos + stride > len(data):
                break
            if is_16bit:
                w_tl = struct.unpack_from(f"{endian}H", data, pos)[0]
                w_tr = struct.unpack_from(f"{endian}H", data, pos + 2)[0]
                w_bl = struct.unpack_from(f"{endian}H", data, pos + 4)[0]
                w_br = struct.unpack_from(f"{endian}H", data, pos + 6)[0]
                e_tl = TilemapEntry.from_u16(w_tl, fmt=fmt)
                e_tr = TilemapEntry.from_u16(w_tr, fmt=fmt)
                e_bl = TilemapEntry.from_u16(w_bl, fmt=fmt)
                e_br = TilemapEntry.from_u16(w_br, fmt=fmt)
            else:
                e_tl = TilemapEntry(tile_index=data[pos])
                e_tr = TilemapEntry(tile_index=data[pos + 1])
                e_bl = TilemapEntry(tile_index=data[pos + 2])
                e_br = TilemapEntry(tile_index=data[pos + 3])

            table.add(Metatile16(index=idx, tl=e_tl, tr=e_tr, bl=e_bl, br=e_br))
            pos += stride

        return table

    @classmethod
    def unpack_planar_bytes(
        cls,
        data: bytes,
        count: int,
        offset_tl: int,
        offset_tr: int,
        offset_bl: int,
        offset_br: int,
    ) -> "MetatileTable":
        """
        Unpack metatiles from four separate parallel arrays (TL, TR, BL, BR).
        Standard memory layout for 6502 and Z80 assembly game engines.
        """
        table = cls()
        for idx in range(count):
            e_tl = TilemapEntry(tile_index=data[offset_tl + idx])
            e_tr = TilemapEntry(tile_index=data[offset_tr + idx])
            e_bl = TilemapEntry(tile_index=data[offset_bl + idx])
            e_br = TilemapEntry(tile_index=data[offset_br + idx])
            table.add(Metatile16(index=idx, tl=e_tl, tr=e_tr, bl=e_bl, br=e_br))
        return table

    def pack_sequential_bytes(
        self,
        fmt: str = "nes",
        endian: str = "<",
    ) -> bytes:
        """
        Pack metatiles into sequential binary records sorted by index.
        """
        is_16bit = fmt.lower() in ("snes", "genesis", "md", "megadrive", "gba", "nds", "gbc")
        out = bytearray()
        sorted_metas = sorted(self.metatiles.values(), key=lambda m: m.index)

        for m in sorted_metas:
            if is_16bit:
                out.extend(struct.pack(f"{endian}H", m.tl.to_u16(fmt=fmt)))
                out.extend(struct.pack(f"{endian}H", m.tr.to_u16(fmt=fmt)))
                out.extend(struct.pack(f"{endian}H", m.bl.to_u16(fmt=fmt)))
                out.extend(struct.pack(f"{endian}H", m.br.to_u16(fmt=fmt)))
            else:
                out.append(m.tl.tile_index & 0xFF)
                out.append(m.tr.tile_index & 0xFF)
                out.append(m.bl.tile_index & 0xFF)
                out.append(m.br.tile_index & 0xFF)

        return bytes(out)

    def pack_planar_bytes(self) -> Tuple[bytes, bytes, bytes, bytes]:
        """
        Pack metatiles into four separate byte arrays (TL, TR, BL, BR).
        """
        sorted_metas = sorted(self.metatiles.values(), key=lambda m: m.index)
        tl_bytes = bytearray()
        tr_bytes = bytearray()
        bl_bytes = bytearray()
        br_bytes = bytearray()

        for m in sorted_metas:
            tl_bytes.append(m.tl.tile_index & 0xFF)
            tr_bytes.append(m.tr.tile_index & 0xFF)
            bl_bytes.append(m.bl.tile_index & 0xFF)
            br_bytes.append(m.br.tile_index & 0xFF)

        return bytes(tl_bytes), bytes(tr_bytes), bytes(bl_bytes), bytes(br_bytes)


class MetatileMap(MioRomResult):
    """
    A 2D level or screen map storing metatile IDs.
    """

    def __init__(
        self,
        width: int,
        height: int,
        map_data: Optional[List[int]] = None,
    ):
        self.width = width
        self.height = height
        total = width * height
        if map_data is not None:
            if len(map_data) != total:
                raise ValueError(
                    f"Map data length {len(map_data)} does not match {width}x{height} ({total})"
                )
            self.map_data = list(map_data)
        else:
            self.map_data = [0] * total

    def get_metatile(self, x: int, y: int) -> int:
        """Get metatile ID at coordinates."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            raise IndexError(f"Coordinates ({x}, {y}) out of range")
        return self.map_data[y * self.width + x]

    def set_metatile(self, x: int, y: int, meta_id: int) -> None:
        """Set metatile ID at coordinates."""
        if x < 0 or x >= self.width or y < 0 or y >= self.height:
            raise IndexError(f"Coordinates ({x}, {y}) out of range")
        self.map_data[y * self.width + x] = meta_id

    def to_tilemap(self, table: MetatileTable) -> Tilemap:
        """
        Expand the 2D metatile map into a full 8x8 Tilemap.
        The resulting tilemap dimensions will be (width * 2, height * 2).
        """
        out_w = self.width * 2
        out_h = self.height * 2
        tilemap = Tilemap(width=out_w, height=out_h)

        default_tile = TilemapEntry(tile_index=0)
        for my in range(self.height):
            for mx in range(self.width):
                meta_id = self.get_metatile(mx, my)
                metatile = table.get(meta_id)
                tl = metatile.tl if metatile else default_tile
                tr = metatile.tr if metatile else default_tile
                bl = metatile.bl if metatile else default_tile
                br = metatile.br if metatile else default_tile

                tx = mx * 2
                ty = my * 2
                tilemap.set_entry(tx, ty, tl)
                tilemap.set_entry(tx + 1, ty, tr)
                tilemap.set_entry(tx, ty + 1, bl)
                tilemap.set_entry(tx + 1, ty + 1, br)

        return tilemap

    @classmethod
    def from_tilemap(
        cls,
        tilemap: Tilemap,
        table: Optional[MetatileTable] = None,
        allow_new: bool = True,
    ) -> Tuple["MetatileMap", MetatileTable]:
        """
        Compress an 8x8 Tilemap into a 16x16 MetatileMap and MetatileTable.
        Synthesizes new metatiles for unique 2x2 tile patterns.
        """
        if tilemap.width % 2 != 0 or tilemap.height % 2 != 0:
            raise ValueError(
                f"Tilemap dimensions {tilemap.width}x{tilemap.height} must be even multiples of 2"
            )

        meta_w = tilemap.width // 2
        meta_h = tilemap.height // 2
        active_table = table or MetatileTable()

        # Build reverse lookup for existing metatiles
        pattern_lookup: Dict[Tuple[TilemapEntry, TilemapEntry, TilemapEntry, TilemapEntry], int] = {}
        for m in active_table:
            pattern_lookup[m.tiles] = m.index

        map_ids: List[int] = []
        for my in range(meta_h):
            for mx in range(meta_w):
                tx = mx * 2
                ty = my * 2
                tl = tilemap.get_entry(tx, ty)
                tr = tilemap.get_entry(tx + 1, ty)
                bl = tilemap.get_entry(tx, ty + 1)
                br = tilemap.get_entry(tx + 1, ty + 1)
                pattern = (tl, tr, bl, br)

                if pattern in pattern_lookup:
                    map_ids.append(pattern_lookup[pattern])
                else:
                    if not allow_new:
                        raise ValueError(f"Unknown metatile pattern at ({mx}, {my})")
                    new_idx = len(active_table)
                    new_meta = Metatile16(index=new_idx, tl=tl, tr=tr, bl=bl, br=br)
                    active_table.add(new_meta)
                    pattern_lookup[pattern] = new_idx
                    map_ids.append(new_idx)

        return cls(width=meta_w, height=meta_h, map_data=map_ids), active_table

    def to_bytes(self, bytes_per_entry: int = 1, endian: str = "<") -> bytes:
        """Serialize map data to binary bytes."""
        out = bytearray()
        for val in self.map_data:
            if bytes_per_entry == 1:
                out.append(val & 0xFF)
            elif bytes_per_entry == 2:
                out.extend(struct.pack(f"{endian}H", val & 0xFFFF))
            else:
                raise ValueError("bytes_per_entry must be 1 or 2")
        return bytes(out)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        width: int,
        height: int,
        bytes_per_entry: int = 1,
        endian: str = "<",
        offset: int = 0,
    ) -> "MetatileMap":
        """Deserialize map data from binary bytes."""
        count = width * height
        needed = offset + count * bytes_per_entry
        if len(data) < needed:
            raise ValueError(f"Insufficient data for {count} metatiles at offset {offset}")

        map_data: List[int] = []
        pos = offset
        for _ in range(count):
            if bytes_per_entry == 1:
                map_data.append(data[pos])
            elif bytes_per_entry == 2:
                map_data.append(struct.unpack_from(f"{endian}H", data, pos)[0])
            else:
                raise ValueError("bytes_per_entry must be 1 or 2")
            pos += bytes_per_entry

        return cls(width=width, height=height, map_data=map_data)
