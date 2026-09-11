"""
miorom.platforms.nds.nclr
~~~~~~~~~~~~~~~~~~~~~~~~~
Nitro Color Resource (NCLR) Parser and Builder.
Standard color palette container for Nintendo DS graphics assets.
Supports multi-section NCLR files (PLTT/TTLP and PCMP/PMCP palette mapping).
"""

from __future__ import annotations

from typing import Dict, List, Optional
from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.graphics.palette import Color, Palette


class NCLRHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"RLCN"
    byte_order = U16()   # 0xFEFF
    version = U16()      # 0x0100
    file_size = U32()
    header_size = U16()  # 0x0010
    section_count = U16()  # 1 or 2


class PLTTSectionStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"TTLP"
    size = U32()
    bpp_mode = U32()     # 3 = 4bpp, 4 = 8bpp
    _reserved = U32()
    data_size = U32()
    data_offset = U32()  # usually 0x10


class PCMPSectionStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"PMCP"
    size = U32()
    palette_count = U16()
    _reserved = U16()
    data_offset = U32()  # 0x00000008


class NCLRFile:
    """
    Nintendo DS NCLR (Nitro Color Resource) palette file.
    Contains BGR555 color palettes used for 2D sprites, backgrounds, and fonts.
    Supports PLTT color storage and PCMP hardware palette bank mapping.
    """

    MAGIC = b"RLCN"
    SECTION_MAGIC = b"TTLP"
    PCMP_MAGIC = b"PMCP"

    def __init__(
        self,
        colors: List[Color],
        bpp: int = 4,
        pmcp_indices: Optional[List[int]] = None,
    ):
        self.colors = list(colors)
        self.bpp = bpp
        self.pmcp_indices = list(pmcp_indices) if pmcp_indices is not None else None

    @property
    def indexed_palettes(self) -> Dict[int, List[Color]]:
        """
        Returns a dictionary mapping hardware palette bank indices (0..15)
        to their respective list of Color objects.
        """
        result: Dict[int, List[Color]] = {}
        if self.bpp == 8:
            result[0] = list(self.colors)
            return result

        # 4bpp palettes (16 colors per bank)
        if self.pmcp_indices:
            for i, bank_id in enumerate(self.pmcp_indices):
                start = i * 16
                end = start + 16
                if start < len(self.colors):
                    result[bank_id] = self.colors[start:end]
        else:
            bank_count = (len(self.colors) + 15) // 16
            for i in range(bank_count):
                start = i * 16
                end = min(start + 16, len(self.colors))
                result[i] = self.colors[start:end]

        return result

    @classmethod
    def from_bytes(cls, data: bytes) -> "NCLRFile":
        if len(data) < 0x20:
            raise ParseError("Data too small for NCLR header.")

        header = NCLRHeaderStruct.from_bytes(data, offset=0)
        if header.magic not in (cls.MAGIC, b"NCLR"):
            raise ParseError(f"Invalid NCLR magic: {header.magic!r}")

        offset = header.header_size
        pltt = PLTTSectionStruct.from_bytes(data, offset=offset)
        if pltt.magic not in (cls.SECTION_MAGIC, b"PLTT"):
            raise ParseError(f"Invalid PLTT section magic: {pltt.magic!r}")

        bpp = 4 if pltt.bpp_mode == 3 else 8
        color_data_start = offset + 8 + pltt.data_offset

        # Guard against VRAM allocation size overflow
        avail_bytes = pltt.size - (8 + pltt.data_offset)
        actual_data_size = min(pltt.data_size, avail_bytes) if avail_bytes > 0 else pltt.data_size
        color_count = actual_data_size // 2

        reader = BinaryReader(data, endian="<")
        reader.seek(color_data_start)
        colors: List[Color] = []
        for _ in range(color_count):
            if reader.tell() + 2 <= len(data):
                val = reader.read_u16()
                colors.append(Color.from_bgr555(val))

        pmcp_indices: Optional[List[int]] = None
        if header.section_count >= 2:
            sec2_offset = offset + pltt.size
            if sec2_offset + 16 <= len(data):
                sec2_magic = data[sec2_offset : sec2_offset + 4]
                if sec2_magic in (cls.PCMP_MAGIC, b"PCMP"):
                    pcmp = PCMPSectionStruct.from_bytes(data, offset=sec2_offset)
                    idx_pos = sec2_offset + 8 + pcmp.data_offset
                    reader.seek(idx_pos)
                    indices = []
                    for _ in range(pcmp.palette_count):
                        if reader.tell() + 2 <= len(data):
                            indices.append(reader.read_u16())
                    pmcp_indices = indices

        return cls(colors=colors, bpp=bpp, pmcp_indices=pmcp_indices)

    @classmethod
    def from_palette(
        cls,
        pal: Palette,
        bpp: int = 4,
        pmcp_indices: Optional[List[int]] = None,
    ) -> "NCLRFile":
        return cls(colors=pal.colors, bpp=bpp, pmcp_indices=pmcp_indices)

    def to_palette(self, expand_pmcp: bool = True) -> Palette:
        """
        Converts the NCLR colors into a Palette object.
        If PMCP palette mapping is active and expand_pmcp is True, maps each
        16-color bank to its hardware VRAM slot (bank_id * 16).
        """
        if expand_pmcp and self.pmcp_indices and self.bpp == 4:
            max_bank = max(self.pmcp_indices) if self.pmcp_indices else 0
            total_size = max(256, (max_bank + 1) * 16)
            expanded = [Color(0, 0, 0, 0)] * total_size
            for i, bank_id in enumerate(self.pmcp_indices):
                start = i * 16
                chunk = self.colors[start : start + 16]
                dest_base = bank_id * 16
                for j, c in enumerate(chunk):
                    if dest_base + j < total_size:
                        expanded[dest_base + j] = c

            # Fallback: alias bank 0 to first colors if empty
            if not any(c.a != 0 for c in expanded[:16]) and self.colors:
                for j, c in enumerate(self.colors[:16]):
                    expanded[j] = c

            return Palette(colors=expanded)

        return Palette(colors=self.colors)

    def to_bytes(self) -> bytes:
        writer = BinaryWriter(endian="<")
        for c in self.colors:
            writer.write_u16(c.to_bgr555())

        color_bytes = writer.to_bytes()
        data_size = len(color_bytes)
        data_offset = 0x10
        pltt_size = 8 + data_offset + data_size
        bpp_mode = 3 if self.bpp == 4 else 4

        header_size = 0x10
        has_pmcp = bool(self.pmcp_indices)
        section_count = 2 if has_pmcp else 1

        pmcp_size = 0
        if has_pmcp:
            pmcp_count = len(self.pmcp_indices)
            pmcp_size = 16 + (pmcp_count * 2)
            # 4-byte alignment padding
            if pmcp_size % 4 != 0:
                pmcp_size += 4 - (pmcp_size % 4)

        file_size = header_size + pltt_size + pmcp_size

        out = BinaryWriter(endian="<")
        # NCLR File Header
        out.write_bytes(self.MAGIC)
        out.write_u16(0xFEFF)
        out.write_u16(0x0100)
        out.write_u32(file_size)
        out.write_u16(header_size)
        out.write_u16(section_count)

        # PLTT Section Header
        out.write_bytes(self.SECTION_MAGIC)
        out.write_u32(pltt_size)
        out.write_u32(bpp_mode)
        out.write_u32(0)  # reserved
        out.write_u32(data_size)
        out.write_u32(data_offset)

        # Color data
        out.write_bytes(color_bytes)

        # PMCP Section (if present)
        if has_pmcp:
            pmcp_count = len(self.pmcp_indices)
            out.write_bytes(self.PCMP_MAGIC)
            out.write_u32(pmcp_size)
            out.write_u16(pmcp_count)
            out.write_u16(0xBEEF)  # standard Nitro PMCP flag / reserved
            out.write_u32(0x00000008)  # data offset to index array
            for idx in self.pmcp_indices:
                out.write_u16(idx)
            # Align
            current_len = out.tell()
            if current_len % 4 != 0:
                out.write_bytes(b"\x00" * (4 - (current_len % 4)))

        return out.to_bytes()
