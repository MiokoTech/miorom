import pytest
from miorom.asm.branch import (
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


def test_thumb_branch_class_and_range_check():
    from miorom.asm.branch import ThumbBranch
    from miorom.errors import RelocationError, ParseError

    source = 0x08000400

    # In-range forward branch (+1000 bytes)
    target_ok = source + 1000
    b_bytes = ThumbBranch.encode_b(source, target_ok)
    assert len(b_bytes) == 2
    assert ThumbBranch.decode_b(source, b_bytes) == target_ok

    # In-range backward branch (-1000 bytes)
    target_back = source - 1000
    b_back = ThumbBranch.encode_b(source, target_back)
    assert ThumbBranch.decode_b(source, b_back) == target_back

    # Out of range positive (> +2046 bytes)
    with pytest.raises(RelocationError, match="out of range"):
        ThumbBranch.encode_b(source, source + 2052)

    # Out of range negative (< -2048 bytes)
    with pytest.raises(RelocationError, match="out of range"):
        ThumbBranch.encode_b(source, source - 2054)

    # Non 2-byte aligned target
    with pytest.raises(ParseError, match="not 2-byte aligned"):
        ThumbBranch.encode_b(source, source + 101)

    # Thumb BL 32-bit roundtrip
    bl_target = source + 0x10000
    bl_bytes = ThumbBranch.encode_bl(source, bl_target)
    assert len(bl_bytes) == 4
    assert ThumbBranch.decode_bl(source, bl_bytes) == bl_target


def test_powerpc_branch_high_address_absolute_decode():
    """Ensure PowerPC absolute branch to high memory (e.g. 0xFE000000) decodes to unsigned uint32."""
    from miorom.asm.branch import PowerPCBranch
    b = PowerPCBranch.encode_b(0x1000, 0xFE000000, absolute=True)
    target, lk, aa = PowerPCBranch.decode_b(0x1000, b)
    assert aa is True
    assert target == 0xFE000000
