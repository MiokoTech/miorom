"""
Unit tests for M68kSnippet and Mos6502Snippet micro-assembly builders.
"""

import pytest
from miorom.asm.snippet import AsmSnippet, M68kSnippet, Mos6502Snippet
from miorom.asm.disasm import UniversalDisassembler


def test_m68k_snippet_basic():
    s = AsmSnippet.m68k()
    s.nop()
    s.moveq("d0", 5)
    s.lea(0x00FF0000, "a0")
    s.jsr(0x00200000)
    s.rts()

    raw = s.emit()
    assert len(raw) == 2 + 2 + 6 + 6 + 2  # 18 bytes

    # Verify first instruction is NOP (0x4E71)
    assert raw[:2] == b"\x4E\x71"
    # MOVEQ #5, D0 (0x7005)
    assert raw[2:4] == b"\x70\x05"
    # LEA $FF0000, A0 (0x41F9, 0x00FF, 0x0000)
    assert raw[4:10] == b"\x41\xF9\x00\xFF\x00\x00"
    # JSR $200000 (0x4EB9, 0x0020, 0x0000)
    assert raw[10:16] == b"\x4E\xB9\x00\x20\x00\x00"
    # RTS (0x4E75)
    assert raw[16:18] == b"\x4E\x75"

    # Disassemble first instruction using UniversalDisassembler
    instr = UniversalDisassembler.disassemble(raw[:2], address=0x1000, arch="m68k")
    assert instr[0].mnemonic.lower() == "nop"


def test_m68k_snippet_moves_and_branches():
    s = AsmSnippet.m68k()
    s.move_imm("d1", 0x1234, size="w")
    s.move_reg("d1", "d2", size="w")
    s.bra(0x10)
    s.bsr(0x20)
    raw = s.emit()
    assert len(raw) > 0


def test_mos6502_snippet():
    s = AsmSnippet.mos6502()
    s.sei()
    s.lda_imm(0x42)
    s.sta_abs(0x2000)
    s.ldx_zp(0x10)
    s.stx_abs(0x2001)
    s.jsr(0x8000)
    s.rts()

    raw = s.emit()
    # SEI (0x78)
    assert raw[0] == 0x78
    # LDA #$42 (0xA9, 0x42)
    assert raw[1:3] == b"\xA9\x42"
    # STA $2000 (0x8D, 0x00, 0x20)
    assert raw[3:6] == b"\x8D\x00\x20"
    # LDX $10 (0xA6, 0x10)
    assert raw[6:8] == b"\xA6\x10"
    # STX $2001 (0x8E, 0x01, 0x20)
    assert raw[8:11] == b"\x8E\x01\x20"
    # JSR $8000 (0x20, 0x00, 0x80)
    assert raw[11:14] == b"\x20\x00\x80"
    # RTS (0x60)
    assert raw[14] == 0x60

    # Disassemble using UniversalDisassembler
    instr = UniversalDisassembler.disassemble(raw[1:3], address=0x8000, arch="6502")
    assert instr[0].mnemonic.lower() == "lda"
