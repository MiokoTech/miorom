"""Tests for miorom.asm.m68k."""

import struct
import pytest

from miorom.asm.m68k import M68kInstruction, M68kDisassembler


@pytest.fixture
def disasm():
    return M68kDisassembler()


# ---------------------------------------------------------------------------
# Single-instruction decodes
# ---------------------------------------------------------------------------

def test_nop(disasm):
    data = bytes([0x4E, 0x71])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "NOP"
    assert instr.size == 2
    assert instr.is_branch is False
    assert instr.is_call is False
    assert instr.is_return is False
    assert instr.operands == ""


def test_rts(disasm):
    data = bytes([0x4E, 0x75])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "RTS"
    assert instr.size == 2
    assert instr.is_return is True
    assert instr.is_branch is False


def test_illegal(disasm):
    data = bytes([0x4A, 0xFC])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "ILLEGAL"
    assert instr.size == 2


def test_trap(disasm):
    # TRAP #0 = 0x4E40
    data = bytes([0x4E, 0x40])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "TRAP"
    assert "#0" in instr.operands
    assert instr.size == 2


def test_trap_n(disasm):
    # TRAP #5 = 0x4E45
    data = bytes([0x4E, 0x45])
    instr = disasm.disassemble_one(data, 0)
    assert "#5" in instr.operands


def test_moveq_positive(disasm):
    # MOVEQ #5, D0: 0x700A
    # top nibble=7, dn=0, bit8=0, imm8=0x0A
    data = bytes([0x70, 0x0A])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "MOVEQ"
    assert "D0" in instr.operands
    assert "#10" in instr.operands
    assert instr.size == 2


def test_moveq_negative(disasm):
    # MOVEQ #-1, D3: 0x76FF
    data = bytes([0x76, 0xFF])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "MOVEQ"
    assert "D3" in instr.operands
    assert "#-1" in instr.operands


def test_move_w_immediate(disasm):
    # MOVE.w #5, D0
    # opcode: 0x3039 would be from abs, use immediate form
    # MOVE.w #imm, D0 = 0x303C 0x0005
    data = bytes([0x30, 0x3C, 0x00, 0x05])
    instr = disasm.disassemble_one(data, 0)
    assert "MOVE" in instr.mnemonic
    assert ".w" in instr.mnemonic
    assert "5" in instr.operands or "#5" in instr.operands
    assert "D0" in instr.operands
    assert instr.size == 4


def test_move_l_immediate(disasm):
    # MOVE.l #0xDEADBEEF, D1 = 0x223C DEADBEEF
    data = bytes([0x22, 0x3C, 0xDE, 0xAD, 0xBE, 0xEF])
    instr = disasm.disassemble_one(data, 0)
    assert ".l" in instr.mnemonic
    assert instr.size == 6


def test_move_b_register(disasm):
    # MOVE.b D1, D0 = 0x1001
    data = bytes([0x10, 0x01])
    instr = disasm.disassemble_one(data, 0)
    assert "MOVE" in instr.mnemonic
    assert ".b" in instr.mnemonic
    assert "D1" in instr.operands
    assert "D0" in instr.operands
    assert instr.size == 2


def test_jsr_absolute_long(disasm):
    # JSR $00FF0000 = 0x4EB9 00FF0000
    data = bytes([0x4E, 0xB9, 0x00, 0xFF, 0x00, 0x00])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "JSR"
    assert instr.is_call is True
    assert instr.is_branch is False
    assert instr.branch_target == 0x00FF0000
    assert instr.size == 6


def test_jsr_address_register_indirect(disasm):
    # JSR (A0) = 0x4E90
    data = bytes([0x4E, 0x90])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "JSR"
    assert instr.is_call is True
    assert instr.size == 2


def test_jmp_absolute_long(disasm):
    # JMP $00001000 = 0x4EF9 00001000
    data = bytes([0x4E, 0xF9, 0x00, 0x00, 0x10, 0x00])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "JMP"
    assert instr.is_branch is True
    assert instr.is_call is False
    assert instr.branch_target == 0x00001000
    assert instr.size == 6


def test_bra_short(disasm):
    # BRA +4 (forward): 0x6004
    # disp8 = 4, target = (0+2) + 4 = 6
    data = bytes([0x60, 0x04])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "BRA"
    assert instr.is_branch is True
    assert instr.is_call is False
    assert instr.branch_target == 6
    assert instr.size == 2


def test_bra_word(disasm):
    # BRA with word displacement: 0x6000 0x0100 → target = 2 + 0x100 = 0x102
    data = bytes([0x60, 0x00, 0x01, 0x00])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "BRA"
    assert instr.branch_target == 0x102
    assert instr.size == 4


def test_bra_backward(disasm):
    # BRA -2 (self-loop): disp8 = 0xFE = -2 signed → target = (2-2) = 0
    data = bytes([0x60, 0xFE])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "BRA"
    assert instr.branch_target == 0


def test_bsr(disasm):
    # BSR +0x10: 0x6110 → is_call=True
    data = bytes([0x61, 0x10])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "BSR"
    assert instr.is_call is True
    assert instr.is_branch is False


def test_bne(disasm):
    # BNE +6: 0x6606
    data = bytes([0x66, 0x06])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "BNE"
    assert instr.is_branch is True


def test_lea_absolute(disasm):
    # LEA $00001234.l, A0 = 0x41F9 00001234
    data = bytes([0x41, 0xF9, 0x00, 0x00, 0x12, 0x34])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "LEA"
    assert "A0" in instr.operands
    assert instr.size == 6


def test_add_dn_dn(disasm):
    # ADD.w D1, D0 = 0xD041
    data = bytes([0xD0, 0x41])
    instr = disasm.disassemble_one(data, 0)
    assert "ADD" in instr.mnemonic
    assert ".w" in instr.mnemonic
    assert instr.size == 2


def test_sub_dn_dn(disasm):
    # SUB.w D1, D0 = 0x9041
    data = bytes([0x90, 0x41])
    instr = disasm.disassemble_one(data, 0)
    assert "SUB" in instr.mnemonic
    assert ".w" in instr.mnemonic


def test_cmp_dn_dn(disasm):
    # CMP.w D1, D0 = 0xB041
    data = bytes([0xB0, 0x41])
    instr = disasm.disassemble_one(data, 0)
    assert "CMP" in instr.mnemonic
    assert instr.size == 2


def test_dc_w_fallback(disasm):
    # Unknown opcode
    data = bytes([0xFF, 0xFF])
    instr = disasm.disassemble_one(data, 0)
    assert instr.mnemonic == "DC.W"
    assert instr.size == 2


# ---------------------------------------------------------------------------
# disassemble() multi-instruction
# ---------------------------------------------------------------------------

def test_disassemble_count(disasm):
    # NOP NOP NOP
    data = bytes([0x4E, 0x71] * 5)
    instrs = disasm.disassemble(data, start=0, count=3)
    assert len(instrs) == 3
    assert all(i.mnemonic == "NOP" for i in instrs)


def test_disassemble_end_offset(disasm):
    data = bytes([0x4E, 0x71] * 10)
    instrs = disasm.disassemble(data, start=0, end=6)
    assert len(instrs) == 3


def test_disassemble_sequence(disasm):
    # MOVEQ #10, D0 / NOP / RTS
    data = bytes([0x70, 0x0A, 0x4E, 0x71, 0x4E, 0x75])
    instrs = disasm.disassemble(data)
    assert len(instrs) == 3
    assert instrs[0].mnemonic == "MOVEQ"
    assert instrs[1].mnemonic == "NOP"
    assert instrs[2].mnemonic == "RTS"
    assert instrs[2].is_return is True


def test_disassemble_offsets_correct(disasm):
    data = bytes([0x4E, 0x71, 0x4E, 0x71, 0x4E, 0x75])
    instrs = disasm.disassemble(data, start=2)
    assert instrs[0].offset == 2
    assert instrs[1].offset == 4


def test_disassemble_mixed_sizes(disasm):
    # NOP (2) + JSR abs.l (6) + RTS (2)
    data = bytes([0x4E, 0x71, 0x4E, 0xB9, 0x00, 0x00, 0x10, 0x00, 0x4E, 0x75])
    instrs = disasm.disassemble(data)
    assert len(instrs) == 3
    assert instrs[0].size == 2
    assert instrs[1].size == 6
    assert instrs[2].size == 2


# ---------------------------------------------------------------------------
# format_listing
# ---------------------------------------------------------------------------

def test_format_listing_nop_rts(disasm):
    data = bytes([0x4E, 0x71, 0x4E, 0x75])
    instrs = disasm.disassemble(data)
    listing = disasm.format_listing(instrs)
    assert "4E71" in listing.upper() or "4e71" in listing.lower()
    assert "NOP" in listing
    assert "RTS" in listing


def test_format_listing_base_offset(disasm):
    data = bytes([0x4E, 0x71])
    instrs = disasm.disassemble(data)
    listing = disasm.format_listing(instrs, base_offset=0x100)
    assert "000100" in listing or "100" in listing


def test_format_listing_moveq(disasm):
    data = bytes([0x70, 0x0A, 0x4E, 0x75])
    instrs = disasm.disassemble(data)
    listing = disasm.format_listing(instrs)
    lines = listing.split("\n")
    assert len(lines) == 2
    assert "MOVEQ" in lines[0]
    assert "RTS" in lines[1]


# ---------------------------------------------------------------------------
# M68kInstruction properties
# ---------------------------------------------------------------------------

def test_instruction_text_property(disasm):
    data = bytes([0x4E, 0x71])
    instr = disasm.disassemble_one(data, 0)
    assert instr.text == "NOP"


def test_instruction_text_with_operands(disasm):
    data = bytes([0x70, 0x05])
    instr = disasm.disassemble_one(data, 0)
    assert "MOVEQ" in instr.text
    assert "#5" in instr.text


def test_bytes_field(disasm):
    data = bytes([0x4E, 0x71])
    instr = disasm.disassemble_one(data, 0)
    assert instr.bytes_ == bytes([0x4E, 0x71])


def test_miorom_result_to_dict(disasm):
    data = bytes([0x4E, 0x75])
    instr = disasm.disassemble_one(data, 0)
    d = instr.to_dict()
    assert d["mnemonic"] == "RTS"
    assert d["is_return"] is True
    assert d["size"] == 2
