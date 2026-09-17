"""
miorom.link - In-ROM ELF32 Linker & Relocator Engine.
Allows linking compiled C and Assembly object files (.o / .elf) directly into ROM code caves.
Supports PowerPC (Wii/GameCube), ARM (GBA/NDS), and MIPS (PS1/N64/PSP) relocation types.
"""

from miorom.link.dol import (
    R_PPC_ADDR14,
    R_PPC_ADDR16,
    R_PPC_ADDR16_HA,
    R_PPC_ADDR16_HI,
    R_PPC_ADDR16_LO,
    R_PPC_ADDR24,
    R_PPC_ADDR32,
    R_PPC_NONE,
    R_PPC_REL14,
    R_PPC_REL24,
    R_RVL_NONE,
    R_RVL_SECT,
    R_RVL_STOP,
    DolBinary,
    DolSection,
    RelFile,
    RelHeader,
    RelocationEntry,
    RelSection,
)
from miorom.link.elf import (
    EM_386,
    EM_ARM,
    EM_MIPS,
    EM_PPC,
    SHT_NOBITS,
    SHT_REL,
    SHT_RELA,
    Elf32File,
    ElfRelocation,
    ElfSection,
    ElfSymbol,
)
from miorom.link.heap import HeapStats, MemBlock, MioRomHeap
from miorom.link.injector import ElfInjector, InjectionReport
from miorom.link.relocator import CompoundRelocationLinker, ElfLinkResult, ElfRelocator

__all__ = [
    "Elf32File",
    "ElfSection",
    "ElfSymbol",
    "ElfRelocation",
    "ElfRelocator",
    "ElfLinkResult",
    "CompoundRelocationLinker",
    "ElfInjector",
    "InjectionReport",
    "DolBinary",
    "DolSection",
    "RelFile",
    "RelHeader",
    "RelSection",
    "RelocationEntry",
    "R_PPC_NONE",
    "R_PPC_ADDR32",
    "R_PPC_ADDR24",
    "R_PPC_ADDR16",
    "R_PPC_ADDR16_LO",
    "R_PPC_ADDR16_HI",
    "R_PPC_ADDR16_HA",
    "R_PPC_ADDR14",
    "R_PPC_REL24",
    "R_PPC_REL14",
    "R_RVL_NONE",
    "R_RVL_SECT",
    "R_RVL_STOP",
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
