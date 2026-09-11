import struct
import pytest
from miorom.asm.reloc_calc import BranchRelocator, BranchRelocation


def test_reloc_6502_single_branch():
    reloc = BranchRelocator()
    # BEQ +4 from orig_pc 0x8000: target is 0x8006 (0x8000 + 2 + 4)
    inst = bytes([0xF0, 0x04])
    res = reloc.patch_single_branch(inst, orig_pc=0x8000, new_pc=0x9000, target_addr=0x9006, arch="6502")
    assert res.in_range is True
    assert res.new_bytes == bytes([0xF0, 0x04])
    assert res.mnemonic == "BEQ"

    # Moving to new_pc 0x9000, but target stays at 0x9020 -> disp = 0x9020 - 0x9002 = 0x1E = 30
    res2 = reloc.patch_single_branch(inst, orig_pc=0x8000, new_pc=0x9000, target_addr=0x9020, arch="6502")
    assert res2.in_range is True
    assert res2.new_bytes == bytes([0xF0, 30])
    assert res2.displacement == 30

    # Out of range test (disp > 127)
    res_overflow = reloc.patch_single_branch(inst, orig_pc=0x8000, new_pc=0x8000, target_addr=0x8500, arch="6502")
    assert res_overflow.in_range is False


def test_reloc_65816_brl():
    reloc = BranchRelocator()
    # BRL opcode 0x82, disp16: target = pc + 3 + disp
    inst = bytes([0x82, 0x10, 0x00])  # +16
    res = reloc.patch_single_branch(inst, orig_pc=0x1000, new_pc=0x5000, target_addr=0x5020, arch="65816")
    assert res.in_range is True
    assert res.mnemonic == "BRL"
    # target (0x5020) - (0x5000 + 3) = 29
    assert res.displacement == 29
    assert res.new_bytes == bytes([0x82]) + struct.pack("<h", 29)


def test_reloc_z80_jr():
    reloc = BranchRelocator()
    # JR opcode 0x18, disp: target = pc + 2 + disp
    inst = bytes([0x18, 0x05])
    res = reloc.patch_single_branch(inst, orig_pc=0x0100, new_pc=0x0200, target_addr=0x0210, arch="z80")
    assert res.in_range is True
    assert res.mnemonic == "JR"
    # target (0x0210) - (0x0200 + 2) = 14
    assert res.displacement == 14
    assert res.new_bytes == bytes([0x18, 14])


def test_reloc_m68k():
    reloc = BranchRelocator()
    # BRA.s (short, 8-bit): 0x60, disp
    inst_s = bytes([0x60, 0x06])
    res_s = reloc.patch_single_branch(inst_s, orig_pc=0x1000, new_pc=0x2000, target_addr=0x2020, arch="m68k")
    assert res_s.in_range is True
    assert res_s.mnemonic == "BRA.s"
    # target (0x2020) - (0x2000 + 2) = 30
    assert res_s.displacement == 30
    assert res_s.new_bytes == bytes([0x60, 30])

    # BSR.w (word, 16-bit): 0x61, 0x00, disp16
    inst_w = bytes([0x61, 0x00, 0x01, 0x00])
    res_w = reloc.patch_single_branch(inst_w, orig_pc=0x1000, new_pc=0x4000, target_addr=0x4200, arch="m68k")
    assert res_w.in_range is True
    assert res_w.mnemonic == "BSR.w"
    # target (0x4200) - (0x4000 + 2) = 0x1FE = 510
    assert res_w.displacement == 510
    assert res_w.new_bytes == bytes([0x61, 0x00]) + struct.pack(">h", 510)


def test_reloc_arm_thumb():
    reloc = BranchRelocator()
    # ARM B to target: delta = target - (pc + 8)
    # Target 0x08000100 from pc 0x08000000: delta = 0xF8 = 248 -> imm24 = 62
    arm_b = struct.pack("<I", 0xEA000000 | 62)
    res_arm = reloc.patch_single_branch(arm_b, orig_pc=0x08000000, new_pc=0x08001000, target_addr=0x08001200, arch="arm")
    assert res_arm.in_range is True
    assert res_arm.mnemonic == "B"

    # Thumb unconditional B: 0xE000 | imm11
    thumb_b = struct.pack("<H", 0xE000 | 10)
    res_thumb = reloc.patch_single_branch(thumb_b, orig_pc=0x08000000, new_pc=0x08000200, target_addr=0x08000230, arch="thumb")
    assert res_thumb.in_range is True
    assert res_thumb.mnemonic == "B"


def test_rebase_block_6502():
    reloc = BranchRelocator()
    # Construct a small 6502 block of 10 bytes:
    # 0x00: NOP (0xEA)
    # 0x01: BEQ +4 -> target 0x8000 + 1 + 2 + 4 = 0x8007 (internal, inside block [0x8000..0x800A))
    # 0x03: NOP (0xEA)
    # 0x04: BNE to external function at 0x9500
    # 0x06: NOP
    # 0x07: RTS (0x60)
    orig_base = 0x8000
    new_base = 0xC000
    # For BNE to 0x9500: target - (0x8004 + 2) = 0x9500 - 0x8006 = 0x14FA (too far for 8-bit)
    # Let external function be at 0xC030:
    # At new_base (0xC000), offset 0x04: pc = 0xC004. target 0xC030: disp = 0xC030 - 0xC006 = 42
    code = bytearray([
        0xEA,
        0xF0, 0x04,
        0xEA,
        0xD0, 0x20,
        0xEA,
        0x60,
        0xEA, 0xEA
    ])

    new_code, items = reloc.rebase_block(
        bytes(code),
        orig_base=orig_base,
        new_base=new_base,
        arch="6502",
        external_targets={0x8026: 0xC030},
    )
    assert len(items) == 2
    # Internal branch at offset 1: relative displacement remains identical
    assert items[0].offset == 1
    assert items[0].new_bytes == bytes([0xF0, 0x04])
    # External branch at offset 4: patched to new displacement
    assert items[1].offset == 4
    assert items[1].in_range is True
    assert new_code[4:6] == items[1].new_bytes
