import pytest
from miorom.asm.branch_calc import (
    calc_arm_branch,
    resolve_arm_branch,
    calc_thumb_branch,
    resolve_thumb_branch,
    calc_mips_jump,
    resolve_mips_jump,
    calc_mips_branch,
    resolve_mips_branch,
    calc_6502_branch,
    resolve_6502_branch,
)


def test_arm_branch():
    src = 0x08000100
    # Forward jump
    dest_fwd = 0x08000500
    op_b = calc_arm_branch(src, dest_fwd, link=False)
    assert resolve_arm_branch(src, op_b) == dest_fwd

    # Backward jump with link (BL)
    dest_back = 0x08000040
    op_bl = calc_arm_branch(src, dest_back, link=True)
    assert (op_bl >> 24) & 1 == 1  # Link bit set
    assert resolve_arm_branch(src, op_bl) == dest_back

    # Misaligned target error
    with pytest.raises(ValueError):
        calc_arm_branch(src, 0x08000103)


def test_thumb_branch():
    src = 0x08001000
    # Forward Thumb call
    dest_fwd = 0x08002400
    h1, h2 = calc_thumb_branch(src, dest_fwd)
    assert resolve_thumb_branch(src, h1, h2) == dest_fwd

    # Backward Thumb call
    dest_back = 0x08000200
    h1_b, h2_b = calc_thumb_branch(src, dest_back)
    assert resolve_thumb_branch(src, h1_b, h2_b) == dest_back


def test_mips_jump():
    src = 0x80040000
    dest = 0x80054320

    j_op = calc_mips_jump(dest, link=False)
    assert (j_op >> 26) == 2
    assert resolve_mips_jump(src, j_op) == dest

    jal_op = calc_mips_jump(dest, link=True)
    assert (jal_op >> 26) == 3
    assert resolve_mips_jump(src, jal_op) == dest


def test_mips_branch():
    src = 0x80001000
    # Forward branch
    dest_fwd = 0x80001080
    beq = calc_mips_branch(src, dest_fwd, opcode=0x04, rs=4, rt=5)
    assert resolve_mips_branch(src, beq) == dest_fwd

    # Backward branch
    dest_back = 0x80000F80
    bne = calc_mips_branch(src, dest_back, opcode=0x05, rs=2, rt=3)
    assert resolve_mips_branch(src, bne) == dest_back


def test_6502_branch():
    src = 0x8000
    # Forward branch (+10 bytes)
    dest_fwd = 0x800A
    op, disp = calc_6502_branch(src, dest_fwd, opcode=0xF0)  # BEQ
    assert op == 0xF0
    assert resolve_6502_branch(src, disp) == dest_fwd

    # Backward branch (-20 bytes)
    dest_back = 0x7FEC
    _, disp_b = calc_6502_branch(src, dest_back)
    assert resolve_6502_branch(src, disp_b) == dest_back

    # Out of range error (> 127 bytes)
    with pytest.raises(ValueError):
        calc_6502_branch(src, 0x8200)
