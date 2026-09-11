"""
miorom.platforms.nds.ncer
~~~~~~~~~~~~~~~~~~~~~~~~~
Nitro Character Resource (NCER) Parser, Builder, and Cell Assembler.
Standard 2D sprite cell and animation bank container for Nintendo DS games.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.graphics.palette import Color, Palette
from miorom.platforms.nds.ncgr import NCGRFile

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


def get_ncer_cell_size(shape: int, size: int) -> Tuple[int, int]:
    """
    Computes (width, height) in pixels from NDS OAM shape and size attributes.
    Shape: 0 = Square, 1 = Wide, 2 = Tall.
    Size: 0 to 3.
    """
    if shape == 0:
        sizes = {0: (8, 8), 1: (16, 16), 2: (32, 32), 3: (64, 64)}
    elif shape == 1:
        sizes = {0: (16, 8), 1: (32, 8), 2: (32, 16), 3: (64, 32)}
    elif shape == 2:
        sizes = {0: (8, 16), 1: (8, 32), 2: (16, 32), 3: (32, 64)}
    else:
        sizes = {}
    return sizes.get(size, (8, 8))


@dataclass
class NCERCell:
    """Individual OAM cell component inside a cell bank."""
    x: int = 0
    y: int = 0
    width: int = 8
    height: int = 8
    shape: int = 0
    size: int = 0
    tile_offset: int = 0
    palette_index: int = 0
    flip_x: bool = False
    flip_y: bool = False
    priority: int = 0
    mosaic: bool = False
    obj_mode: int = 0
    rs_flag: bool = False
    num_cell: int = 0
    raw_obj0: int = 0
    raw_obj1: int = 0
    raw_obj2: int = 0


@dataclass
class NCERBank:
    """A collection of OAM cells forming an assembled frame or sprite state."""
    cells: List[NCERCell] = field(default_factory=list)
    width: int = 0
    height: int = 0
    x_min: int = 0
    y_min: int = 0
    x_max: int = 0
    y_max: int = 0
    cell_info: int = 0
    cell_offset: int = 0
    partition_offset: int = 0
    partition_size: int = 0


class NCERHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"RECN"
    byte_order = U16()   # 0xFEFF
    version = U16()      # 0x0100
    file_size = U32()
    header_size = U16()  # 0x0010
    section_count = U16()  # 1


class CEBKSectionStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"KBEC"
    size = U32()
    bank_count = U16()
    cell_type = U16()    # 0 = standard, 1 = with bounding box
    bank_data_offset = U32()
    block_size = U32()
    partition_offset = U32()


class NCERFile:
    """
    Nintendo DS NCER (Nitro Character Resource) cell bank archive.
    Assembles individual 8x8 character tiles into complete 2D sprites and UI widgets.
    """

    MAGIC = b"RECN"
    SECTION_MAGIC = b"KBEC"

    def __init__(
        self,
        banks: List[NCERBank],
        cell_type: int = 1,
        block_size: int = 0,
    ):
        self.banks = list(banks)
        self.cell_type = cell_type
        self.block_size = block_size

    @property
    def bank_count(self) -> int:
        return len(self.banks)

    @classmethod
    def from_bytes(cls, data: bytes) -> "NCERFile":
        if len(data) < 0x20:
            raise ParseError("Data too small for NCER header.")

        header = NCERHeaderStruct.from_bytes(data, offset=0)
        if header.magic not in (cls.MAGIC, b"NCER"):
            raise ParseError(f"Invalid NCER magic: {header.magic!r}")

        offset = header.header_size
        cebk = CEBKSectionStruct.from_bytes(data, offset=offset)
        if cebk.magic not in (cls.SECTION_MAGIC, b"CEBK"):
            raise ParseError(f"Invalid CEBK section magic: {cebk.magic!r}")

        banks: List[NCERBank] = [NCERBank() for _ in range(cebk.bank_count)]

        # Read partition offsets if present
        if cebk.partition_offset > 0:
            part_pos = offset + 8 + cebk.partition_offset
            if part_pos + 8 <= len(data):
                reader_part = BinaryReader(data, endian="<")
                reader_part.seek(part_pos)
                _max_part_size = reader_part.read_u32()
                first_part_offset = reader_part.read_u32()
                reader_part.seek(part_pos + first_part_offset)
                for b in banks:
                    if reader_part.tell() + 8 <= len(data):
                        b.partition_offset = reader_part.read_u32()
                        b.partition_size = reader_part.read_u32()

        # Read banks and cells
        bank_base = offset + 8 + cebk.bank_data_offset
        reader = BinaryReader(data, endian="<")
        reader.seek(bank_base)

        for i, bank in enumerate(banks):
            if reader.tell() + 8 > len(data):
                break
            cell_num = reader.read_u16()
            cell_info = reader.read_u16()
            cell_offset = reader.read_u32()
            bank.cell_info = cell_info
            bank.cell_offset = cell_offset

            if cebk.cell_type == 1:
                if reader.tell() + 8 <= len(data):
                    bank.x_max = reader.read_s16()
                    bank.y_max = reader.read_s16()
                    bank.x_min = reader.read_s16()
                    bank.y_min = reader.read_s16()
                    bank.width = bank.x_max - bank.x_min + 1
                    bank.height = bank.y_max - bank.y_min + 1

            saved_pos = reader.tell()
            stride = 8 if cebk.cell_type == 0 else 16
            obj_offset = saved_pos + (cebk.bank_count - (i + 1)) * stride + cell_offset

            if obj_offset + cell_num * 6 <= len(data):
                cell_reader = BinaryReader(data, endian="<")
                cell_reader.seek(obj_offset)
                cells: List[NCERCell] = []
                for j in range(cell_num):
                    o0 = cell_reader.read_u16()
                    o1 = cell_reader.read_u16()
                    o2 = cell_reader.read_u16()

                    y = o0 & 0xFF
                    if y >= 128:
                        y -= 256

                    x = o1 & 0x1FF
                    if x >= 0x100:
                        x -= 0x200

                    shape = (o0 >> 14) & 3
                    size = (o1 >> 14) & 3
                    tile_offset = o2 & 0x3FF
                    pal_idx = (o2 >> 12) & 0xF
                    rs_flag = bool((o0 >> 8) & 1)
                    x_flip = bool((o1 >> 12) & 1) if not rs_flag else False
                    y_flip = bool((o1 >> 13) & 1) if not rs_flag else False
                    priority = (o2 >> 10) & 3

                    w, h = get_ncer_cell_size(shape, size)
                    cell = NCERCell(
                        x=x,
                        y=y,
                        width=w,
                        height=h,
                        shape=shape,
                        size=size,
                        tile_offset=tile_offset,
                        palette_index=pal_idx,
                        flip_x=x_flip,
                        flip_y=y_flip,
                        priority=priority,
                        mosaic=bool((o0 >> 12) & 1),
                        obj_mode=(o0 >> 10) & 3,
                        rs_flag=rs_flag,
                        num_cell=j,
                        raw_obj0=o0,
                        raw_obj1=o1,
                        raw_obj2=o2,
                    )
                    cells.append(cell)

                bank.cells = cells

                # Compute bounding box if unset
                if bank.width <= 0 or bank.height <= 0:
                    if cells:
                        min_x = min(c.x for c in cells)
                        min_y = min(c.y for c in cells)
                        max_x = max(c.x + c.width for c in cells)
                        max_y = max(c.y + c.height for c in cells)
                        bank.width = max_x - min_x
                        bank.height = max_y - min_y
                        bank.x_min, bank.y_min = min_x, min_y
                        bank.x_max, bank.y_max = max_x, max_y

            reader.seek(saved_pos)

        return cls(banks=banks, cell_type=cebk.cell_type, block_size=cebk.block_size)

    def render_bank(
        self,
        bank_index: int,
        ncgr: NCGRFile,
        palette_or_nclr: Union[Palette, List[Color], "NCLRFile"],
        transparency: bool = True,
    ) -> Optional["Image.Image"]:
        """
        Assembles and renders a specific cell bank frame into a PIL RGBA Image.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for NCER rendering. Install with 'pip install Pillow'.")

        if bank_index < 0 or bank_index >= len(self.banks):
            return None

        bank = self.banks[bank_index]
        if not bank.cells or bank.width <= 0 or bank.height <= 0:
            return None

        # Resolve palette
        if hasattr(palette_or_nclr, "to_palette"):
            pal = palette_or_nclr.to_palette()
        elif isinstance(palette_or_nclr, Palette):
            pal = palette_or_nclr
        else:
            pal = Palette(colors=palette_or_nclr)

        img = Image.new("RGBA", (bank.width, bank.height), (0, 0, 0, 0))
        pixels = img.load()

        shift = self.block_size & 0xFF
        bpp_shift = 8 * ncgr.bpp
        min_x = bank.x_min
        min_y = bank.y_min

        sorted_cells = sorted(bank.cells, key=lambda c: (c.priority, c.num_cell), reverse=True)

        for cell in sorted_cells:
            tile_start = (bank.partition_offset // bpp_shift) + ((cell.tile_offset << shift) * 0x20 // bpp_shift)
            cols = cell.width // 8
            rows = cell.height // 8
            pal_base = cell.palette_index * 16 if ncgr.bpp == 4 else 0
            if pal_base >= len(pal):
                pal_base = 0

            cx = cell.x - min_x
            cy = cell.y - min_y

            for r in range(rows):
                for c in range(cols):
                    t_idx = tile_start + (r * cols + c)
                    if t_idx >= len(ncgr.tiles):
                        continue
                    tile = ncgr.tiles[t_idx]

                    sub_x = (cols - 1 - c if cell.flip_x else c) * 8
                    sub_y = (rows - 1 - r if cell.flip_y else r) * 8

                    for y in range(8):
                        py = 7 - y if cell.flip_y else y
                        for x in range(8):
                            px = 7 - x if cell.flip_x else x
                            c_idx = tile.get_pixel(px, py)
                            if transparency and c_idx == 0:
                                continue
                            full_pal_idx = pal_base + c_idx
                            if full_pal_idx < len(pal):
                                col = pal[full_pal_idx]
                                target_x = cx + sub_x + x
                                target_y = cy + sub_y + y
                                if 0 <= target_x < bank.width and 0 <= target_y < bank.height:
                                    pixels[target_x, target_y] = (col.r, col.g, col.b, 255)

        return img

    def render_all_banks_stacked(
        self,
        ncgr: NCGRFile,
        palette_or_nclr: Union[Palette, List[Color], "NCLRFile"],
        transparency: bool = True,
        padding: int = 4,
    ) -> Optional["Image.Image"]:
        """
        Renders all cell bank frames stacked vertically into a single sprite animation atlas image.
        Deduplicates identical animation frames and ignores empty banks.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for NCER rendering.")

        rendered_banks: List["Image.Image"] = []
        seen_hashes = set()
        for i in range(len(self.banks)):
            bank = self.banks[i]
            if not bank.cells or bank.width <= 0 or bank.height <= 0:
                continue
            b_img = self.render_bank(i, ncgr, palette_or_nclr, transparency=transparency)
            if b_img:
                b_hash = b_img.tobytes()
                if b_hash in seen_hashes:
                    continue
                seen_hashes.add(b_hash)
                rendered_banks.append(b_img)

        if not rendered_banks:
            return None

        total_width = max(b.width for b in rendered_banks)
        total_height = sum(b.height for b in rendered_banks) + padding * (len(rendered_banks) - 1)

        combined = Image.new("RGBA", (total_width, total_height), (0, 0, 0, 0))
        curr_y = 0
        for b in rendered_banks:
            combined.paste(b, (0, curr_y), b)
            curr_y += b.height + padding

        return combined

    def to_bytes(self) -> bytes:
        """
        Serializes NCERFile back into Nintendo DS Nitro Character Resource binary format.
        """
        bank_count = len(self.banks)
        bank_data_offset = 0x18
        cell_type = self.cell_type

        bank_entries_bytes = bytearray()
        cells_bytes = bytearray()

        for bank in self.banks:
            cell_offset = len(cells_bytes)
            cell_num = len(bank.cells)
            cell_info = bank.cell_info

            bank_entries_bytes.extend(struct.pack("<HHI", cell_num, cell_info, cell_offset))
            if cell_type == 1:
                bank_entries_bytes.extend(
                    struct.pack("<hhhh", bank.x_max, bank.y_max, bank.x_min, bank.y_min)
                )

            for cell in bank.cells:
                if cell.raw_obj0 or cell.raw_obj1 or cell.raw_obj2:
                    o0 = cell.raw_obj0
                    o1 = cell.raw_obj1
                    o2 = cell.raw_obj2
                else:
                    y = cell.y & 0xFF
                    shape = (cell.shape & 3) << 14
                    rs = (1 if cell.rs_flag else 0) << 8
                    obj_mode = (cell.obj_mode & 3) << 10
                    mosaic = (1 if cell.mosaic else 0) << 12
                    o0 = y | rs | obj_mode | mosaic | shape

                    x = cell.x & 0x1FF
                    fx = (1 if cell.flip_x else 0) << 12
                    fy = (1 if cell.flip_y else 0) << 13
                    sz = (cell.size & 3) << 14
                    o1 = x | fx | fy | sz

                    tile = cell.tile_offset & 0x3FF
                    pri = (cell.priority & 3) << 10
                    pal = (cell.palette_index & 0xF) << 12
                    o2 = tile | pri | pal

                cells_bytes.extend(struct.pack("<HHH", o0, o1, o2))

        cebk_payload = bytearray()
        cebk_payload.extend(
            struct.pack(
                "<HHIIII",
                bank_count,
                cell_type,
                bank_data_offset,
                self.block_size,
                0,  # partition_offset
                0,  # reserved
            )
        )
        cebk_payload.extend(b"\x00\x00\x00\x00")
        cebk_payload.extend(bank_entries_bytes)
        cebk_payload.extend(cells_bytes)

        pad = (4 - (len(cebk_payload) % 4)) % 4
        if pad:
            cebk_payload.extend(b"\x00" * pad)

        cebk_size = 8 + len(cebk_payload)
        header_size = 0x10
        file_size = header_size + cebk_size

        out = BinaryWriter(endian="<")
        out.write_bytes(self.MAGIC)
        out.write_u16(0xFEFF)
        out.write_u16(0x0100)
        out.write_u32(file_size)
        out.write_u16(header_size)
        out.write_u16(1)

        out.write_bytes(self.SECTION_MAGIC)
        out.write_u32(cebk_size)
        out.write_bytes(cebk_payload)

        return out.to_bytes()
