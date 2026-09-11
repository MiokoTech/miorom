"""
miorom.platforms.nds.overlay
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo DS ARM9 and ARM7 Overlay Table Manager and Code/Data Relocator.
Provides overlay table (y9.bin/y7.bin) serialization, RAM address relocation,
and LZ10 overlay compression management for localized ROM translation.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from miorom.compression.lz10 import LZ10
from miorom.platforms.nds.rom import NDSOverlayEntry, NDSOverlayEntryStruct, NDSRom
from miorom.result import MioRomResult


@dataclass
class OverlayAllocationReport(MioRomResult):
    """Summary diagnostics for an overlay update or relocation operation."""
    overlay_id: int
    old_ram_address: int
    new_ram_address: int
    old_ram_size: int
    new_ram_size: int
    old_file_size: int
    new_file_size: int
    is_compressed: bool


class NDSOverlayTable(MioRomResult):
    """
    Parser, serializer, and editor for Nintendo DS overlay definition tables (y9.bin / y7.bin).
    Each entry specifies the RAM execution address, allocated buffer size, BSS reservation,
    and associated FAT file index.
    """

    ENTRY_SIZE = 32

    def __init__(self, entries: Optional[List[NDSOverlayEntry]] = None):
        self.entries: List[NDSOverlayEntry] = entries or []

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray]) -> "NDSOverlayTable":
        """Parse an overlay table from raw binary bytes."""
        num_entries = len(data) // cls.ENTRY_SIZE
        entries: List[NDSOverlayEntry] = []
        for i in range(num_entries):
            off = i * cls.ENTRY_SIZE
            parsed = NDSOverlayEntryStruct.from_bytes(data, offset=off)
            entries.append(
                NDSOverlayEntry(
                    id=parsed.id,
                    ram_address=parsed.ram_address,
                    ram_size=parsed.ram_size,
                    bss_size=parsed.bss_size,
                    sinit_init=parsed.sinit_init,
                    sinit_init_end=parsed.sinit_init_end,
                    file_id=parsed.file_id,
                    flags=parsed.flags,
                )
            )
        return cls(entries=entries)

    def to_bytes(self) -> bytes:
        """Serialize all overlay entries into binary table bytes."""
        out = bytearray()
        for entry in self.entries:
            struct_obj = NDSOverlayEntryStruct(
                id=entry.id,
                ram_address=entry.ram_address,
                ram_size=entry.ram_size,
                bss_size=entry.bss_size,
                sinit_init=entry.sinit_init,
                sinit_init_end=entry.sinit_init_end,
                file_id=entry.file_id,
                flags=entry.flags,
            )
            out.extend(struct_obj.to_bytes())
        return bytes(out)

    def get_entry(self, overlay_id: int) -> Optional[NDSOverlayEntry]:
        """Look up an overlay record by its unique numeric ID."""
        for e in self.entries:
            if e.id == overlay_id:
                return e
        return None

    def add_entry(self, entry: NDSOverlayEntry) -> None:
        """Register a new overlay entry in the table."""
        existing = self.get_entry(entry.id)
        if existing is not None:
            raise ValueError(f"Overlay ID {entry.id} already exists in overlay table")
        self.entries.append(entry)

    def update_entry(
        self,
        overlay_id: int,
        ram_address: Optional[int] = None,
        ram_size: Optional[int] = None,
        bss_size: Optional[int] = None,
        file_id: Optional[int] = None,
        flags: Optional[int] = None,
        is_compressed: Optional[bool] = None,
    ) -> NDSOverlayEntry:
        """Update fields of an existing overlay entry."""
        entry = self.get_entry(overlay_id)
        if entry is None:
            raise KeyError(f"Overlay ID {overlay_id} not found in table")

        if ram_address is not None:
            entry.ram_address = ram_address
        if ram_size is not None:
            entry.ram_size = ram_size
        if bss_size is not None:
            entry.bss_size = bss_size
        if file_id is not None:
            entry.file_id = file_id
        if flags is not None:
            entry.flags = flags

        if is_compressed is not None:
            if is_compressed:
                entry.flags |= 0x01000000
            else:
                entry.flags &= ~0x01000000

        return entry

    def relocate(self, overlay_id: int, new_ram_address: int) -> None:
        """Relocate the RAM load address of an overlay."""
        self.update_entry(overlay_id, ram_address=new_ram_address)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)


class NDSOverlayCompressor:
    """
    Handles Nintendo DS overlay compression detection, LZ10 decompression,
    and size recalculation for localized overlays.
    """

    COMPRESSION_FLAG = 0x01000000

    @classmethod
    def is_compressed(cls, data: Union[bytes, bytearray], flags: int = 0) -> bool:
        """
        Determine if overlay payload is compressed based on flags or header inspection.
        """
        if (flags & cls.COMPRESSION_FLAG) != 0 or (flags & 0x01) != 0:
            return True
        if len(data) >= 4 and data[0] == 0x10:
            return True
        return False

    @classmethod
    def decompress(cls, data: Union[bytes, bytearray], flags: int = 0) -> bytes:
        """Decompress overlay payload if compressed, otherwise return raw bytes."""
        if cls.is_compressed(data, flags):
            try:
                return LZ10.decompress(data)
            except Exception:
                return bytes(data)
        return bytes(data)

    @classmethod
    def compress(cls, data: Union[bytes, bytearray]) -> bytes:
        """Compress overlay payload using standard BIOS LZ10 algorithm."""
        return LZ10.compress(bytes(data))


class NDSOverlayManager:
    """
    High-level orchestrator for extracting, modifying, compressing, and injecting
    ARM9 and ARM7 overlays within an NDSRom image.
    """

    def __init__(self, rom: NDSRom):
        self.rom = rom

    def get_overlay_table(self, processor: str = "arm9") -> NDSOverlayTable:
        """Load and parse the overlay table for the requested processor."""
        is_arm9 = processor.lower() == "arm9"
        offset = self.rom.header.arm9_overlay_offset if is_arm9 else self.rom.header.arm7_overlay_offset
        size = self.rom.header.arm9_overlay_size if is_arm9 else self.rom.header.arm7_overlay_size

        if offset == 0 or size == 0:
            return NDSOverlayTable([])

        raw_table = bytes(self.rom.data[offset:offset + size])
        return NDSOverlayTable.from_bytes(raw_table)

    def save_overlay_table(self, table: NDSOverlayTable, processor: str = "arm9") -> None:
        """Serialize and write back the overlay table into the ROM buffer."""
        is_arm9 = processor.lower() == "arm9"
        offset = self.rom.header.arm9_overlay_offset if is_arm9 else self.rom.header.arm7_overlay_offset
        size = self.rom.header.arm9_overlay_size if is_arm9 else self.rom.header.arm7_overlay_size

        table_bytes = table.to_bytes()
        if len(table_bytes) > size:
            raise ValueError(
                f"Serialized overlay table ({len(table_bytes)} bytes) exceeds allocated space ({size} bytes)"
            )

        self.rom.data[offset:offset + len(table_bytes)] = table_bytes

    def extract_overlay(
        self,
        overlay_id: int,
        processor: str = "arm9",
        decompress: bool = True,
    ) -> bytes:
        """Extract overlay data by overlay ID, optionally decompressing it."""
        table = self.get_overlay_table(processor)
        entry = table.get_entry(overlay_id)
        if entry is None:
            raise KeyError(f"Overlay ID {overlay_id} not found in {processor} table")

        fat_off = self.rom.fat_offset + (entry.file_id * 8)
        if fat_off + 8 > len(self.rom.data):
            raise KeyError(f"FAT file entry for ID {entry.file_id} not found in ROM")

        start = int.from_bytes(self.rom.data[fat_off:fat_off + 4], "little")
        end = int.from_bytes(self.rom.data[fat_off + 4:fat_off + 8], "little")

        raw_data = bytes(self.rom.data[start:end])
        if decompress:
            return NDSOverlayCompressor.decompress(raw_data, entry.flags)
        return raw_data

    def replace_overlay_data(
        self,
        overlay_id: int,
        new_data: bytes,
        processor: str = "arm9",
        compress: bool = True,
        update_ram_size: bool = True,
    ) -> OverlayAllocationReport:
        """
        Replace overlay payload with updated translated data, update FAT boundaries,
        adjust RAM size in overlay table, and optionally compress.
        """
        table = self.get_overlay_table(processor)
        entry = table.get_entry(overlay_id)
        if entry is None:
            raise KeyError(f"Overlay ID {overlay_id} not found in {processor} table")

        fat_off = self.rom.fat_offset + (entry.file_id * 8)
        if fat_off + 8 > len(self.rom.data):
            raise KeyError(f"FAT file entry for ID {entry.file_id} not found in ROM")

        start = int.from_bytes(self.rom.data[fat_off:fat_off + 4], "little")
        end = int.from_bytes(self.rom.data[fat_off + 4:fat_off + 8], "little")

        old_ram_size = entry.ram_size
        old_file_size = end - start
        uncompressed_size = len(new_data)

        if compress:
            final_data = NDSOverlayCompressor.compress(new_data)
            entry.flags |= NDSOverlayCompressor.COMPRESSION_FLAG
        else:
            final_data = bytes(new_data)
            entry.flags &= ~NDSOverlayCompressor.COMPRESSION_FLAG

        if update_ram_size:
            entry.ram_size = uncompressed_size

        current_capacity = end - start
        if len(final_data) <= current_capacity:
            self.rom.data[start:start + len(final_data)] = final_data
            pad_len = current_capacity - len(final_data)
            if pad_len > 0:
                self.rom.data[start + len(final_data):end] = b"\x00" * pad_len
        else:
            old_end = len(self.rom.data)
            rem = old_end % 512
            new_top = old_end if rem == 0 else old_end + (512 - rem)
            new_bottom = new_top + len(final_data)

            self.rom.data.extend(b"\x00" * (new_bottom - len(self.rom.data)))
            self.rom.data[new_top:new_bottom] = final_data

            self.rom.data[fat_off:fat_off + 4] = new_top.to_bytes(4, "little")
            self.rom.data[fat_off + 4:fat_off + 8] = new_bottom.to_bytes(4, "little")

        self.save_overlay_table(table, processor)

        return OverlayAllocationReport(
            overlay_id=overlay_id,
            old_ram_address=entry.ram_address,
            new_ram_address=entry.ram_address,
            old_ram_size=old_ram_size,
            new_ram_size=entry.ram_size,
            old_file_size=old_file_size,
            new_file_size=len(final_data),
            is_compressed=compress,
        )
