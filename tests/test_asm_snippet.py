import pytest
from miorom.asm import AsmSnippet, ArmSnippet, MipsSnippet


def test_arm_snippet_basic():
    arm = AsmSnippet.arm("<")
    # PUSH {r4, r5, lr} -> mask: r4(1<<4), r5(1<<5), lr(1<<14)
    arm.push(["r4", "r5", "lr"])
    arm.mov_imm("r0", 42)
    arm.add_imm("r1", "r0", 10)
    arm.sub_imm("r2", "r1", 5)
    arm.nop(2)
    arm.bx("lr")
    
    code = arm.emit()
    assert isinstance(code, bytes)
    assert len(code) == 7 * 4  # 7 instructions * 4 bytes = 28 bytes


def test_arm_snippet_branch():
    arm = AsmSnippet.arm("<")
    # Branch to target from current PC
    arm.b(target_vaddr=0x02001000, current_pc=0x02000000)
    arm.bl(target_vaddr=0x02002000, current_pc=0x02000004)
    code = arm.emit()
    assert len(code) == 8


def test_arm_snippet_invalid_reg():
    arm = AsmSnippet.arm()
    with pytest.raises(ValueError, match="Unknown ARM register"):
        arm.mov_imm("invalid_reg", 1)


def test_mips_snippet_basic():
    mips = AsmSnippet.mips(">")
    mips.lui("v0", 0x1234)
    mips.addiu("v0", "v0", 0x5678)
    mips.nop(1)
    mips.jr_ra()  # jr_ra adds jr + delay slot nop = 2 instructions

    code = mips.emit()
    assert isinstance(code, bytes)
    assert len(code) == 5 * 4  # lui, addiu, nop, jr, nop = 20 bytes


def test_mips_snippet_invalid_reg():
    mips = AsmSnippet.mips()
    with pytest.raises(ValueError, match="Unknown MIPS register"):
        mips.lui("$invalid_reg", 0)


def test_mips_snippet_advanced():
    mips = (
        AsmSnippet.mips(">")
        .li("a0", 42)
        .lw("v0", "a0", 0)
        .sw("v0", "sp", 16)
        .addu("v1", "v0", "a0")
        .subu("t0", "v1", "a0")
        .sll("t1", "t0", 2)
        .srl("t2", "t1", 1)
        .ori("t3", "t2", 0xFF)
        .move("t4", "t3")
        .jr_ra()
    )
    code = mips.emit()
    assert len(code) == 11 * 4
