"""
miorom.platforms.nds.nscr
~~~~~~~~~~~~~~~~~~~~~~~~~
Nitro Screen Resource (NSCR) Parser and Builder.
Standard background / tilemap container for Nintendo DS games.
Supports Text BG and multi-page sub-screen base block (SBB) coordinate mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile


@dataclass
class ScreenEntry:
    tile_index: int
    flip_x: bool = False
    flip_y: bool = False
    palette_index: int = 0

    def to_u16(self) -> int:
        val = self.tile_index & 0x03FF
        if self.flip_x:
            val |= 1 << 10
        if self.flip_y:
            val |= 1 << 11
        val |= (self.palette_index & 0x0F) << 12
        return val

    @classmethod
    def from_u16(cls, val: int) -> "ScreenEntry":
        return cls(
            tile_index=val & 0x03FF,
            flip_x=bool(val & (1 << 10)),
            flip_y=bool(val & (1 << 11)),
            palette_index=(val >> 12) & 0x0F,
        )


class NSCRHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"RCSN"
    byte_order = U16()   # 0xFEFF
    version = U16()      # 0x0100
    file_size = U32()
    header_size = U16()  # 0x0010
    section_count = U16()  # 1


class SCRNSectionStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"NRCS"
    size = U32()
    screen_width = U16()   # width in pixels (e.g. 256)
    screen_height = U16()  # height in pixels (e.g. 192)
    bg_type = U16()        # background type (0 = text)
    _reserved = U16()
    data_size = U32()


class NSCRFile:
    """
    Nintendo DS NSCR (Nitro Screen Resource) tilemap layout.
    Represents background layer tile mappings, palette assignments, and flips.
    """

    MAGIC = b"RCSN"
    SECTION_MAGIC = b"NRCS"

    def __init__(
        self,
        entries: List[ScreenEntry],
        width_pixels: int = 256,
        height_pixels: int = 192,
        bg_type: int = 0,
    ):
        self.entries = list(entries)
        self.width_pixels = width_pixels
        self.height_pixels = height_pixels
        self.bg_type = bg_type

    @property
    def width_tiles(self) -> int:
        return self.width_pixels // 8

    @property
    def height_tiles(self) -> int:
        return self.height_pixels // 8

    @property
    def actual_height_tiles(self) -> int:
        """Computes real height in tiles based on actual available entries."""
        cols = self.width_tiles if self.width_tiles > 0 else 32
        calculated = (len(self.entries) + cols - 1) // cols
        return min(self.height_tiles, calculated) if calculated > 0 else self.height_tiles

    @property
    def actual_height_pixels(self) -> int:
        return self.actual_height_tiles * 8

    def get_entry(self, tile_x: int, tile_y: int, paged: bool = True) -> Optional[ScreenEntry]:
        """
        Retrieves the ScreenEntry for logical tile coordinate (tile_x, tile_y).
        If paged is True and screen is larger than 32 tiles, accounts for
        hardware Screen Base Block (SBB 32x32) paging.
        """
        cols = self.width_tiles
        if paged and cols > 32:
            sbb_cols = cols // 32
            sbb_x = tile_x // 32
            sbb_y = tile_y // 32
            sub_x = tile_x % 32
            sub_y = tile_y % 32
            sbb_idx = sbb_y * sbb_cols + sbb_x
            entry_idx = sbb_idx * 1024 + sub_y * 32 + sub_x
        else:
            entry_idx = tile_y * cols + tile_x

        if 0 <= entry_idx < len(self.entries):
            return self.entries[entry_idx]
        return None

    @classmethod
    def from_bytes(cls, data: bytes) -> "NSCRFile":
        if len(data) < 0x20:
            raise ParseError("Data too small for NSCR header.")

        header = NSCRHeaderStruct.from_bytes(data, offset=0)
        if header.magic not in (cls.MAGIC, b"NSCR"):
            raise ParseError(f"Invalid NSCR magic: {header.magic!r}")

        offset = header.header_size
        scrn = SCRNSectionStruct.from_bytes(data, offset=offset)
        if scrn.magic not in (cls.SECTION_MAGIC, b"SCRN"):
            raise ParseError(f"Invalid SCRN section magic: {scrn.magic!r}")

        entry_data_start = offset + 20
        count = scrn.data_size // 2

        reader = BinaryReader(data, endian="<")
        reader.seek(entry_data_start)
        entries: List[ScreenEntry] = []
        for _ in range(count):
            if reader.tell() + 2 <= len(data):
                val = reader.read_u16()
                entries.append(ScreenEntry.from_u16(val))

        return cls(
            entries=entries,
            width_pixels=scrn.screen_width,
            height_pixels=scrn.screen_height,
            bg_type=scrn.bg_type,
        )

    def to_bytes(self) -> bytes:
        writer = BinaryWriter(endian="<")
        for e in self.entries:
            writer.write_u16(e.to_u16())

        raw_entries = writer.to_bytes()
        data_size = len(raw_entries)
        scrn_size = 20 + data_size
        header_size = 0x10
        file_size = header_size + scrn_size

        out = BinaryWriter(endian="<")
        # NSCR File Header
        out.write_bytes(self.MAGIC)
        out.write_u16(0xFEFF)
        out.write_u16(0x0100)
        out.write_u32(file_size)
        out.write_u16(header_size)
        out.write_u16(1)

        # SCRN Section Header
        out.write_bytes(self.SECTION_MAGIC)
        out.write_u32(scrn_size)
        out.write_u16(self.width_pixels)
        out.write_u16(self.height_pixels)
        out.write_u16(self.bg_type)
        out.write_u16(0)
        out.write_u32(data_size)

        # Screen Entry Data
        out.write_bytes(raw_entries)
        return out.to_bytes()
