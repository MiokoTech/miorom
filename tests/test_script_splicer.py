import struct
import pytest
from miorom.script.splicer import BytecodeStreamSplicer, SpliceTarget


def test_splice_absolute_jump():
    # Bytecode:
    # 0x00: NOP (0x00)
    # 0x01: JUMP_ABS target=0x08 (opcode 0x10, u16 target at 0x02)
    # 0x04: NOP, NOP, NOP, NOP
    # 0x08: TARGET_LABEL (0xAA)
    bc = bytearray([0x00, 0x10, 0x08, 0x00, 0x00, 0x00, 0x00, 0x00, 0xAA])
    # Splice 4 bytes of extra opcode at offset 0x04
    insert_bytes = bytes([0x20, 0x21, 0x22, 0x23])

    target = SpliceTarget(
        instruction_offset=0x01,
        operand_offset=0x02,
        operand_size=2,
        is_relative=False,
        endian="<",
    )

    new_bc, adj_count = BytecodeStreamSplicer.splice_and_shift(
        bytecode=bytes(bc),
        splice_offset=0x04,
        insert_bytes=insert_bytes,
        branch_targets=[target],
    )

    assert adj_count == 1
    assert len(new_bc) == len(bc) + 4
    # The jump target originally pointed to 0x08. Since 4 bytes were inserted before it,
    # the target should now point to 0x08 + 4 = 0x0C.
    new_target = struct.unpack_from("<H", new_bc, 0x02)[0]
    assert new_target == 0x0C
    # Verify byte at 0x0C is the TARGET_LABEL 0xAA
    assert new_bc[0x0C] == 0xAA


def test_splice_relative_jump():
    # Bytecode:
    # 0x00: BRANCH_REL +6 (opcode 0x15, s16 relative at 0x01) -> target = 0x00 + 6 = 0x06
    # 0x03: NOP, NOP, NOP
    # 0x06: TARGET_CODE (0xBB)
    bc = bytearray([0x15, 0x06, 0x00, 0x00, 0x00, 0x00, 0xBB])
    # Insert 3 bytes at offset 0x03
    insert_bytes = bytes([0x99, 0x99, 0x99])

    target = SpliceTarget(
        instruction_offset=0x00,
        operand_offset=0x01,
        operand_size=2,
        is_relative=True,
        endian="<",
    )

    new_bc, adj_count = BytecodeStreamSplicer.splice_and_shift(
        bytecode=bytes(bc),
        splice_offset=0x03,
        insert_bytes=insert_bytes,
        branch_targets=[target],
    )

    assert adj_count == 1
    assert len(new_bc) == len(bc) + 3
    # Original relative delta was +6. Spliced 3 bytes between instruction and target.
    # New relative delta should be +9.
    new_rel = struct.unpack_from("<H", new_bc, 0x01)[0]
    assert new_rel == 9
    # Target code should now be at 0x00 + 9 = 0x09
    assert new_bc[0x09] == 0xBB
