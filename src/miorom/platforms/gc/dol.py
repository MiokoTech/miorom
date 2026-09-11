"""
miorom.platforms.gc.dol
~~~~~~~~~~~~~~~~~~~~~~~
GameCube and Wii Executable (DOL) Parser, Serializer, and Section Injector.
Provides bidirectional address translation (RAM address <-> DOL file offset),
memory reading/writing, and section creation for ASM code caves and translation hooks.
"""

import os
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class DolSection(MioRomResult):
    """Represents an individual text or data section within a DOL binary."""
    section_type: str
    index: int
    offset: int
    address: int
    size: int
    data: bytearray

    @property
    def is_text(self) -> bool:
        return self.section_type == "text"

    @property
    def is_data(self) -> bool:
        return self.section_type == "data"

    @property
    def end_address(self) -> int:
        return self.address + self.size

    @property
    def end_offset(self) -> int:
        return self.offset + self.size

    def contains_address(self, addr: int) -> bool:
        return self.address <= addr < (self.address + self.size)

    def contains_offset(self, off: int) -> bool:
        return self.offset <= off < (self.offset + self.size)


class DolFile(MioRomResult):
    """
    GameCube and Wii DOL executable container.

    Manages up to 7 text sections and 11 data sections with full header parsing,
    address-to-offset mapping, memory modification, and dynamic section injection.
    """

    NUM_TEXT_SECTIONS = 7
    NUM_DATA_SECTIONS = 11
    HEADER_SIZE = 0x100

    def __init__(
        self,
        text_sections: Optional[List[DolSection]] = None,
        data_sections: Optional[List[DolSection]] = None,
        bss_address: int = 0,
        bss_size: int = 0,
        entry_point: int = 0x80003100,
    ):
        self.text_sections: List[DolSection] = text_sections or []
        self.data_sections: List[DolSection] = data_sections or []
        self.bss_address: int = bss_address
        self.bss_size: int = bss_size
        self.entry_point: int = entry_point

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray]) -> "DolFile":
        """Parse a DOL executable file from a binary buffer."""
        if len(data) < cls.HEADER_SIZE:
            raise ValueError(f"DOL data too short ({len(data)} bytes, minimum {cls.HEADER_SIZE} bytes)")

        header = memoryview(data)[:cls.HEADER_SIZE]

        text_offsets = [struct.unpack_from(">I", header, i * 4)[0] for i in range(cls.NUM_TEXT_SECTIONS)]
        data_offsets = [struct.unpack_from(">I", header, 0x1C + i * 4)[0] for i in range(cls.NUM_DATA_SECTIONS)]
        text_addrs = [struct.unpack_from(">I", header, 0x48 + i * 4)[0] for i in range(cls.NUM_TEXT_SECTIONS)]
        data_addrs = [struct.unpack_from(">I", header, 0x64 + i * 4)[0] for i in range(cls.NUM_DATA_SECTIONS)]
        text_sizes = [struct.unpack_from(">I", header, 0x90 + i * 4)[0] for i in range(cls.NUM_TEXT_SECTIONS)]
        data_sizes = [struct.unpack_from(">I", header, 0xAC + i * 4)[0] for i in range(cls.NUM_DATA_SECTIONS)]

        bss_addr, bss_size, entry = struct.unpack_from(">III", header, 0xD8)

        text_secs: List[DolSection] = []
        for i in range(cls.NUM_TEXT_SECTIONS):
            off = text_offsets[i]
            addr = text_addrs[i]
            sz = text_sizes[i]
            if off > 0 and sz > 0:
                sec_data = bytearray(data[off : off + sz])
                text_secs.append(DolSection("text", i, off, addr, sz, sec_data))

        data_secs: List[DolSection] = []
        for i in range(cls.NUM_DATA_SECTIONS):
            off = data_offsets[i]
            addr = data_addrs[i]
            sz = data_sizes[i]
            if off > 0 and sz > 0:
                sec_data = bytearray(data[off : off + sz])
                data_secs.append(DolSection("data", i, off, addr, sz, sec_data))

        return cls(
            text_sections=text_secs,
            data_sections=data_secs,
            bss_address=bss_addr,
            bss_size=bss_size,
            entry_point=entry,
        )

    @classmethod
    def from_file(cls, filepath: Union[str, os.PathLike]) -> "DolFile":
        """Load a DOL executable from disk."""
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    @property
    def all_sections(self) -> List[DolSection]:
        """Return all active text and data sections sorted by file offset."""
        return sorted(self.text_sections + self.data_sections, key=lambda s: s.offset)

    def address_to_offset(self, address: int) -> Optional[int]:
        """Translate a RAM virtual address to a DOL file offset."""
        for sec in self.all_sections:
            if sec.contains_address(address):
                return sec.offset + (address - sec.address)
        return None

    def offset_to_address(self, offset: int) -> Optional[int]:
        """Translate a DOL file offset to a RAM virtual address."""
        for sec in self.all_sections:
            if sec.contains_offset(offset):
                return sec.address + (offset - sec.offset)
        return None

    def read_memory(self, address: int, size: int) -> bytes:
        """Read bytes directly from a virtual RAM address."""
        for sec in self.all_sections:
            if sec.contains_address(address):
                offset_in_sec = address - sec.address
                if offset_in_sec + size <= len(sec.data):
                    return bytes(sec.data[offset_in_sec : offset_in_sec + size])
                raise ValueError(
                    f"Read across section boundary: requested {size} bytes at 0x{address:08X}, but section ends at 0x{sec.end_address:08X}"
                )
        raise ValueError(f"Address 0x{address:08X} does not reside in any loaded DOL section")

    def write_memory(self, address: int, data: Union[bytes, bytearray]) -> None:
        """Write bytes directly into a section at the specified virtual RAM address."""
        size = len(data)
        for sec in self.all_sections:
            if sec.contains_address(address):
                offset_in_sec = address - sec.address
                if offset_in_sec + size <= len(sec.data):
                    sec.data[offset_in_sec : offset_in_sec + size] = data
                    return
                raise ValueError(
                    f"Write across section boundary: attempted to write {size} bytes at 0x{address:08X}, exceeding section end 0x{sec.end_address:08X}"
                )
        raise ValueError(f"Address 0x{address:08X} does not reside in any loaded DOL section")

    def add_section(
        self,
        is_text: bool,
        address: int,
        data: Union[bytes, bytearray],
        alignment: int = 32,
    ) -> DolSection:
        """
        Append a new section into the first available section slot.
        """
        target_list = self.text_sections if is_text else self.data_sections
        max_slots = self.NUM_TEXT_SECTIONS if is_text else self.NUM_DATA_SECTIONS
        sec_type = "text" if is_text else "data"

        used_indices = {s.index for s in target_list}
        available_index = None
        for i in range(max_slots):
            if i not in used_indices:
                available_index = i
                break

        if available_index is None:
            raise ValueError(f"No free {sec_type} section slots available (maximum {max_slots})")

        # Compute next file offset with alignment
        all_secs = self.all_sections
        if all_secs:
            last_end = max(s.offset + s.size for s in all_secs)
        else:
            last_end = self.HEADER_SIZE

        remainder = last_end % alignment
        offset = last_end if remainder == 0 else last_end + (alignment - remainder)

        size = len(data)
        sec = DolSection(
            section_type=sec_type,
            index=available_index,
            offset=offset,
            address=address,
            size=size,
            data=bytearray(data),
        )
        target_list.append(sec)
        return sec

    def allocate_code_cave(
        self,
        size: int,
        is_text: bool = True,
        preferred_address: Optional[int] = None,
        alignment: int = 32,
    ) -> Tuple[int, int]:
        """
        Allocate a zeroed code cave section and return (ram_address, file_offset).
        If preferred_address is None, places it beyond the highest existing section address.
        """
        if preferred_address is None:
            highest_addr = max((s.end_address for s in self.all_sections), default=0x80004000)
            rem = highest_addr % alignment
            preferred_address = highest_addr if rem == 0 else highest_addr + (alignment - rem)

        empty_data = bytearray(size)
        sec = self.add_section(is_text=is_text, address=preferred_address, data=empty_data, alignment=alignment)
        return sec.address, sec.offset

    def to_bytes(self) -> bytes:
        """Serialize the DOL header and all active sections into a binary byte string."""
        header = bytearray(self.HEADER_SIZE)

        # Build lookup tables for text and data sections by slot index
        text_by_idx = {s.index: s for s in self.text_sections}
        data_by_idx = {s.index: s for s in self.data_sections}

        for i in range(self.NUM_TEXT_SECTIONS):
            if i in text_by_idx:
                s = text_by_idx[i]
                struct.pack_into(">I", header, i * 4, s.offset)
                struct.pack_into(">I", header, 0x48 + i * 4, s.address)
                struct.pack_into(">I", header, 0x90 + i * 4, s.size)

        for i in range(self.NUM_DATA_SECTIONS):
            if i in data_by_idx:
                s = data_by_idx[i]
                struct.pack_into(">I", header, 0x1C + i * 4, s.offset)
                struct.pack_into(">I", header, 0x64 + i * 4, s.address)
                struct.pack_into(">I", header, 0xAC + i * 4, s.size)

        struct.pack_into(">III", header, 0xD8, self.bss_address, self.bss_size, self.entry_point)

        # Determine output file size
        all_secs = self.all_sections
        max_end = max((s.offset + s.size for s in all_secs), default=self.HEADER_SIZE)
        output = bytearray(max_end)

        output[:self.HEADER_SIZE] = header

        for sec in all_secs:
            output[sec.offset : sec.offset + sec.size] = sec.data

        return bytes(output)

    def save(self, filepath: Union[str, os.PathLike]) -> None:
        """Write the serialized DOL executable to disk."""
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())
