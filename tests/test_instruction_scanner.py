import struct
import pytest

from miorom.asm.instruction_scanner import (
    CodePointer,
    PPCInstructionScanner,
    MIPSInstructionScanner,
    ARMLiteralPointer,
    ARMMovPairPointer,
    ARMInstructionScanner,
    UniversalInstructionScanner,
)


def test_ppc_instruction_scanner():
    # lis r3, 0x8024 (opcode 15) then addi r3, r3, 0x51A0 (opcode 14)
    insn_lis = (15 << 26) | (3 << 21) | 0x8024
    insn_addi = (14 << 26) | (3 << 21) | (3 << 16) | 0x51A0

    buf = bytearray(struct.pack(">II", insn_lis, insn_addi))
    ptrs = PPCInstructionScanner.find_split_pointers(bytes(buf), min_target=0x80000000)
    assert len(ptrs) == 1
    assert ptrs[0].target_address == 0x802451A0
    assert ptrs[0].reg == 3

    # Patch pointer
    ptrs[0].patch(buf, 0x80281234, endian=">")
    ptrs_patched = PPCInstructionScanner.find_split_pointers(bytes(buf), min_target=0x80000000)
    assert len(ptrs_patched) == 1
    assert ptrs_patched[0].target_address == 0x80281234


def test_mips_instruction_scanner():
    # lui $v0, 0x8005 then addiu $v0, $v0, 0x1234
    mips_lui = (15 << 26) | (2 << 16) | 0x8005
    mips_addiu = (9 << 26) | (2 << 21) | (2 << 16) | 0x1234

    buf = bytearray(struct.pack(">II", mips_lui, mips_addiu))
    ptrs = MIPSInstructionScanner.find_split_pointers(bytes(buf), min_target=0x80000000)
    assert len(ptrs) == 1
    assert ptrs[0].target_address == 0x80051234
    assert ptrs[0].reg == 2

    # Patch pointer
    ptrs[0].patch(buf, 0x80109876, endian=">")
    ptrs_patched = MIPSInstructionScanner.find_split_pointers(bytes(buf), min_target=0x80000000)
    assert len(ptrs_patched) == 1
    assert ptrs_patched[0].target_address == 0x80109876


def test_arm32_literal_pool_scanner():
    # Construct 32 bytes of ARM32 code with literal pool
    # Offset 0x00: LDR R0, [PC, #8] -> PC is 0x08, target pool is 0x08 + 8 = 0x10 (16)
    # 0xE59F0008: cond=AL, P=1, U=1, B=0, W=0, L=1, Rn=15, Rd=0, imm12=8
    insn_ldr = 0xE59F0008
    buf = bytearray(32)
    struct.pack_into("<I", buf, 0x00, insn_ldr)
    # Literal pool entry at offset 0x10: points to 0x0205DC00
    struct.pack_into("<I", buf, 0x10, 0x0205DC00)

    base = 0x02000000
    ptrs = ARMInstructionScanner.find_literal_pointers(
        bytes(buf),
        min_target=0x02000000,
        max_target=0x02400000,
        base_address=base,
        mode="arm",
    )
    assert len(ptrs) == 1
    p = ptrs[0]
    assert p.insn_offset == 0x00
    assert p.insn_address == 0x02000000
    assert p.pool_offset == 0x10
    assert p.pool_address == 0x02000010
    assert p.target_address == 0x0205DC00
    assert p.reg == 0
    assert p.mode == "arm"
    assert p.target_hex == "0x0205DC00"

    # Test in-place repoint
    p.patch(buf, 0x0208ABCD)
    assert struct.unpack_from("<I", buf, 0x10)[0] == 0x0208ABCD

    ptrs_patched = ARMInstructionScanner.find_literal_pointers(
        bytes(buf),
        min_target=0x02000000,
        max_target=0x02400000,
        base_address=base,
        mode="arm",
    )
    assert len(ptrs_patched) == 1
    assert ptrs_patched[0].target_address == 0x0208ABCD


def test_thumb_literal_pool_scanner():
    # 32 bytes of Thumb code
    # Offset 0x00: LDR R2, [PC, #imm8]
    # In Thumb: PC = (insn_addr + 4) & ~3. If insn is at 0, PC = 4.
    # imm8 = 2 -> pool_offset = 4 + (2 * 4) = 12 (0x0C).
    # Insn encoding: 0x4800 | (2 << 8) | 2 = 0x4A02
    buf = bytearray(32)
    struct.pack_into("<H", buf, 0x00, 0x4A02)
    # Literal pool entry at offset 0x0C
    struct.pack_into("<I", buf, 0x0C, 0x02071234)

    base = 0x02000000
    ptrs = ARMInstructionScanner.find_literal_pointers(
        bytes(buf),
        min_target=0x02000000,
        max_target=0x02400000,
        base_address=base,
        mode="thumb",
    )
    assert len(ptrs) == 1
    p = ptrs[0]
    assert p.insn_offset == 0x00
    assert p.pool_offset == 0x0C
    assert p.target_address == 0x02071234
    assert p.reg == 2
    assert p.mode == "thumb"

    # Patch Thumb literal pool entry
    p.patch(buf, 0x02099999)
    assert struct.unpack_from("<I", buf, 0x0C)[0] == 0x02099999


def test_armv7_movw_movt_pair_scanner():
    # movw r3, #0x5678 (imm4=5, imm12=0x678)
    # 0xE3000000 | (5 << 16) | (3 << 12) | 0x678 = 0xE3053678
    insn_movw = 0xE3053678
    # movt r3, #0x0204 (imm4=0, imm12=0x204)
    # 0xE3400000 | (0 << 16) | (3 << 12) | 0x204 = 0xE3403204
    insn_movt = 0xE3403204

    buf = bytearray(struct.pack("<II", insn_movw, insn_movt))
    base = 0x02000000
    pairs = ARMInstructionScanner.find_mov_pairs(
        bytes(buf),
        min_target=0x02000000,
        max_target=0x02400000,
        base_address=base,
    )
    assert len(pairs) == 1
    p = pairs[0]
    assert p.target_address == 0x02045678
    assert p.reg == 3
    assert p.movw_offset == 0
    assert p.movt_offset == 4

    # Patch pair to 0x0211ABCD
    p.patch(buf, 0x0211ABCD)
    pairs_patched = ARMInstructionScanner.find_mov_pairs(
        bytes(buf),
        min_target=0x02000000,
        max_target=0x02400000,
        base_address=base,
    )
    assert len(pairs_patched) == 1
    assert pairs_patched[0].target_address == 0x0211ABCD


def test_arm_find_xrefs():
    # Buffer with ARM32 literal pool load referencing 0x0205BA80
    buf = bytearray(32)
    # LDR R4, [PC, #8] -> at offset 0x04, PC is 0x0C, pool offset = 0x0C + 8 = 0x14
    struct.pack_into("<I", buf, 0x04, 0xE59F4008)
    struct.pack_into("<I", buf, 0x14, 0x0205BA80)

    xrefs = ARMInstructionScanner.find_xrefs(
        bytes(buf),
        target_address=0x0205BA80,
        base_address=0x02000000,
    )
    assert len(xrefs) == 1
    assert xrefs[0] == 0x02000004


def test_universal_instruction_scanner():
    # Test ARM dispatch
    buf_arm = bytearray(32)
    struct.pack_into("<I", buf_arm, 0x00, 0xE59F0008)  # LDR R0, [PC, #8]
    struct.pack_into("<I", buf_arm, 0x10, 0x0205DC00)

    ptrs_arm = UniversalInstructionScanner.find_code_pointers(
        bytes(buf_arm),
        arch="arm",
        min_target=0x02000000,
        max_target=0x02400000,
        base_address=0x02000000,
    )
    assert len(ptrs_arm) == 1
    assert ptrs_arm[0].target_address == 0x0205DC00

    # Test PPC dispatch
    insn_lis = (15 << 26) | (3 << 21) | 0x8024
    insn_addi = (14 << 26) | (3 << 21) | (3 << 16) | 0x51A0
    buf_ppc = bytearray(struct.pack(">II", insn_lis, insn_addi))

    ptrs_ppc = UniversalInstructionScanner.find_code_pointers(
        bytes(buf_ppc),
        arch="ppc",
        min_target=0x80000000,
        max_target=0x81000000,
        base_address=0x80000000,
    )
    assert len(ptrs_ppc) == 1
    assert ptrs_ppc[0].target_address == 0x802451A0

