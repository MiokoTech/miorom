"""
miorom.text.pointer_relinker
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Script table pointer relinker for ROM hacking workflows.
Scans pointer tables, finds free space in ROM, and rewrites strings
in-place or relocates them when they no longer fit their original slot.
Supports absolute, relative, and banked pointer types with configurable
endianness and pointer widths.
"""

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class PointerRecord(MioRomResult):
    """Describes a single pointer entry discovered in a ROM pointer table."""
    pointer_offset: int
    target_offset: int
    pointer_type: str
    bank: int = 0


@dataclass
class RelinkReport(MioRomResult):
    """Summary produced by PointerRelinker.relink()."""
    entries_relinked: int
    entries_relocated: int
    bytes_saved: int
    pointer_updates: List[Tuple[int, int, int]]
    free_space_used: List[Tuple[int, int]]


_STRUCT_FMTS = {
    (1, 'little'): 'B',
    (1, 'big'):    'B',
    (2, 'little'): '<H',
    (2, 'big'):    '>H',
    (3, 'little'): None,
    (3, 'big'):    None,
    (4, 'little'): '<I',
    (4, 'big'):    '>I',
}


class PointerRelinker:
    """
    Rewrites script pointer tables after text has been edited and reencoded.

    Handles in-place rewrites when new text fits the original slot, and
    automatic relocation to free ROM space when text has grown too large.
    Supports 1-, 2-, 3-, and 4-byte pointers in little- or big-endian form,
    as well as absolute, relative, and banked addressing modes.
    """

    def __init__(
        self,
        pointer_size: int = 4,
        endian: str = 'little',
        base_address: int = 0,
        bank_size: int = 0x4000,
    ) -> None:
        if pointer_size not in (1, 2, 3, 4):
            raise ValueError(f"pointer_size must be 1, 2, 3, or 4; got {pointer_size}")
        if endian not in ('little', 'big'):
            raise ValueError(f"endian must be 'little' or 'big'; got {endian!r}")
        self.pointer_size = pointer_size
        self.endian = endian
        self.base_address = base_address
        self.bank_size = bank_size

    def read_pointer(self, rom: Union[bytes, bytearray], offset: int) -> int:
        """Read a single pointer value from rom at the given byte offset."""
        size = self.pointer_size
        raw = rom[offset:offset + size]
        if size == 3:
            if self.endian == 'little':
                return raw[0] | (raw[1] << 8) | (raw[2] << 16)
            return (raw[0] << 16) | (raw[1] << 8) | raw[2]
        fmt = _STRUCT_FMTS[(size, self.endian)]
        return struct.unpack_from(fmt, raw)[0]

    def write_pointer(self, buf: bytearray, offset: int, value: int) -> None:
        """Write a single pointer value into buf at the given byte offset."""
        size = self.pointer_size
        if size == 3:
            if self.endian == 'little':
                buf[offset]     = value & 0xFF
                buf[offset + 1] = (value >> 8) & 0xFF
                buf[offset + 2] = (value >> 16) & 0xFF
            else:
                buf[offset]     = (value >> 16) & 0xFF
                buf[offset + 1] = (value >> 8) & 0xFF
                buf[offset + 2] = value & 0xFF
            return
        fmt = _STRUCT_FMTS[(size, self.endian)]
        struct.pack_into(fmt, buf, offset, value)

    def _to_rom_offset(self, pointer_value: int, pointer_type: str, bank: int) -> int:
        """Convert a raw pointer value to a flat ROM file offset."""
        if pointer_type == 'absolute':
            return pointer_value - self.base_address
        if pointer_type == 'relative':
            return pointer_value
        if pointer_type == 'banked':
            within_bank = pointer_value - self.base_address
            return bank * self.bank_size + within_bank
        raise ValueError(f"Unknown pointer_type: {pointer_type!r}")

    def _to_pointer_value(self, rom_offset: int, pointer_type: str, bank: int) -> int:
        """Convert a flat ROM file offset back to the appropriate pointer value."""
        if pointer_type == 'absolute':
            return rom_offset + self.base_address
        if pointer_type == 'relative':
            return rom_offset
        if pointer_type == 'banked':
            within_bank = rom_offset - bank * self.bank_size
            return within_bank + self.base_address
        raise ValueError(f"Unknown pointer_type: {pointer_type!r}")

    def scan_pointer_table(
        self,
        rom: Union[bytes, bytearray],
        table_offset: int,
        entry_count: int,
        pointer_type: str = 'absolute',
    ) -> List[PointerRecord]:
        """
        Read entry_count consecutive pointers starting at table_offset.

        Returns one PointerRecord per entry with the decoded target ROM offset.
        For banked pointers the bank field is left as 0; callers should fill it
        after scanning if they have separate bank-number tables.
        """
        records: List[PointerRecord] = []
        size = self.pointer_size
        for i in range(entry_count):
            ptr_off = table_offset + i * size
            raw_val = self.read_pointer(rom, ptr_off)
            target = self._to_rom_offset(raw_val, pointer_type, bank=0)
            records.append(PointerRecord(
                pointer_offset=ptr_off,
                target_offset=target,
                pointer_type=pointer_type,
                bank=0,
            ))
        return records

    def find_free_space(
        self,
        rom: Union[bytes, bytearray],
        size_needed: int,
        fill_byte: int = 0xFF,
        search_start: int = 0,
    ) -> Optional[int]:
        """
        Scan rom for a contiguous run of fill_byte >= size_needed bytes.

        Returns the starting offset of the first qualifying run, or None if
        no such run exists from search_start onward.
        """
        if size_needed <= 0:
            return search_start
        run_start = -1
        run_len = 0
        for i in range(search_start, len(rom)):
            if rom[i] == fill_byte:
                if run_len == 0:
                    run_start = i
                run_len += 1
                if run_len >= size_needed:
                    return run_start
            else:
                run_len = 0
                run_start = -1
        return None

    def _measure_slot(
        self,
        rom: Union[bytes, bytearray],
        target_offset: int,
        fill_byte: int,
    ) -> int:
        """
        Estimate the original slot size by scanning forward from target_offset
        until a fill_byte is found or another non-data byte terminates the slot.

        In practice we scan until we hit a contiguous fill_byte run of >= 1 byte,
        treating that first fill byte as the slot boundary.
        """
        pos = target_offset
        while pos < len(rom) and rom[pos] != fill_byte:
            pos += 1
        return pos - target_offset

    def relink(
        self,
        rom: Union[bytes, bytearray],
        pointers: List[PointerRecord],
        new_strings: List[bytes],
        fill_byte: int = 0xFF,
    ) -> Tuple[bytearray, RelinkReport]:
        """
        Rewrite all strings referenced by pointers and update the pointer table.

        For each (pointer, new_string) pair:
        - If the new string fits within the original slot, it is written in-place
          and the original slot tail is padded with fill_byte.
        - If it is too large, free space is located elsewhere in the ROM, the
          string is written there, and the pointer is updated to the new address.

        Returns the modified ROM as a bytearray and a RelinkReport.
        """
        buf = bytearray(rom)
        entries_relinked = 0
        entries_relocated = 0
        bytes_saved = 0
        pointer_updates: List[Tuple[int, int, int]] = []
        free_space_used: List[Tuple[int, int]] = []

        for record, new_str in zip(pointers, new_strings):
            old_target = record.target_offset
            slot_size = self._measure_slot(buf, old_target, fill_byte)
            new_len = len(new_str)

            if new_len <= slot_size:
                buf[old_target:old_target + new_len] = new_str
                tail = slot_size - new_len
                if tail > 0:
                    buf[old_target + new_len:old_target + slot_size] = bytes([fill_byte]) * tail
                    bytes_saved += tail
                new_target = old_target
                entries_relinked += 1
            else:
                dest = self.find_free_space(buf, new_len, fill_byte)
                if dest is None:
                    raise RuntimeError(
                        f"No free space of {new_len} bytes found for pointer at "
                        f"0x{record.pointer_offset:X}"
                    )
                buf[dest:dest + new_len] = new_str
                new_target = dest
                free_space_used.append((dest, new_len))
                entries_relocated += 1

            new_ptr_val = self._to_pointer_value(new_target, record.pointer_type, record.bank)
            old_ptr_val = self.read_pointer(buf, record.pointer_offset)
            self.write_pointer(buf, record.pointer_offset, new_ptr_val)
            pointer_updates.append((record.pointer_offset, old_target, new_target))

        return buf, RelinkReport(
            entries_relinked=entries_relinked,
            entries_relocated=entries_relocated,
            bytes_saved=bytes_saved,
            pointer_updates=pointer_updates,
            free_space_used=free_space_used,
        )
