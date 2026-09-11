"""
miorom.platforms.nds.ncgr
~~~~~~~~~~~~~~~~~~~~~~~~~
Nitro Character Graphic Resource (NCGR) Parser and Builder.
Standard tile/character graphics container for Nintendo DS games.
"""

from __future__ import annotations

from miorom.core.binary import BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.graphics.tiles import Tile, decode_tile, encode_tile


class NCGRHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"RGCN"
    byte_order = U16()   # 0xFEFF
    version = U16()      # 0x0100
    file_size = U32()
    header_size = U16()  # 0x0010
    section_count = U16()  # 1


class CHARSectionStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"RAHC"
    size = U32()
    tile_height = U16()  # in tiles, or 0xFFFF for 1D
    tile_width = U16()   # in tiles, or 0xFFFF for 1D
    bpp_mode = U32()     # 3 = 4bpp, 4 = 8bpp
    _reserved = U32()
    mapping_mode = U32() # 0 = 2D, 1 = 1D
    data_size = U32()
    data_offset = U32()  # 0x18


class NCGRFile:
    """
    Nintendo DS NCGR (Nitro Character Graphic Resource) tile archive.
    Stores 8x8 character tiles in 4bpp or 8bpp chunky format.
    """

    MAGIC = b"RGCN"
    SECTION_MAGIC = b"RAHC"

    def __init__(
        self,
        tiles: List[Tile],
        bpp: int = 4,
        width_tiles: int = 0xFFFF,
        height_tiles: int = 0xFFFF,
        is_1d: bool = True,
    ):
        self.tiles = list(tiles)
        self.bpp = bpp
        self.width_tiles = width_tiles
        self.height_tiles = height_tiles
        self.is_1d = is_1d

    @property
    def tile_count(self) -> int:
        return len(self.tiles)

    @classmethod
    def from_bytes(cls, data: bytes) -> "NCGRFile":
        if len(data) < 0x20:
            raise ParseError("Data too small for NCGR header.")

        header = NCGRHeaderStruct.from_bytes(data, offset=0)
        if header.magic not in (cls.MAGIC, b"NCGR"):
            raise ParseError(f"Invalid NCGR magic: {header.magic!r}")

        offset = header.header_size
        char = CHARSectionStruct.from_bytes(data, offset=offset)
        if char.magic not in (cls.SECTION_MAGIC, b"CHAR"):
            raise ParseError(f"Invalid CHAR section magic: {char.magic!r}")

        bpp = 4 if char.bpp_mode == 3 else 8
        tile_bytes = 32 if bpp == 4 else 64
        tile_data_start = offset + 8 + char.data_offset

        tiles: List[Tile] = []
        count = char.data_size // tile_bytes

        for i in range(count):
            t_offset = tile_data_start + (i * tile_bytes)
            if t_offset + tile_bytes <= len(data):
                tile = decode_tile(data[t_offset : t_offset + tile_bytes], bpp=bpp, planar=False)
                tiles.append(tile)

        return cls(
            tiles=tiles,
            bpp=bpp,
            width_tiles=char.tile_width,
            height_tiles=char.tile_height,
            is_1d=bool(char.mapping_mode & 1),
        )

    def to_bytes(self) -> bytes:
        raw_tiles = bytearray()
        for t in self.tiles:
            raw_tiles.extend(encode_tile(t, bpp=self.bpp, planar=False))

        data_size = len(raw_tiles)
        data_offset = 0x18
        char_size = 8 + data_offset + data_size
        bpp_mode = 3 if self.bpp == 4 else 4
        mapping = 1 if self.is_1d else 0

        header_size = 0x10
        file_size = header_size + char_size

        out = BinaryWriter(endian="<")
        # NCGR Header
        out.write_bytes(self.MAGIC)
        out.write_u16(0xFEFF)
        out.write_u16(0x0100)
        out.write_u32(file_size)
        out.write_u16(header_size)
        out.write_u16(1)

        # CHAR Section Header
        out.write_bytes(self.SECTION_MAGIC)
        out.write_u32(char_size)
        out.write_u16(self.height_tiles)
        out.write_u16(self.width_tiles)
        out.write_u32(bpp_mode)
        out.write_u32(0)  # reserved
        out.write_u32(mapping)
        out.write_u32(data_size)
        out.write_u32(data_offset)

        # Tile Data
        out.write_bytes(raw_tiles)
        return out.to_bytes()
