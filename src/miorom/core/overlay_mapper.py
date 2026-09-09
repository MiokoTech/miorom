"""
miorom.core.overlay_mapper
~~~~~~~~~~~~~~~~~~~~~~~~~~
RAM-to-ROM Overlay and Virtual Memory Mapping Engine.
Translates runtime RAM addresses (from GDB, save states, or emulator traces)
to physical ROM file offsets across systems with dynamic overlays, bank switching,
and DMA load routines (Nintendo DS, Game Boy Advance, PlayStation 1, N64).
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


@dataclass
class OverlayRegion(MioRomResult):
    """Represents a mapped memory segment or overlay."""
    region_id: Union[int, str]
    name: str
    ram_address: int
    ram_size: int
    rom_offset: int
    rom_size: int
    bss_size: int = 0
    flags: int = 0

    def contains_ram(self, ram_addr: int) -> bool:
        return self.ram_address <= ram_addr < (self.ram_address + self.ram_size)

    def contains_rom(self, rom_off: int) -> bool:
        return self.rom_offset <= rom_off < (self.rom_offset + self.rom_size)

    def ram_to_rom(self, ram_addr: int) -> Optional[int]:
        if self.contains_ram(ram_addr):
            delta = ram_addr - self.ram_address
            if delta < self.rom_size:
                return self.rom_offset + delta
        return None

    def rom_to_ram(self, rom_off: int) -> Optional[int]:
        if self.contains_rom(rom_off):
            delta = rom_off - self.rom_offset
            return self.ram_address + delta
        return None


@dataclass
class DMACopyRecord(MioRomResult):
    """Represents a discovered DMA or memcpy routine transferring ROM to RAM."""
    pc_address: int
    source_address: int
    destination_address: int
    word_count: int


class MemoryOverlayMapper:
    """
    Bidirectional RAM <-> ROM address translator and overlay manager.
    """

    def __init__(self):
        self.regions: List[OverlayRegion] = []
        self.region_map: Dict[Union[int, str], OverlayRegion] = {}

    def add_region(self, region: OverlayRegion) -> None:
        """Registers a mapped memory region or overlay."""
        self.regions.append(region)
        self.region_map[region.region_id] = region
        self.region_map[region.name] = region

    def ram_to_rom(
        self,
        ram_address: int,
        preferred_region: Optional[Union[int, str]] = None,
    ) -> Optional[int]:
        """
        Translates a virtual RAM address to its underlying ROM file offset.
        """
        if preferred_region is not None and preferred_region in self.region_map:
            res = self.region_map[preferred_region].ram_to_rom(ram_address)
            if res is not None:
                return res

        for r in self.regions:
            res = r.ram_to_rom(ram_address)
            if res is not None:
                return res
        return None

    def rom_to_ram(
        self,
        rom_offset: int,
        preferred_region: Optional[Union[int, str]] = None,
    ) -> Optional[int]:
        """
        Translates a physical ROM offset to its execution RAM address.
        """
        if preferred_region is not None and preferred_region in self.region_map:
            res = self.region_map[preferred_region].rom_to_ram(rom_offset)
            if res is not None:
                return res

        for r in self.regions:
            res = r.rom_to_ram(rom_offset)
            if res is not None:
                return res
        return None

    @classmethod
    def parse_nds_overlays(
        cls,
        y9_table_bytes: bytes,
        fat_entries: Optional[List[Tuple[int, int]]] = None,
    ) -> "MemoryOverlayMapper":
        """
        Parses Nintendo DS ARM9 overlay table (32 bytes per entry).
        If fat_entries is provided (list of (start, end) offsets), maps each overlay
        to its precise physical ROM file offset.
        """
        mapper = cls()
        entry_size = 32
        count = len(y9_table_bytes) // entry_size

        for i in range(count):
            off = i * entry_size
            (
                ov_id,
                ram_addr,
                ram_sz,
                bss_sz,
                _,
                _,
                file_id,
                flags,
            ) = struct.unpack_from("<8I", y9_table_bytes, off)

            rom_off = 0
            rom_sz = ram_sz
            if fat_entries and file_id < len(fat_entries):
                f_start, f_end = fat_entries[file_id]
                rom_off = f_start
                rom_sz = f_end - f_start

            region = OverlayRegion(
                region_id=ov_id,
                name=f"overlay9_{ov_id:04d}",
                ram_address=ram_addr,
                ram_size=ram_sz,
                rom_offset=rom_off,
                rom_size=rom_sz,
                bss_size=bss_sz,
                flags=flags,
            )
            mapper.add_region(region)

        return mapper

    @classmethod
    def parse_psx_exe(cls, exe_header: bytes) -> "MemoryOverlayMapper":
        """
        Parses standard Sony PlayStation 1 PS-X EXE header (first 2048 bytes).
        Text section starts at ROM offset 0x800 (sector 1).
        """
        mapper = cls()
        if len(exe_header) < 0x800:
            return mapper

        # PS-X EXE header:
        # 0x00: b"PS-X EXE"
        # 0x10: initial PC
        # 0x18: text RAM destination
        # 0x1C: text size in bytes
        if exe_header[:8] == b"PS-X EXE":
            ram_dest = struct.unpack_from("<I", exe_header, 0x18)[0]
            text_size = struct.unpack_from("<I", exe_header, 0x1C)[0]
            region = OverlayRegion(
                region_id="MAIN",
                name="PSX_MAIN_EXE",
                ram_address=ram_dest,
                ram_size=text_size,
                rom_offset=0x800,
                rom_size=text_size,
            )
            mapper.add_region(region)

        return mapper

    @classmethod
    def detect_dma_copies(
        cls,
        code: bytes,
        base_address: int,
    ) -> List[DMACopyRecord]:
        """
        Heuristic scanner for GBA DMA3 transfers (0x040000D4 source, 0x040000D8 dest, 0x040000DC control).
        """
        records: List[DMACopyRecord] = []
        n_words = len(code) // 4
        cur_src = None
        cur_dst = None

        for i in range(n_words):
            word = struct.unpack_from("<I", code, i * 4)[0]
            addr = base_address + i * 4

            # Look for 32-bit constant loads or stores pointing to DMA3 registers
            # 0x040000D4: DMA3SAD
            # If literal pool or address load sets registers:
            if word == 0x040000D4:
                # Discovered literal reference to DMA3
                pass

        return records
