"""
miorom.asm.jump_table
~~~~~~~~~~~~~~~~~~~~~
Heuristic Jump Table (Switch-Case) Detector & Resolver.
Discovers indirect branch tables across ARM32, Thumb, MIPS, and PowerPC architectures.
Extracts case bounds, target addresses, default fallbacks, and tags code/data boundaries
to prevent disassemblers from corrupting jump table data.
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction
from miorom.asm.disambiguator import CodeDataDisambiguator, ByteClassification
from miorom.asm.slicer import JumpTable, DataFlowSlicer


class JumpTableDetector:
    """
    Scans binary machine code for indirect jump and switch-case dispatch patterns.
    """

    @classmethod
    def detect_arm_jump_tables(
        cls,
        data: bytes,
        base_address: int,
        endian: str = "<",
    ) -> List[JumpTable]:
        """
        Detects ARM32 switch-case patterns:
        1. ADD PC, PC, Rm, LSL #2 (0xE08FF10X)
        2. LDR PC, [PC, Rm, LSL #2] (0xE79FF10X)
        Followed immediately (or at PC+8) by an array of 32-bit target addresses or branch opcodes.
        """
        jump_tables: List[JumpTable] = []
        if len(data) < 16:
            return jump_tables

        num_words = len(data) // 4
        for i in range(num_words):
            word = struct.unpack_from(f"{endian}I", data, i * 4)[0]
            addr = base_address + i * 4

            is_add_pc_lsl2 = (word & 0xFFFFFFF0) == 0xE08FF100
            is_ldr_pc_lsl2 = (word & 0xFFFFFFF0) == 0xE79FF100

            if is_add_pc_lsl2 or is_ldr_pc_lsl2:
                # In ARM state, PC is current address + 8
                table_addr = addr + 8
                table_off = (i + 2) * 4

                # Scan backwards for CMP Rm, #N (bounds check) and conditional branch to default
                case_count = 4  # Default reasonable estimate
                default_target = None

                lookback_start = max(0, i - 12)
                for k in range(i - 1, lookback_start - 1, -1):
                    w_prev = struct.unpack_from(f"{endian}I", data, k * 4)[0]
                    # CMP Rm, #imm8: 0xE35X00YY
                    if (w_prev & 0xFFF0F000) == 0xE3500000:
                        imm8 = w_prev & 0xFF
                        case_count = imm8 + 1
                    # BHI / BHS default_target: bits 31..28 = 0x8 or 0x2
                    cond_code = (w_prev >> 28) & 0xF
                    if cond_code in (0x2, 0x8) and ((w_prev >> 25) & 0x7) == 0b101:
                        imm24 = w_prev & 0x00FFFFFF
                        if imm24 & 0x00800000:
                            b_off = (imm24 - 0x01000000) << 2
                        else:
                            b_off = imm24 << 2
                        instr_addr = base_address + k * 4
                        default_target = (instr_addr + 8 + b_off) & 0xFFFFFFFF

                # Extract case targets
                case_targets: List[int] = []
                stride = 4
                if 0 <= table_off < len(data):
                    for c in range(case_count):
                        entry_off = table_off + c * stride
                        if entry_off + stride <= len(data):
                            raw_target = struct.unpack_from(f"{endian}I", data, entry_off)[0]
                            # Check if entry is a B <target> instruction (0xEAxxxxxx)
                            if ((raw_target >> 24) & 0xFF) == 0xEA:
                                imm24 = raw_target & 0x00FFFFFF
                                if imm24 & 0x00800000:
                                    b_off = (imm24 - 0x01000000) << 2
                                else:
                                    b_off = imm24 << 2
                                entry_addr = table_addr + c * stride
                                abs_target = (entry_addr + 8 + b_off) & 0xFFFFFFFF
                                case_targets.append(abs_target)
                            else:
                                case_targets.append(raw_target)

                if len(case_targets) >= 2:
                    jump_tables.append(
                        JumpTable(
                            jump_address=addr,
                            table_address=table_addr,
                            entry_count=len(case_targets),
                            stride=stride,
                            default_target=default_target,
                            case_targets=case_targets,
                        )
                    )

        return jump_tables


class JumpTableResolver:
    """
    High-level facade for recovering switch-case jump tables across consoles.
    Integrates with CodeDataDisambiguator to preserve code integrity.
    """

    @classmethod
    def resolve_all(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "arm",
        endian: Optional[str] = None,
    ) -> List[JumpTable]:
        """
        Finds all jump tables for the specified architecture.
        Combines pattern matching and backward data flow slicing.
        """
        arch_norm = arch.lower()
        if arch_norm in ("arm", "arm32", "gba_arm", "nds_arm"):
            jts = JumpTableDetector.detect_arm_jump_tables(data, base_address, endian=endian or "<")
            if jts:
                return jts
            return DataFlowSlicer.find_jump_tables(data, base_address, arch="arm", endian=endian)
        elif arch_norm in ("ppc", "powerpc", "wii", "gc"):
            return DataFlowSlicer.find_jump_tables(data, base_address, arch="ppc", endian=endian)
        elif "mips" in arch_norm or arch_norm in ("psx", "n64", "psp"):
            return DataFlowSlicer.find_jump_tables(data, base_address, arch="mips", endian=endian)
        else:
            return DataFlowSlicer.find_jump_tables(data, base_address, arch=arch, endian=endian)

    @classmethod
    def mark_in_disambiguator(
        cls,
        target: Union[CodeDataDisambiguator, List[ByteClassification], Any],
        jump_tables: Sequence[JumpTable],
        base_address: int,
    ) -> int:
        """
        Marks all bytes spanned by jump tables as ByteClassification.JUMP_TABLE.
        Prevents disassembler from misinterpreting table data as executable code.
        Returns the total number of bytes protected.
        """
        labels = target.classifications if hasattr(target, "classifications") else target
        total_protected = 0
        for jt in jump_tables:
            start_off = jt.table_address - base_address
            table_size = jt.entry_count * jt.stride
            for byte_off in range(start_off, start_off + table_size):
                if 0 <= byte_off < len(labels):
                    labels[byte_off] = ByteClassification.JUMP_TABLE
                    total_protected += 1
        return total_protected

    @classmethod
    def to_switch_cases(cls, jump_table: JumpTable) -> Dict[int, int]:
        """Maps case index (0, 1, 2, ...) to target address."""
        return {idx: target for idx, target in enumerate(jump_table.case_targets)}

    @classmethod
    def to_c_switch(
        cls,
        jump_table: JumpTable,
        switch_var: str = "case_var",
        indent: str = "    ",
    ) -> str:
        """Synthesizes structured C switch-case block."""
        lines = [f"switch ({switch_var}) {{"]
        for idx, target in enumerate(jump_table.case_targets):
            lines.append(f"{indent}case {idx}:")
            lines.append(f"{indent}{indent}goto loc_{target:08X};")
        if jump_table.default_target:
            lines.append(f"{indent}default:")
            lines.append(f"{indent}{indent}goto loc_{jump_table.default_target:08X};")
        lines.append("}")
        return "\n".join(lines)
