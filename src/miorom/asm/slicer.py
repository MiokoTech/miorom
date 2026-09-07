import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from miorom.asm.disasm import DisasmInstruction, UniversalDisassembler


@dataclass
class JumpTable:
    """
    Representation of an indirect jump table (switch-case statement)
    resolved through backward data flow slicing.
    """
    jump_address: int
    table_address: int
    entry_count: int
    stride: int
    default_target: Optional[int] = None
    case_targets: List[int] = field(default_factory=list)
    slice_instructions: List[DisasmInstruction] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"Jump Table at 0x{self.table_address:08X} (Referenced by 0x{self.jump_address:08X}):",
            f"  Entries : {self.entry_count} (Stride: {self.stride} bytes)",
            f"  Default : 0x{self.default_target:08X}" if self.default_target else "  Default : None",
            "  Targets :",
        ]
        for idx, t in enumerate(self.case_targets):
            lines.append(f"    - Case {idx:<2} -> 0x{t:08X}")
        return "\n".join(lines)


class DataFlowSlicer:
    """
    Backward Data Flow Slicing engine.
    Traces indirect jump instructions backwards to recover jump table base addresses,
    stride factors, bounds limits, and individual branch case targets.
    """

    @classmethod
    def find_jump_tables(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "ppc",
        endian: Optional[str] = None,
        max_slice_depth: int = 20,
    ) -> List[JumpTable]:
        """
        Scan a code buffer, detect indirect jumps, and recover all jump tables.
        """
        instructions = UniversalDisassembler.disassemble(
            data=data,
            base_address=base_address,
            arch=arch,
            endian=endian,
        )

        jump_tables: List[JumpTable] = []

        for idx, ins in enumerate(instructions):
            # Check for indirect jump
            is_indirect = False
            target_reg = None

            # PowerPC bctr / bcctr
            if arch.lower() in ("ppc", "powerpc", "wii", "gc"):
                if ins.mnemonic in ("bctr", "bcctr"):
                    is_indirect = True
            # ARM bx Rm / mov pc, Rm / ldr pc, [Rn, ...]
            elif arch.lower() in ("arm", "arm32"):
                if ins.mnemonic in ("bx", "mov") and ins.operands:
                    if ins.mnemonic == "bx" and ins.operands[0] != "lr":
                        is_indirect = True
                        target_reg = ins.operands[0]
                    elif ins.mnemonic == "mov" and ins.operands[0] == "pc":
                        is_indirect = True
                        target_reg = ins.operands[1]
            # MIPS jr $rs (except jr $ra)
            elif "mips" in arch.lower() or arch.lower() in ("psx", "n64", "psp"):
                if ins.mnemonic == "jr" and ins.operands and ins.operands[0] not in ("$ra", "$31"):
                    is_indirect = True
                    target_reg = ins.operands[0]

            if not is_indirect:
                continue

            # Slice backwards
            slice_start = max(0, idx - max_slice_depth)
            backward_slice = instructions[slice_start : idx + 1]

            jt = cls._resolve_jump_table(
                data=data,
                base_address=base_address,
                backward_slice=backward_slice,
                arch=arch,
                endian=endian,
            )
            if jt:
                jump_tables.append(jt)

        return jump_tables

    @classmethod
    def _resolve_jump_table(
        cls,
        data: bytes,
        base_address: int,
        backward_slice: List[DisasmInstruction],
        arch: str = "ppc",
        endian: Optional[str] = None,
    ) -> Optional[JumpTable]:
        """
        Perform backward slicing over a window of instructions leading to an indirect jump.
        """
        if not backward_slice:
            return None

        jump_ins = backward_slice[-1]
        arch_norm = arch.lower()

        table_base: Optional[int] = None
        entry_count: int = 0
        stride: int = 4
        default_target: Optional[int] = None

        # Trace PowerPC patterns
        if arch_norm in ("ppc", "powerpc", "wii", "gc"):
            ha_val = None
            lo_val = None

            for ins in backward_slice[:-1]:
                # Bounds check: cmplwi rX, N / cmpwi rX, N
                if ins.mnemonic in ("cmplwi", "cmpwi") and len(ins.operands) >= 2:
                    try:
                        entry_count = int(ins.operands[1], 0) + 1  # 0..N inclusive is N+1 cases
                    except ValueError:
                        pass

                # Conditional branch to default case
                if ins.is_branch and ins.is_conditional and ins.target_address and default_target is None:
                    default_target = ins.target_address

                # lis rX, table@ha
                if ins.mnemonic == "lis" and len(ins.operands) >= 2:
                    try:
                        ha_val = int(ins.operands[1], 0) << 16
                    except ValueError:
                        pass

                # addi rX, rX, table@l
                if ins.mnemonic == "addi" and len(ins.operands) >= 3 and ha_val is not None:
                    try:
                        lo = int(ins.operands[2], 0)
                        # Handle sign extension
                        if lo & 0x8000:
                            lo -= 0x10000
                        lo_val = lo
                        table_base = (ha_val + lo_val) & 0xFFFFFFFF
                    except ValueError:
                        pass

        # Trace MIPS patterns
        elif "mips" in arch_norm or arch_norm in ("psx", "n64", "psp"):
            hi_val = None
            for ins in backward_slice[:-1]:
                if ins.mnemonic == "sltiu" and len(ins.operands) >= 3:
                    try:
                        entry_count = int(ins.operands[2], 0)
                    except ValueError:
                        pass

                if ins.mnemonic == "lui" and len(ins.operands) >= 2:
                    try:
                        hi_val = int(ins.operands[1], 0) << 16
                    except ValueError:
                        pass

                if ins.mnemonic == "addiu" and len(ins.operands) >= 3 and hi_val is not None:
                    try:
                        lo = int(ins.operands[2], 0)
                        table_base = (hi_val + lo) & 0xFFFFFFFF
                    except ValueError:
                        pass

        # Fallback heuristic: default entry_count if not explicitly checked
        if table_base is not None and entry_count == 0:
            entry_count = 4  # Reasonable minimum estimate

        if table_base is None:
            return None

        # Read case targets from table in ROM data
        end = endian or (">" if arch_norm == "ppc" or "be" in arch_norm else "<")
        case_targets: List[int] = []

        table_off = table_base - base_address
        if 0 <= table_off < len(data):
            for i in range(entry_count):
                off = table_off + i * stride
                if off + stride <= len(data):
                    target = struct.unpack(f"{end}I", data[off : off + stride])[0]
                    case_targets.append(target)

        return JumpTable(
            jump_address=jump_ins.address,
            table_address=table_base,
            entry_count=entry_count,
            stride=stride,
            default_target=default_target,
            case_targets=case_targets,
            slice_instructions=backward_slice,
        )
