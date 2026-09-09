from miorom.result import MioRomResult
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple

from miorom.asm.codecave import CodeCave, CodeCaveFinder


@dataclass
class DolSection(MioRomResult):
    index: int
    is_text: bool
    file_offset: int
    ram_address: int
    size: int

    @property
    def end_ram(self) -> int:
        return self.ram_address + self.size

    @property
    def end_offset(self) -> int:
        return self.file_offset + self.size


class DolBinary:
    """
    Parser and modifier for Nintendo GameCube and Wii DOL executables (.dol).
    Supports:
    - Parsing header with 7 text and 11 data sections.
    - Bidirectional RAM address <-> File offset resolution.
    - Adding new text/data sections (for expanding code space).
    - Scanning existing sections for code caves.
    """

    HEADER_SIZE = 0x100  # 256 bytes

    def __init__(self, data: bytearray):
        self.data = data
        self.text_sections: List[DolSection] = []
        self.data_sections: List[DolSection] = []
        self.bss_address: int = 0
        self.bss_size: int = 0
        self.entry_point: int = 0
        self._parse_header()

    @classmethod
    def is_dol(cls, data: bytes) -> bool:
        """
        Check if data has a valid DOL executable header.
        """
        if len(data) < cls.HEADER_SIZE:
            return False

        # Check first text offset - typically 0x100 in valid DOLs
        first_text_offset = struct.unpack_from(">I", data, 0)[0]
        first_text_address = struct.unpack_from(">I", data, 0x48)[0]

        # Valid GC/Wii RAM addresses are in 0x80000000..0x81800000 or 0x90000000..0x94000000
        is_ram_valid = (
            (0x80000000 <= first_text_address <= 0x81800000)
            or (0x90000000 <= first_text_address <= 0x94000000)
        )
        return first_text_offset == 0x100 and is_ram_valid

    def _parse_header(self):
        text_offsets = struct.unpack_from(">7I", self.data, 0x00)
        data_offsets = struct.unpack_from(">11I", self.data, 0x1C)
        text_addrs = struct.unpack_from(">7I", self.data, 0x48)
        data_addrs = struct.unpack_from(">11I", self.data, 0x64)
        text_sizes = struct.unpack_from(">7I", self.data, 0x90)
        data_sizes = struct.unpack_from(">11I", self.data, 0xAC)

        self.bss_address, self.bss_size, self.entry_point = struct.unpack_from(
            ">III", self.data, 0xD8
        )

        self.text_sections.clear()
        for i in range(7):
            if text_offsets[i] != 0 and text_sizes[i] != 0:
                self.text_sections.append(
                    DolSection(
                        index=i,
                        is_text=True,
                        file_offset=text_offsets[i],
                        ram_address=text_addrs[i],
                        size=text_sizes[i],
                    )
                )

        self.data_sections.clear()
        for i in range(11):
            if data_offsets[i] != 0 and data_sizes[i] != 0:
                self.data_sections.append(
                    DolSection(
                        index=i,
                        is_text=False,
                        file_offset=data_offsets[i],
                        ram_address=data_addrs[i],
                        size=data_sizes[i],
                    )
                )

    def ram_to_offset(self, ram_addr: int) -> Optional[int]:
        """
        Convert a GameCube/Wii RAM address to its corresponding file offset in the DOL.
        """
        for sec in self.text_sections + self.data_sections:
            if sec.ram_address <= ram_addr < sec.end_ram:
                return sec.file_offset + (ram_addr - sec.ram_address)
        return None

    def offset_to_ram(self, file_offset: int) -> Optional[int]:
        """
        Convert a DOL file offset to its corresponding GameCube/Wii RAM address.
        """
        for sec in self.text_sections + self.data_sections:
            if sec.file_offset <= file_offset < sec.end_offset:
                return sec.ram_address + (file_offset - sec.file_offset)
        return None

    def find_free_section_slot(self, is_text: bool = True) -> Optional[int]:
        """
        Find an unused section slot index (0..6 for text, 0..10 for data).
        """
        used_indices = {s.index for s in (self.text_sections if is_text else self.data_sections)}
        max_slots = 7 if is_text else 11
        for idx in range(max_slots):
            if idx not in used_indices:
                return idx
        return None

    def add_section(
        self,
        payload: bytes,
        ram_address: int,
        is_text: bool = True,
        alignment: int = 32,
    ) -> DolSection:
        """
        Appends a new section containing payload to the DOL, updates the header,
        and returns the created DolSection.
        """
        slot = self.find_free_section_slot(is_text=is_text)
        if slot is None:
            raise RuntimeError(
                f"No free {'text' if is_text else 'data'} section slots in DOL header."
            )

        # Align end of current DOL file
        current_len = len(self.data)
        rem = current_len % alignment
        if rem != 0:
            pad = alignment - rem
            self.data.extend(b"\x00" * pad)
            current_len += pad

        file_offset = current_len
        self.data.extend(payload)
        size = len(payload)

        # Align section payload to 32 bytes
        rem = size % alignment
        if rem != 0:
            pad = alignment - rem
            self.data.extend(b"\x00" * pad)
            size += pad

        # Update header
        if is_text:
            struct.pack_into(">I", self.data, 0x00 + slot * 4, file_offset)
            struct.pack_into(">I", self.data, 0x48 + slot * 4, ram_address)
            struct.pack_into(">I", self.data, 0x90 + slot * 4, size)
        else:
            struct.pack_into(">I", self.data, 0x1C + slot * 4, file_offset)
            struct.pack_into(">I", self.data, 0x64 + slot * 4, ram_address)
            struct.pack_into(">I", self.data, 0xAC + slot * 4, size)

        new_sec = DolSection(
            index=slot,
            is_text=is_text,
            file_offset=file_offset,
            ram_address=ram_address,
            size=size,
        )
        if is_text:
            self.text_sections.append(new_sec)
        else:
            self.data_sections.append(new_sec)

        return new_sec

    def find_caves(
        self,
        min_size: int = 16,
        filler_byte: int = 0x00,
        alignment: int = 4,
    ) -> List[Tuple[DolSection, CodeCave]]:
        """
        Scan all text sections in the DOL for code caves.
        Returns a list of tuples (DolSection, CodeCave).
        """
        results: List[Tuple[DolSection, CodeCave]] = []
        for sec in self.text_sections:
            sec_bytes = bytes(self.data[sec.file_offset : sec.end_offset])
            caves = CodeCaveFinder.find_caves(
                sec_bytes, min_size=min_size, filler_byte=filler_byte, alignment=alignment
            )
            for c in caves:
                cave_abs = CodeCave(
                    offset=sec.file_offset + c.offset,
                    size=c.size,
                    filler_byte=c.filler_byte,
                )
                results.append((sec, cave_abs))
        return results
