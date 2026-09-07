"""
miorom.link - In-ROM ELF32 Linker & Relocator Engine.
Allows linking compiled C and Assembly object files (.o / .elf) directly into ROM code caves.
Supports PowerPC (Wii/GameCube), ARM (GBA/NDS), and MIPS (PS1/N64/PSP) relocation types.
"""

from miorom.link.elf import (
    Elf32File,
    ElfRelocation,
    ElfSection,
    ElfSymbol,
    EM_386,
    EM_ARM,
    EM_MIPS,
    EM_PPC,
    SHT_NOBITS,
    SHT_REL,
    SHT_RELA,
)
from miorom.link.relocator import ElfRelocator, ElfLinkResult
from miorom.link.dol import DolBinary, DolSection
from miorom.link.injector import ElfInjector, InjectionReport
from miorom.link.heap import MioRomHeap, HeapStats, MemBlock

__all__ = [
    "Elf32File",
    "ElfSection",
    "ElfSymbol",
    "ElfRelocation",
    "ElfRelocator",
    "ElfLinkResult",
    "ElfInjector",
    "InjectionReport",
    "DolBinary",
    "DolSection",
    "MioRomHeap",
    "HeapStats",
    "MemBlock",
    "EM_386",
    "EM_ARM",
    "EM_MIPS",
    "EM_PPC",
    "SHT_NOBITS",
    "SHT_REL",
    "SHT_RELA",
]
