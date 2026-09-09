from miorom.result import MioRomResult
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any


@dataclass
class MemoryRegion(MioRomResult):
    name: str
    file_offset: int
    ram_address: int
    size: int

    @property
    def file_end(self) -> int:
        return self.file_offset + self.size

    @property
    def ram_end(self) -> int:
        return self.ram_address + self.size

    def contains_file_offset(self, offset: int) -> bool:
        return self.file_offset <= offset < self.file_end

    def contains_ram_address(self, addr: int) -> bool:
        return self.ram_address <= addr < self.ram_end

    def file_to_ram(self, offset: int) -> int:
        return self.ram_address + (offset - self.file_offset)

    def ram_to_file(self, addr: int) -> int:
        return self.file_offset + (addr - self.ram_address)


class MemoryMap:
    """
    Virtual Memory Address Resolver.
    Translates bi-directionally between ROM file offsets and console RAM addresses.
    Supports linear, banked, and multi-region console memory architectures.
    """

    def __init__(self):
        self.regions: List[MemoryRegion] = []

    def add_region(self, name: str, file_offset: int, ram_address: int, size: int) -> "MemoryMap":
        self.regions.append(MemoryRegion(name, file_offset, ram_address, size))
        return self

    def file_to_ram(self, file_offset: int) -> Optional[int]:
        for r in self.regions:
            if r.contains_file_offset(file_offset):
                return r.file_to_ram(file_offset)
        return None

    def ram_to_file(self, ram_address: int) -> Optional[int]:
        for r in self.regions:
            if r.contains_ram_address(ram_address):
                return r.ram_to_file(ram_address)
        return None

    def resolve_pointer(self, ptr_value: int) -> Optional[int]:
        """Converts a RAM address pointer read from game code into a ROM file offset."""
        return self.ram_to_file(ptr_value)

    def make_pointer(self, file_offset: int) -> Optional[int]:
        """Converts a ROM file offset into a RAM pointer value to write into game code."""
        return self.file_to_ram(file_offset)

    # -----------------------------------------------------------------------
    # Console Architecture Presets
    # -----------------------------------------------------------------------

    @classmethod
    def gba(cls, rom_size: int = 0x02000000) -> "MemoryMap":
        """Standard Game Boy Advance ROM mapping (Cartridge ROM space starts at 0x08000000)."""
        m = cls()
        m.add_region("ROM_WS0", file_offset=0, ram_address=0x08000000, size=rom_size)
        return m

    @classmethod
    def nds_arm9(cls, file_offset: int = 0x4000, ram_address: int = 0x02000000, size: int = 0x00400000) -> "MemoryMap":
        """Nintendo DS ARM9 Main RAM mapping (Main RAM at 0x02000000)."""
        m = cls()
        m.add_region("ARM9_MAIN", file_offset=file_offset, ram_address=ram_address, size=size)
        return m

    @classmethod
    def wii_main(cls, file_offset: int = 0, ram_address: int = 0x80004000, size: int = 0x01800000) -> "MemoryMap":
        """Nintendo Wii MEM1 cached memory mapping (KSEG0 0x80000000)."""
        m = cls()
        m.add_region("WII_MEM1", file_offset=file_offset, ram_address=ram_address, size=size)
        return m

    @classmethod
    def snes_lorom(cls, rom_size: int = 0x200000) -> "MemoryMap":
        """SNES LoROM mapping (Banks $80-$FF, $8000-$FFFF, 32KB per bank)."""
        m = cls()
        bank_count = (rom_size + 0x7FFF) // 0x8000
        for b in range(bank_count):
            f_off = b * 0x8000
            ram_addr = ((0x80 + b) << 16) | 0x8000
            m.add_region(f"BANK_{0x80+b:02X}", file_offset=f_off, ram_address=ram_addr, size=0x8000)
        return m

    @classmethod
    def snes_hirom(cls, rom_size: int = 0x400000) -> "MemoryMap":
        """SNES HiROM mapping (Banks $C0-$FF, $0000-$FFFF, 64KB per bank)."""
        m = cls()
        bank_count = (rom_size + 0xFFFF) // 0x10000
        for b in range(bank_count):
            f_off = b * 0x10000
            ram_addr = ((0xC0 + b) << 16)
            m.add_region(f"BANK_{0xC0+b:02X}", file_offset=f_off, ram_address=ram_addr, size=0x10000)
        return m
