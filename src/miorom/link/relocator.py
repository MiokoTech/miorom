from miorom.result import MioRomResult
import struct
from dataclasses import dataclass
from miorom.core.schema import U16, U32
from typing import Dict, List, Optional, Tuple

from miorom.link.elf import (
    Elf32File,
    ElfRelocation,
    ElfSection,
    ElfSymbol,
    EM_ARM,
    EM_MIPS,
    EM_PPC,
    SHT_NOBITS,
)


@dataclass
class ElfLinkResult(MioRomResult):
    """
    Result of linking and relocating an ELF32 object into memory.
    """
    base_address: int
    binary: bytes
    symbol_table: Dict[str, int]
    section_offsets: Dict[str, int]
    section_sizes: Dict[str, int]
    unresolved_symbols: List[str]
    entry_point: Optional[int] = None

    @property
    def total_size(self) -> int:
        return len(self.binary)


class ElfRelocator:
    """
    In-ROM Linker and Relocator for compiled C / Assembly ELF32 object files.
    Merges loadable sections, resolves internal & external function symbols,
    and applies machine code relocations for ARM, MIPS, and PowerPC architectures.
    """

    def __init__(self, elf: Elf32File):
        self.elf = elf

    def link(
        self,
        base_address: int,
        external_symbols: Optional[Dict[str, int]] = None,
        entry_symbol: Optional[str] = None,
    ) -> ElfLinkResult:
        """
        Link and relocate ELF sections to base_address in RAM.
        External symbols (such as original game functions) are resolved via external_symbols dict.
        Returns an ElfLinkResult with linked machine code, symbol table, and memory layout.
        """
        externs = external_symbols or {}
        endian = self.elf.endian

        # Collect allocatable sections
        loadable_sections: List[ElfSection] = []
        for sec in self.elf.sections:
            # SHF_ALLOC = 0x2
            if (sec.sh_flags & 0x2) and sec.sh_type != 0 and (len(sec.data) > 0 or sec.sh_size > 0):
                loadable_sections.append(sec)

        # Calculate section virtual memory layout
        current_offset = 0
        section_offsets: Dict[str, int] = {}
        section_sizes: Dict[str, int] = {}
        section_buffers: Dict[str, bytearray] = {}

        for sec in loadable_sections:
            align = max(1, sec.sh_addralign)
            rem = current_offset % align
            if rem != 0:
                current_offset += align - rem

            section_offsets[sec.name] = current_offset
            if sec.sh_type == SHT_NOBITS:  # .bss uninitialized data
                section_buffers[sec.name] = bytearray(sec.sh_size)
                section_sizes[sec.name] = sec.sh_size
                current_offset += sec.sh_size
            else:
                section_buffers[sec.name] = bytearray(sec.data)
                section_sizes[sec.name] = len(sec.data)
                current_offset += len(sec.data)

        # Resolve symbol addresses
        resolved_symbols: Dict[str, int] = {}
        unresolved_symbols: List[str] = []
        for sym in self.elf.symbol_list:
            if sym.is_undefined:
                if sym.name in externs:
                    resolved_symbols[sym.name] = externs[sym.name]
                else:
                    resolved_symbols[sym.name] = 0
                    if sym.name:
                        unresolved_symbols.append(sym.name)
            else:
                if sym.section_name in section_offsets:
                    sec_base = base_address + section_offsets[sym.section_name]
                    resolved_symbols[sym.name] = sec_base + sym.st_value
                else:
                    resolved_symbols[sym.name] = base_address + sym.st_value

        # Apply relocations
        for rel in self.elf.relocations:
            sec_name = rel.section_name
            if sec_name not in section_buffers:
                continue

            buf = section_buffers[sec_name]
            p_addr = base_address + section_offsets[sec_name] + rel.r_offset
            s_addr = resolved_symbols.get(rel.symbol_name, 0)
            addend = rel.r_addend

            # ARM Relocations (EM_ARM = 40)
            if self.elf.e_machine == EM_ARM:
                # R_ARM_ABS32 = 2
                if rel.rel_type == 2:
                    val = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (val + s_addr + addend) & 0xFFFFFFFF
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_ARM_REL32 = 3
                elif rel.rel_type == 3:
                    val = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (val + s_addr + addend - p_addr) & 0xFFFFFFFF
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_ARM_CALL = 28, R_ARM_JUMP24 = 29
                elif rel.rel_type in (28, 29):
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    branch_offset = (s_addr + addend - p_addr - 8) >> 2
                    new_instr = (orig_instr & 0xFF000000) | (branch_offset & 0x00FFFFFF)
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(new_instr, endian=endian)

                # R_ARM_THM_CALL = 10 (Thumb BL/BLX pair)
                elif rel.rel_type == 10:
                    h1 = U16().unpack(buf, rel.r_offset, endian)[0]
                    h2 = U16().unpack(buf, rel.r_offset + 2, endian)[0]
                    diff = s_addr + addend - p_addr - 4
                    diff >>= 1
                    h1 = 0xF000 | ((diff >> 11) & 0x07FF)
                    h2 = 0xF800 | (diff & 0x07FF)
                    buf[rel.r_offset:rel.r_offset + 4] = U16().pack(h1, endian=endian) + U16().pack(h2, endian=endian)

            # MIPS Relocations (EM_MIPS = 8)
            elif self.elf.e_machine == EM_MIPS:
                # R_MIPS_32 = 2
                if rel.rel_type == 2:
                    val = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (val + s_addr + addend) & 0xFFFFFFFF
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_MIPS_26 = 4 (J / JAL)
                elif rel.rel_type == 4:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    target = (s_addr + addend) >> 2
                    new_instr = (orig_instr & 0xFC000000) | (target & 0x03FFFFFF)
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(new_instr, endian=endian)

                # R_MIPS_HI16 = 5
                elif rel.rel_type == 5:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    hi = ((s_addr + addend + 0x8000) >> 16) & 0xFFFF
                    new_instr = (orig_instr & 0xFFFF0000) | hi
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(new_instr, endian=endian)

                # R_MIPS_LO16 = 6
                elif rel.rel_type == 6:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    lo = (s_addr + addend) & 0xFFFF
                    new_instr = (orig_instr & 0xFFFF0000) | lo
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(new_instr, endian=endian)

            # PowerPC Relocations (EM_PPC = 20)
            elif self.elf.e_machine == EM_PPC:
                # R_PPC_NONE = 0
                if rel.rel_type == 0:
                    pass

                # R_PPC_ADDR32 = 1
                elif rel.rel_type == 1:
                    val = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (val + s_addr + addend) & 0xFFFFFFFF
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_ADDR24 = 2 (Unconditional branch target)
                elif rel.rel_type == 2:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (orig_instr & 0xFC000003) | ((s_addr + addend) & 0x03FFFFFC)
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_ADDR16_LO = 4
                elif rel.rel_type == 4:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    lo = (s_addr + addend) & 0xFFFF
                    res = (orig_instr & 0xFFFF0000) | lo
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_ADDR16_HI = 5
                elif rel.rel_type == 5:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    hi = ((s_addr + addend) >> 16) & 0xFFFF
                    res = (orig_instr & 0xFFFF0000) | hi
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_ADDR16_HA = 6
                elif rel.rel_type == 6:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    ha = ((s_addr + addend + 0x8000) >> 16) & 0xFFFF
                    res = (orig_instr & 0xFFFF0000) | ha
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_ADDR14 = 7 (Conditional branch target)
                elif rel.rel_type == 7:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (orig_instr & 0xFFFF0003) | ((s_addr + addend) & 0x0000FFFC)
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_REL24 = 10 (Relative branch b/bl)
                elif rel.rel_type == 10:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    diff = s_addr + addend - p_addr
                    res = (orig_instr & 0xFC000003) | (diff & 0x03FFFFFC)
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_REL14 = 11 (Relative conditional branch)
                elif rel.rel_type == 11:
                    orig_instr = U32().unpack(buf, rel.r_offset, endian)[0]
                    diff = s_addr + addend - p_addr
                    res = (orig_instr & 0xFFFF0003) | (diff & 0x0000FFFC)
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

                # R_PPC_REL32 = 26
                elif rel.rel_type == 26:
                    val = U32().unpack(buf, rel.r_offset, endian)[0]
                    res = (val + s_addr + addend - p_addr) & 0xFFFFFFFF
                    buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

            # Generic 32-bit absolute
            elif rel.rel_type == 1:
                val = U32().unpack(buf, rel.r_offset, endian)[0]
                res = (val + s_addr + addend) & 0xFFFFFFFF
                buf[rel.r_offset:rel.r_offset + 4] = U32().pack(res, endian=endian)

        # Pack relocated sections into contiguous binary
        out = bytearray(current_offset)
        for sec in loadable_sections:
            sec_off = section_offsets[sec.name]
            buf = section_buffers[sec.name]
            out[sec_off:sec_off + len(buf)] = buf

        # Resolve entry point address
        entry_point = None
        if entry_symbol and entry_symbol in resolved_symbols:
            entry_point = resolved_symbols[entry_symbol]
        else:
            for candidate in ("payload_entry", "payload_main", "main", "_start", "hook_entry"):
                if candidate in resolved_symbols:
                    entry_point = resolved_symbols[candidate]
                    break
            if entry_point is None:
                for sym in self.elf.symbol_list:
                    if not sym.is_undefined and sym.section_name == ".text" and sym.name in resolved_symbols:
                        entry_point = resolved_symbols[sym.name]
                        break
            if entry_point is None:
                entry_point = base_address

        return ElfLinkResult(
            base_address=base_address,
            binary=bytes(out),
            symbol_table=resolved_symbols,
            section_offsets=section_offsets,
            section_sizes=section_sizes,
            unresolved_symbols=unresolved_symbols,
            entry_point=entry_point,
        )

    def relocate(
        self,
        base_address: int,
        external_symbols: Optional[Dict[str, int]] = None,
    ) -> bytes:
        """
        Link and relocate ELF sections to base_address in RAM.
        External symbols (such as original game functions) are resolved via external_symbols dict.
        Returns the linked executable machine code buffer.
        """
        return self.link(base_address=base_address, external_symbols=external_symbols).binary

    def inject(
        self,
        rom_data: bytearray,
        rom_offset: int,
        ram_address: int,
        external_symbols: Optional[Dict[str, int]] = None,
    ) -> int:
        """
        Relocate ELF code to ram_address and inject into rom_data at rom_offset.
        Returns the number of bytes injected.
        """
        linked_bytes = self.relocate(ram_address, external_symbols=external_symbols)
        end_offset = rom_offset + len(linked_bytes)
        if end_offset > len(rom_data):
            rom_data.extend(b"\x00" * (end_offset - len(rom_data)))
        rom_data[rom_offset:end_offset] = linked_bytes
        return len(linked_bytes)


class CompoundRelocationLinker:
    """
    Solves MIPS compound relocations by pairing R_MIPS_HI16 with subsequent R_MIPS_LO16
    and computing proper sign-extension carry bit adjustments.
    """

    @classmethod
    def calculate_hi_lo_pair(cls, target_addr: int) -> Tuple[int, int]:
        """
        Computes (hi16, lo16) pair for MIPS LUI / ADDIU instructions with sign-extension carry.
        """
        lo = target_addr & 0xFFFF
        simm = struct.unpack(">h", struct.pack(">H", lo))[0]
        hi = ((target_addr - simm) >> 16) & 0xFFFF
        return hi, lo
