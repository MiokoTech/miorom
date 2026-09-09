"""
miorom.script.splicer
~~~~~~~~~~~~~~~~~~~~~
Bytecode Stream Splicer & Jump Shifter Primitive.
Enables inserting or replacing bytes in a binary VM bytecode stream
while automatically recalculating absolute and relative branch jump targets.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass
import struct
from typing import List, Sequence, Tuple


@dataclass
class SpliceTarget(MioRomResult):
    """Represents a branch or jump operand in a bytecode stream."""
    instruction_offset: int
    operand_offset: int
    operand_size: int = 2        # 2 (u16/s16) or 4 (u32/s32)
    is_relative: bool = False    # True if target is relative to instruction_offset
    endian: str = "<"


class BytecodeStreamSplicer:
    """
    Pure modular primitive to splice new bytecode and adjust branch targets.
    """

    @classmethod
    def splice_and_shift(
        cls,
        bytecode: bytes,
        splice_offset: int,
        insert_bytes: bytes,
        branch_targets: Sequence[SpliceTarget],
    ) -> Tuple[bytes, int]:
        """
        Inserts insert_bytes at splice_offset in bytecode, and adjusts all
        branch target operands that span across the splice point.
        Returns (new_bytecode, adjusted_branches_count).
        """
        delta = len(insert_bytes)
        if delta == 0:
            return bytecode, 0

        # Construct new buffer with inserted bytes
        buf = bytearray()
        buf.extend(bytecode[:splice_offset])
        buf.extend(insert_bytes)
        buf.extend(bytecode[splice_offset:])

        adjusted_count = 0

        for bt in branch_targets:
            # Adjust operand offset if it was after the splice point
            eff_op_pos = bt.operand_offset if bt.operand_offset < splice_offset else bt.operand_offset + delta
            eff_insn_pos = bt.instruction_offset if bt.instruction_offset < splice_offset else bt.instruction_offset + delta

            fmt = f"{bt.endian}{'I' if bt.operand_size == 4 else 'H'}"
            # Read original target value from original bytecode
            raw_val = struct.unpack_from(fmt, bytecode, bt.operand_offset)[0]

            if bt.is_relative:
                # Relative jump: target_abs = instruction_offset + raw_val
                # Handle signed relative branch
                signed_val = raw_val
                if bt.operand_size == 2 and raw_val >= 0x8000:
                    signed_val = raw_val - 0x10000
                elif bt.operand_size == 4 and raw_val >= 0x80000000:
                    signed_val = raw_val - 0x100000000

                target_abs = bt.instruction_offset + signed_val

                # If jump crosses the splice point, adjust relative delta
                # Case 1: instruction before splice, target after splice -> distance increases by delta
                if bt.instruction_offset < splice_offset and target_abs >= splice_offset:
                    new_rel = signed_val + delta
                # Case 2: instruction after splice, target before splice -> distance decreases by delta
                elif bt.instruction_offset >= splice_offset and target_abs < splice_offset:
                    new_rel = signed_val - delta
                else:
                    new_rel = signed_val

                # Mask to unsigned representation for packing
                mask = 0xFFFFFFFF if bt.operand_size == 4 else 0xFFFF
                struct.pack_into(fmt, buf, eff_op_pos, new_rel & mask)
                adjusted_count += 1
            else:
                # Absolute jump: target_abs = raw_val
                # If target is at or after splice_offset, increase by delta
                if raw_val >= splice_offset:
                    new_abs = raw_val + delta
                    struct.pack_into(fmt, buf, eff_op_pos, new_abs)
                    adjusted_count += 1

        return bytes(buf), adjusted_count
