"""
miorom.asm.literal_relocator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Hardcoded Executable String & Code Literal Relocator.
Solves the challenge of translating hardcoded strings embedded inside executable
code (.text sections / ARM9 / DOL / SLUS). Relocates strings to designated
ROM caves or expanded slack space and automatically patches split instruction
pairs (ARM MOV/MOVT, PowerPC LIS/ADDI, MIPS LUI/ADDIU) and PC-relative literal pools.
"""

from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.asm.instruction_scanner import (
    PPCInstructionScanner,
    MIPSInstructionScanner,
    ARMInstructionScanner,
    UniversalInstructionScanner,
    CodePointer,
    ARMLiteralPointer,
    ARMMovPairPointer,
)


@dataclass
class LiteralRelocationReport:
    """Detailed summary of code literal relocation."""
    old_string: str
    new_string: str
    old_offset: int
    new_offset: int
    old_address: int
    new_address: int
    pointers_patched: int
    patch_offsets: List[int] = field(default_factory=list)


class CodeLiteralRelocator:
    """
    High-level orchestrator for discovering and repointing hardcoded code strings.
    """

    @classmethod
    def relocate_string(
        cls,
        rom: bytearray,
        old_str: Union[str, bytes],
        new_str: Union[str, bytes],
        cave_offset: int,
        ram_base: int = 0,
        arch: str = "arm",
        endian: str = "<",
    ) -> LiteralRelocationReport:
        """
        Relocates a hardcoded string from original ROM position to cave_offset,
        and rewrites all machine instructions that reference its virtual address.
        """
        old_bytes = old_str.encode("utf-8") if isinstance(old_str, str) else old_str
        new_bytes = new_str.encode("utf-8") if isinstance(new_str, str) else new_str

        # 1. Locate original string in ROM
        old_off = rom.find(old_bytes)
        if old_off == -1:
            raise ValueError(f"Old string {old_str!r} not found in ROM buffer.")

        old_vaddr = ram_base + old_off
        new_vaddr = ram_base + cave_offset

        # 2. Write new string into cave (with null terminator)
        rom[cave_offset : cave_offset + len(new_bytes)] = new_bytes
        if cave_offset + len(new_bytes) < len(rom):
            rom[cave_offset + len(new_bytes)] = 0  # Null terminator

        patched_count = 0
        patch_offsets: List[int] = []

        # 3. Discover and patch code pointers according to architecture
        arch_lower = arch.lower()
        min_tgt = min(old_vaddr, ram_base)
        max_tgt = max(old_vaddr, ram_base + len(rom)) + 0x10000

        if arch_lower in ("arm", "arm32"):
            # A. Scan for ARM literal pool pointers
            literal_ptrs = ARMInstructionScanner.find_literal_pointers(
                code=bytes(rom),
                min_target=min_tgt,
                max_target=max_tgt,
                base_address=ram_base,
                endian=endian,
            )
            for lp in literal_ptrs:
                if lp.target_address == old_vaddr:
                    lp.patch(rom, new_vaddr, endian=endian)
                    patched_count += 1
                    patch_offsets.append(lp.pool_offset)

            # B. Scan for ARM MOV/MOVT pairs
            mov_pairs = ARMInstructionScanner.find_mov_pairs(
                code=bytes(rom),
                min_target=min_tgt,
                max_target=max_tgt,
                base_address=ram_base,
                endian=endian,
            )
            for mp in mov_pairs:
                if mp.target_address == old_vaddr:
                    mp.patch(rom, new_vaddr, endian=endian)
                    patched_count += 1
                    patch_offsets.append(mp.movw_offset)

        elif arch_lower in ("ppc", "powerpc"):
            ppc_ptrs = PPCInstructionScanner.find_split_pointers(
                code=bytes(rom),
                min_target=min_tgt,
                max_target=max_tgt,
                base_address=ram_base,
                endian=endian,
            )
            for ptr in ppc_ptrs:
                if ptr.target_address == old_vaddr:
                    ptr.patch(rom, new_vaddr, endian=endian)
                    patched_count += 1
                    patch_offsets.append(ptr.lis_offset)

        elif arch_lower in ("mips", "mips32"):
            mips_ptrs = MIPSInstructionScanner.find_split_pointers(
                code=bytes(rom),
                min_target=min_tgt,
                max_target=max_tgt,
                endian=endian,
            )
            for ptr in mips_ptrs:
                if ptr.target_address == old_vaddr:
                    ptr.patch(rom, new_vaddr, endian=endian)
                    patched_count += 1
                    patch_offsets.append(ptr.lis_offset)

        else:
            # Universal fallback
            all_ptrs = UniversalInstructionScanner.scan_all(
                data=bytes(rom),
                base_address=ram_base,
                endian=endian,
            )
            for ptr in all_ptrs:
                if ptr.target_address == old_vaddr:
                    ptr.patch(rom, new_vaddr, endian=endian)
                    patched_count += 1
                    patch_offsets.append(ptr.lis_offset)

        return LiteralRelocationReport(
            old_string=old_str if isinstance(old_str, str) else old_str.decode("utf-8", "replace"),
            new_string=new_str if isinstance(new_str, str) else new_str.decode("utf-8", "replace"),
            old_offset=old_off,
            new_offset=cave_offset,
            old_address=old_vaddr,
            new_address=new_vaddr,
            pointers_patched=patched_count,
            patch_offsets=patch_offsets,
        )
