"""
miorom.rom.expander
~~~~~~~~~~~~~~~~~~~
Physical ROM Layout Expander & Far Memory Relocator.
Expands cartridge and optical ROM layouts beyond standard hardware boundaries
(GBA 16MB -> 32MB, N64 16MB -> 64MB, NDS capacity bitshift updates),
enabling massive space expansions for translated script pools, high-res textures,
and injected C/assembly code payloads.
"""

import math
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from miorom.platforms.n64 import fix_n64_checksum


@dataclass
class RomExpansionReport:
    platform: str
    original_size: int
    new_size: int
    expanded_bytes: int
    far_memory_base: int
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "==================================================",
            "           ROM Layout Expansion Report            ",
            "==================================================",
            f"  Platform         : {self.platform.upper()}",
            f"  Original Size    : {self.original_size:,} bytes (0x{self.original_size:X})",
            f"  Expanded Size    : {self.new_size:,} bytes (0x{self.new_size:X})",
            f"  Added Space      : +{self.expanded_bytes:,} bytes",
            f"  Far Memory Base  : 0x{self.far_memory_base:08X}",
        ]
        if self.notes:
            lines.append("  Notes:")
            for note in self.notes:
                lines.append(f"    - {note}")
        lines.append("==================================================")
        return "\n".join(lines)


class RomLayoutExpander:
    """
    Physical ROM Expansion and Far Memory Relocator.
    """

    GBA_MAX_SIZE = 32 * 1024 * 1024       # 32 MB
    N64_MAX_SIZE = 64 * 1024 * 1024       # 64 MB
    GBA_ROM_BASE = 0x08000000

    @classmethod
    def expand_gba(
        cls,
        rom_data: bytes,
        target_size: int = GBA_MAX_SIZE,
        pad_byte: int = 0xFF,
    ) -> Tuple[bytearray, RomExpansionReport]:
        """
        Expand a Game Boy Advance ROM to a target size (default 32MB).
        Pads new area with 0xFF.
        """
        orig_len = len(rom_data)
        if target_size <= orig_len:
            raise ValueError(
                f"Target size (0x{target_size:X}) must be greater than current size (0x{orig_len:X})"
            )
        if target_size > cls.GBA_MAX_SIZE:
            raise ValueError(f"GBA hardware addressing maximum is 32MB (0x{cls.GBA_MAX_SIZE:X})")

        out = bytearray(rom_data)
        delta = target_size - orig_len
        out.extend(bytes([pad_byte]) * delta)

        report = RomExpansionReport(
            platform="gba",
            original_size=orig_len,
            new_size=target_size,
            expanded_bytes=delta,
            far_memory_base=cls.GBA_ROM_BASE + orig_len,
            notes=[
                f"Padded with 0x{pad_byte:02X} up to 32MB limit",
                f"New far memory mapped at GBA RAM 0x{cls.GBA_ROM_BASE + orig_len:08X}",
            ],
        )
        return out, report

    @classmethod
    def expand_n64(
        cls,
        rom_data: bytes,
        target_size: int = N64_MAX_SIZE,
        pad_byte: int = 0x00,
        recalculate_checksum: bool = True,
    ) -> Tuple[bytearray, RomExpansionReport]:
        """
        Expand a Nintendo 64 ROM to a target size (default 64MB) and recalculates CIC checksum.
        """
        orig_len = len(rom_data)
        if target_size <= orig_len:
            raise ValueError(f"Target size 0x{target_size:X} must exceed current size 0x{orig_len:X}")

        out = bytearray(rom_data)
        delta = target_size - orig_len
        out.extend(bytes([pad_byte]) * delta)

        notes = [f"Padded with 0x{pad_byte:02X} up to 0x{target_size:X}"]
        if recalculate_checksum:
            try:
                out = fix_n64_checksum(out)
                notes.append("Successfully recalculated and patched N64 CIC boot checksum")
            except Exception as e:
                notes.append(f"Warning: Checksum calculation skipped: {e}")

        report = RomExpansionReport(
            platform="n64",
            original_size=orig_len,
            new_size=target_size,
            expanded_bytes=delta,
            far_memory_base=0x10000000 + orig_len,
            notes=notes,
        )
        return out, report

    @classmethod
    def expand_nds(
        cls,
        rom_data: bytes,
        target_size: int,
        pad_byte: int = 0xFF,
    ) -> Tuple[bytearray, RomExpansionReport]:
        """
        Expand a Nintendo DS (.nds) ROM and update header device capacity byte.
        """
        orig_len = len(rom_data)
        if target_size <= orig_len:
            raise ValueError(f"Target size 0x{target_size:X} must exceed current size 0x{orig_len:X}")

        out = bytearray(rom_data)
        delta = target_size - orig_len
        out.extend(bytes([pad_byte]) * delta)

        # In NDS header, offset 0x14 stores Device Capacity (1 << (20 + n) bytes)
        # Calculate smallest power of 2 >= target_size
        capacity_exp = math.ceil(math.log2(target_size))
        nds_device_capacity = max(0, capacity_exp - 17)  # standard NDS formula
        if len(out) > 0x15:
            out[0x14] = nds_device_capacity & 0xFF

        # Offset 0x80 stores Total Used ROM size (ARM9/ARM7 + FAT/FNT + overlays)
        # Update 0x80 with new size
        if len(out) >= 0x84:
            struct.pack_into("<I", out, 0x80, target_size)

        report = RomExpansionReport(
            platform="nds",
            original_size=orig_len,
            new_size=target_size,
            expanded_bytes=delta,
            far_memory_base=orig_len,
            notes=[
                f"Updated NDS header device capacity (0x14) = 0x{nds_device_capacity:02X}",
                f"Updated Total ROM size (0x80) = 0x{target_size:08X}",
            ],
        )
        return out, report

    @classmethod
    def relocate_to_far_memory(
        cls,
        rom_data: bytearray,
        source_offset: int,
        source_size: int,
        target_offset: int,
        pointer_locations: List[int],
        ram_base: int = 0,
        endian: str = ">",
        pad_byte: int = 0x00,
    ) -> int:
        """
        Relocate a chunk of data into far memory, clear the old space,
        and update all referencing pointers.
        Returns the number of pointers successfully updated.
        """
        if source_offset + source_size > len(rom_data):
            raise ValueError("Source slice exceeds ROM buffer bounds")
        if target_offset + source_size > len(rom_data):
            raise ValueError("Target offset exceeds expanded ROM buffer bounds")

        # 1. Copy data chunk to far target
        payload = bytes(rom_data[source_offset : source_offset + source_size])
        rom_data[target_offset : target_offset + source_size] = payload

        # 2. Fill source area with pad_byte (freeing space or creating code cave)
        rom_data[source_offset : source_offset + source_size] = bytes([pad_byte]) * source_size

        # 3. Update referencing pointers
        new_ram_ptr = target_offset + ram_base
        fmt = f"{endian}I"
        updated_ptrs = 0

        for ptr_loc in pointer_locations:
            if ptr_loc + 4 <= len(rom_data):
                struct.pack_into(fmt, rom_data, ptr_loc, new_ram_ptr)
                updated_ptrs += 1

        return updated_ptrs
