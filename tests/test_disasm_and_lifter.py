import struct
import pytest

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction
from miorom.asm.disambiguator import CodeDataDisambiguator, ByteClassification
from miorom.asm.slicer import DataFlowSlicer, JumpTable
from miorom.script.ir import IROp, IRVar
from miorom.script.lifter import BinaryLifter


def test_universal_disassembler_ppc():
    # Instructions:
    # 0x00: lis r3, 0x8025
    # 0x04: addi r3, r3, 0x1234
    # 0x08: bl 0x80005000
    # 0x0C: blr
    text = bytearray(16)
    struct.pack_into(">I", text, 0, 0x3C608025)
    struct.pack_into(">I", text, 4, 0x38631234)
    # bl to 0x80005000 from 0x80001008 -> diff = 0x00003FF8
    struct.pack_into(">I", text, 8, 0x48003FF9)
    struct.pack_into(">I", text, 12, 0x4E800020)

    instrs = UniversalDisassembler.disassemble(bytes(text), base_address=0x80001000, arch="ppc")
    assert len(instrs) == 4

    assert instrs[0].mnemonic == "lis"
    assert instrs[0].operands == ["r3", "0x8025"]

    assert instrs[1].mnemonic == "addi"
    assert instrs[1].operands == ["r3", "r3", "4660"]

    assert instrs[2].mnemonic == "bl"
    assert instrs[2].is_call is True
    assert instrs[2].target_address == 0x80005000

    assert instrs[3].mnemonic == "blr"
    assert instrs[3].is_return is True

    # Test listing formatting with symbols
    listing = UniversalDisassembler.format_listing(instrs, symbols={0x80005000: "OSReport"})
    assert "<OSReport>" in listing
    assert "blr" in listing


def test_universal_disassembler_arm():
    # 0x00: mov r0, #42
    # 0x04: bl 0x08002000 (from 0x08001004: diff = 0xFF4, imm = 0x3FD)
    # 0x08: bx lr
    text = bytearray(12)
    struct.pack_into("<I", text, 0, 0xE3A0002A)
    struct.pack_into("<I", text, 4, 0xEB0003FD)
    struct.pack_into("<I", text, 8, 0xE12FFF1E)

    instrs = UniversalDisassembler.disassemble(bytes(text), base_address=0x08001000, arch="arm")
    assert len(instrs) == 3
    assert instrs[0].mnemonic == "mov"
    assert instrs[1].mnemonic == "bl"
    assert instrs[1].target_address == 0x08002000
    assert instrs[2].mnemonic == "bx"
    assert instrs[2].is_return is True


def test_code_data_disambiguator():
    # Build synthetic ROM section:
    # 0x00..0x08: Code (li r3, 1; blr)
    # 0x08..0x10: Padding (0x00)
    # 0x10..0x18: Jump Table (pointers to 0x80000000, 0x80000004)
    # 0x18..0x24: String ("MioROM\x00")
    # 0x24..0x28: Rodata (0x12345678)
    rom = bytearray(40)
    struct.pack_into(">I", rom, 0x00, 0x38600001)  # li r3, 1
    struct.pack_into(">I", rom, 0x04, 0x4E800020)  # blr
    # Padding at 0x08..0x10 is 0x00 * 8
    # Jump Table at 0x10:
    struct.pack_into(">I", rom, 0x10, 0x80000000)  # Case 0 points to li r3, 1
    struct.pack_into(">I", rom, 0x14, 0x80000004)  # Case 1 points to blr
    # String at 0x18:
    rom[0x18:0x1F] = b"MioROM\x00"
    # Rodata at 0x20:
    struct.pack_into(">I", rom, 0x20, 0x12345678)

    report = CodeDataDisambiguator.analyze(
        data=bytes(rom),
        base_address=0x80000000,
        entry_points=[0x80000000],
        arch="ppc",
    )

    assert report.total_bytes == 40
    assert "CODE" in report.stats
    assert "PADDING" in report.stats
    assert "JUMP_TABLE" in report.stats
    assert "STRING" in report.stats

    # Check classifications
    classifications = {r.classification for r in report.ranges}
    assert ByteClassification.CODE in classifications
    assert ByteClassification.PADDING in classifications
    assert ByteClassification.JUMP_TABLE in classifications
    assert ByteClassification.STRING in classifications


def test_data_flow_slicer_jump_table():
    # PowerPC Switch-Case block:
    # 0x00: cmplwi r3, 2       ; 3 cases (0, 1, 2)
    # 0x04: bgt loc_default    ; conditional branch to default (0x80000020)
    # 0x08: lis r5, 0x8000     ; table base hi
    # 0x0C: addi r5, r5, 0x0018 ; table base lo (table at 0x80000018)
    # 0x10: mtctr r5           ; dummy move
    # 0x14: bctr               ; indirect jump!
    # 0x18: table entry 0 -> 0x80000030
    # 0x1C: table entry 1 -> 0x80000040
    # 0x20: table entry 2 -> 0x80000050
    # 0x24: default target
    code = bytearray(48)
    struct.pack_into(">I", code, 0x00, 0x28030002)  # cmplwi r3, 2
    # bgt to 0x80000024 -> diff = 0x20, bc opcode 16, bo=12, bi=1 (gt)
    struct.pack_into(">I", code, 0x04, 0x41810020)  # bc 12, 1, 0x20
    struct.pack_into(">I", code, 0x08, 0x3CA08000)  # lis r5, 0x8000
    struct.pack_into(">I", code, 0x0C, 0x38A50018)  # addi r5, r5, 0x18
    struct.pack_into(">I", code, 0x10, 0x7CA903A6)  # mtctr r5
    struct.pack_into(">I", code, 0x14, 0x4E800420)  # bctr

    # Table data at 0x18
    struct.pack_into(">I", code, 0x18, 0x80000030)
    struct.pack_into(">I", code, 0x1C, 0x80000040)
    struct.pack_into(">I", code, 0x20, 0x80000050)

    jts = DataFlowSlicer.find_jump_tables(bytes(code), base_address=0x80000000, arch="ppc")
    assert len(jts) == 1

    jt = jts[0]
    assert jt.jump_address == 0x80000014
    assert jt.table_address == 0x80000018
    assert jt.entry_count == 3
    assert jt.case_targets == [0x80000030, 0x80000040, 0x80000050]
    assert "Jump Table at 0x80000018" in jt.summary()


def test_binary_lifter_to_c():
    # PowerPC function:
    # 0x00: addi r3, r3, 10
    # 0x04: blr
    code = bytearray(8)
    struct.pack_into(">I", code, 0x00, 0x3863000A)  # addi r3, r3, 10
    struct.pack_into(">I", code, 0x04, 0x4E800020)  # blr

    ir_func = BinaryLifter.lift(bytes(code), base_address=0x80001000, arch="ppc", function_name="add_ten")
    assert ir_func.name == "add_ten"
    assert len(ir_func.blocks) == 1

    c_code = BinaryLifter.decompile_to_c(ir_func)
    assert "int add_ten()" in c_code
    assert "r3_1 = r3 + 0xA;" in c_code
    assert "return r3_1;" in c_code


def test_universal_disassembler_mips():
    # MIPS instructions (big-endian):
    # 0x00: addiu $a0, $zero, 42 -> 0x2404002A (li $a0, 42)
    # 0x04: lw $v0, 0($a0)       -> 0x8C820000
    # 0x08: jal 0x80002000       -> 0x0C000800
    # 0x0C: nop                  -> 0x00000000 (delay slot)
    # 0x10: jr $ra               -> 0x03E00008
    text = bytearray(20)
    struct.pack_into(">I", text, 0, 0x2404002A)
    struct.pack_into(">I", text, 4, 0x8C820000)
    struct.pack_into(">I", text, 8, 0x0C000800)
    struct.pack_into(">I", text, 12, 0x00000000)
    struct.pack_into(">I", text, 16, 0x03E00008)

    instrs = UniversalDisassembler.disassemble(bytes(text), base_address=0x80001000, arch="mips", endian=">")
    assert len(instrs) == 5
    assert instrs[0].mnemonic == "li"
    assert instrs[0].operands == ["$a0", "42"]
    assert instrs[1].mnemonic == "lw"
    assert instrs[1].operands == ["$v0", "0($a0)"]
    assert instrs[2].mnemonic == "jal"
    assert instrs[2].is_call is True
    assert instrs[2].target_address == 0x80002000
    assert instrs[3].mnemonic == "nop"
    assert instrs[4].mnemonic == "jr"
    assert instrs[4].is_return is True


def test_binary_lifter_mips_to_c():
    # MIPS function:
    # 0x00: addiu $v0, $a0, 10 -> 0x2482000A
    # 0x04: jr $ra              -> 0x03E00008
    code = bytearray(8)
    struct.pack_into(">I", code, 0, 0x2482000A)
    struct.pack_into(">I", code, 4, 0x03E00008)

    ir_func = BinaryLifter.lift(bytes(code), base_address=0x80001000, arch="mips", endian=">", function_name="mips_add_ten")
    assert ir_func.name == "mips_add_ten"
    c_code = BinaryLifter.decompile_to_c(ir_func)
    assert "int mips_add_ten()" in c_code
    assert "$v0_1 = $a0 + 0xA;" in c_code
    assert "return $v0_1;" in c_code
