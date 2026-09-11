import struct
import pytest
from miorom.asm.xref_engine import SymbolicXrefEngine, XRefDatabase, XRefRecord
from miorom.asm.xref import XRefType
from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction


def test_xref_engine_arm_literal_and_branches():
    # Build a small ARM snippet
    # 0x08000000: LDR R0, [PC, #8] -> points to 0x08000010 (val 0x08000040)
    # 0x08000004: BL 0x08000020
    # 0x08000008: B  0x08000030
    # 0x0800000C: NOP (0xE1A00000)
    # 0x08000010: .word 0x08000040 (literal pool target)
    ldr_r0_pc8 = 0xE59F0008     # LDR R0, [PC, #8]
    bl_target = 0xEB000005      # BL + (5+2)*4 = +28 bytes -> 0x08000004 + 8 + 20 = 0x08000020
    b_target = 0xEA000008       # B  + (8+2)*4 = +40 bytes -> 0x08000008 + 8 + 32 = 0x08000030
    nop = 0xE1A00000
    literal_val = 0x08000040

    code = struct.pack("<5I", ldr_r0_pc8, bl_target, b_target, nop, literal_val)
    base = 0x08000000

    db = SymbolicXrefEngine.analyze(code, base_address=base, arch="arm", endian="<")

    assert db.total_count >= 3
    # Check LDR literal pool
    ldr_refs = db.xrefs_to(0x08000040, xref_type=XRefType.LITERAL_POOL)
    assert len(ldr_refs) == 1
    assert ldr_refs[0].source_address == 0x08000000

    # Check BL call
    call_refs = db.xrefs_to(0x08000020, xref_type=XRefType.CALL)
    assert len(call_refs) == 1
    assert call_refs[0].source_address == 0x08000004

    # Check B branch
    branch_refs = db.xrefs_to(0x08000030, xref_type=XRefType.BRANCH)
    assert len(branch_refs) == 1
    assert branch_refs[0].source_address == 0x08000008


def test_xref_engine_thumb():
    # Thumb:
    # 0x08000000: LDR R2, [PC, #8] (0x4A02) -> PC = (0x08000000+4)&~2 = 0x08000004; + 8 = 0x0800000C
    # 0x08000002: B 0x08000010 (0xE005 -> imm 5 -> +10 bytes -> 0x08000002+4+10 = 0x08000010)
    # 0x08000004: BL 0x08000020 (0xF000, 0xF80C)
    # 0x08000008: NOP (0x46C0)
    # 0x0800000A: NOP (0x46C0)
    # 0x0800000C: .word 0x08009999 (pool)
    ldr_hw = 0x4A02
    b_hw = 0xE005
    bl_hi = 0xF000
    bl_lo = 0xF80C
    nop_hw = 0x46C0

    code = bytearray()
    code.extend(struct.pack("<H", ldr_hw))
    code.extend(struct.pack("<H", b_hw))
    code.extend(struct.pack("<H", bl_hi))
    code.extend(struct.pack("<H", bl_lo))
    code.extend(struct.pack("<H", nop_hw))
    code.extend(struct.pack("<H", nop_hw))
    code.extend(struct.pack("<I", 0x08009999))

    base = 0x08000000
    db = SymbolicXrefEngine.analyze(bytes(code), base_address=base, arch="thumb", endian="<")

    ldr_refs = db.xrefs_to(0x08009999, xref_type=XRefType.LITERAL_POOL)
    assert len(ldr_refs) == 1
    assert ldr_refs[0].source_address == 0x08000000

    b_refs = db.xrefs_to(0x08000010, xref_type=XRefType.BRANCH)
    assert len(b_refs) == 1
    assert b_refs[0].source_address == 0x08000002


def test_xref_engine_ppc():
    # PowerPC 32-bit big endian:
    # 0x80001000: LIS r3, 0x8020
    # 0x80001004: ADDI r3, r3, 0x3000 -> full 0x80203000
    # 0x80001008: BL 0x80002000 (opcode 18, LK=1)
    lis = 0x3C608020    # lis r3, 0x8020
    addi = 0x38633000   # addi r3, r3, 0x3000
    bl = 0x48000FF9     # bl 0x80001008 + 0xFF8 = 0x80002000

    code = struct.pack(">3I", lis, addi, bl)
    base = 0x80001000

    db = SymbolicXrefEngine.analyze(code, base_address=base, arch="ppc", endian=">")
    split_refs = db.xrefs_to(0x80203000, xref_type=XRefType.SPLIT_IMMEDIATE)
    assert len(split_refs) == 1
    assert split_refs[0].source_address == 0x80001000

    bl_refs = db.xrefs_to(0x80002000, xref_type=XRefType.CALL)
    assert len(bl_refs) == 1
    assert bl_refs[0].source_address == 0x80001008


def test_xref_engine_mips():
    # MIPS:
    # 0x00400000: LUI $v0, 0x0041 (0x3C020041)
    # 0x00400004: ORI $v0, $v0, 0x5000 (0x34425000) -> 0x00415000
    # 0x00400008: JAL 0x00401000 (target idx = 0x00401000 >> 2 = 0x100400 -> 0x0C100400)
    lui = 0x3C020041
    ori = 0x34425000
    jal = 0x0C100400

    code = struct.pack(">3I", lui, ori, jal)
    base = 0x00400000

    db = SymbolicXrefEngine.analyze(code, base_address=base, arch="mips", endian=">")
    split_refs = db.xrefs_to(0x00415000, xref_type=XRefType.SPLIT_IMMEDIATE)
    assert len(split_refs) == 1

    call_refs = db.xrefs_to(0x00401000, xref_type=XRefType.CALL)
    assert len(call_refs) == 1
    assert call_refs[0].source_address == 0x00400008


def test_xref_engine_snes_and_mos6502():
    # SNES:
    # 0x808000: JSR $9000 -> full 0x809000
    # 0x808003: JSL $82ABCD
    # 0x808007: BRA +$05 -> 0x80800E
    code = bytes([0x20, 0x00, 0x90, 0x22, 0xCD, 0xAB, 0x82, 0x80, 0x05])
    base = 0x808000

    db = SymbolicXrefEngine.analyze(code, base_address=base, arch="snes")
    assert len(db.xrefs_to(0x809000, xref_type=XRefType.CALL)) == 1
    assert len(db.xrefs_to(0x82ABCD, xref_type=XRefType.CALL)) == 1
    assert len(db.xrefs_to(0x80800E, xref_type=XRefType.BRANCH)) == 1


def test_xref_database_annotations():
    db = XRefDatabase()
    db.add_symbol(0x08000100, "main")
    db.add_symbol(0x08000200, "print_string")
    db.add_symbol(0x08000500, "str_Hello")

    # Add xref: main calls print_string
    db.add_xref(0x08000108, 0x08000200, XRefType.CALL, instruction_text="BL print_string")
    # Add xref: main loads str_Hello
    db.add_xref(0x08000104, 0x08000500, XRefType.LITERAL_POOL, instruction_text="LDR R0, [PC, #8]")

    assert db.callers_of(0x08000200) == [0x08000108]
    assert db.callees_of(0x08000100, function_length=32) == [0x08000200]

    # Test disassembly annotation
    ins1 = DisasmInstruction(
        address=0x08000200,
        raw_bytes=b"\x00\x00\x00\x00",
        mnemonic="PUSH",
        operands=["{r4, lr}"],
    )
    annotated = db.annotate_disassembly([ins1])
    text = "\n".join(annotated)
    assert "; Function: print_string" in text
    assert "; CODE XREF:" in text
