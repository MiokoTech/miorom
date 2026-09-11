"""
Unit tests for MOS 6502 and W65C816 disassembly, prologue scanning, and SSA IR lifting.
"""

import struct
import pytest

from miorom.asm.disasm import UniversalDisassembler
from miorom.asm.prologue_scanner import FunctionPrologueScanner
from miorom.script.ir import IROp
from miorom.script.lifter import BinaryLifter


def test_6502_disassembler_basic():
    # 0x00: lda #$42     -> 0xA9, 0x42
    # 0x02: sta $0200    -> 0x8D, 0x00, 0x02
    # 0x05: jsr $C000    -> 0x20, 0x00, 0xC0
    # 0x08: rts          -> 0x60
    code = bytes([0xA9, 0x42, 0x8D, 0x00, 0x02, 0x20, 0x00, 0xC0, 0x60])
    instrs = UniversalDisassembler.disassemble(code, base_address=0x8000, arch="6502")

    assert len(instrs) == 4
    assert instrs[0].mnemonic == "lda"
    assert instrs[0].operands == ["#$42"]
    assert len(instrs[0].raw_bytes) == 2

    assert instrs[1].mnemonic == "sta"
    assert instrs[1].operands == ["$0200"]
    assert len(instrs[1].raw_bytes) == 3

    assert instrs[2].mnemonic == "jsr"
    assert instrs[2].is_call is True
    assert instrs[2].target_address == 0xC000
    assert len(instrs[2].raw_bytes) == 3

    assert instrs[3].mnemonic == "rts"
    assert instrs[3].is_return is True
    assert len(instrs[3].raw_bytes) == 1


def test_6502_branch_addressing():
    # 0x8000: bne $8006 (disp = +4) -> 0xD0, 0x04 (target = 0x8000 + 2 + 4 = 0x8006)
    # 0x8002: beq $8000 (disp = -4) -> 0xF0, 0xFC (target = 0x8002 + 2 - 4 = 0x8000)
    code = bytes([0xD0, 0x04, 0xF0, 0xFC])
    instrs = UniversalDisassembler.disassemble(code, base_address=0x8000, arch="nes")

    assert len(instrs) == 2
    assert instrs[0].mnemonic == "bne"
    assert instrs[0].is_conditional is True
    assert instrs[0].target_address == 0x8006

    assert instrs[1].mnemonic == "beq"
    assert instrs[1].is_conditional is True
    assert instrs[1].target_address == 0x8000


def test_65816_dynamic_m16_x16_state_tracking():
    # 0x00: rep #$20      -> 0xC2, 0x20 (M=0 -> 16-bit A)
    # 0x02: lda #$1234    -> 0xA9, 0x34, 0x12 (3 bytes!)
    # 0x05: sep #$20      -> 0xE2, 0x20 (M=1 -> 8-bit A)
    # 0x07: lda #$56      -> 0xA9, 0x56 (2 bytes!)
    # 0x09: jsl $808000   -> 0x22, 0x00, 0x80, 0x80 (4 bytes!)
    # 0x0D: rtl           -> 0x6B (1 byte!)
    code = bytes([0xC2, 0x20, 0xA9, 0x34, 0x12, 0xE2, 0x20, 0xA9, 0x56, 0x22, 0x00, 0x80, 0x80, 0x6B])
    instrs = UniversalDisassembler.disassemble(code, base_address=0x800000, arch="snes")

    assert len(instrs) == 6
    assert instrs[0].mnemonic == "rep"
    assert instrs[0].operands == ["#$20"]

    assert instrs[1].mnemonic == "lda"
    assert instrs[1].operands == ["#$1234"]
    assert len(instrs[1].raw_bytes) == 3

    assert instrs[2].mnemonic == "sep"
    assert instrs[2].operands == ["#$20"]

    assert instrs[3].mnemonic == "lda"
    assert instrs[3].operands == ["#$56"]
    assert len(instrs[3].raw_bytes) == 2

    assert instrs[4].mnemonic == "jsl"
    assert instrs[4].target_address == 0x808000
    assert len(instrs[4].raw_bytes) == 4
    assert instrs[4].is_call is True

    assert instrs[5].mnemonic == "rtl"
    assert instrs[5].is_return is True
    assert len(instrs[5].raw_bytes) == 1


def test_65816_advanced_modes():
    # Long addressing:
    # lda $123456     -> 0xAF, 0x56, 0x34, 0x12 (4 bytes)
    # Direct page indirect long:
    # lda [$10]       -> 0xA7, 0x10 (2 bytes)
    # Stack relative:
    # lda $02,s       -> 0xA3, 0x02 (2 bytes)
    # Block move:
    # mvn $01, $02    -> 0x54, 0x02, 0x01 (3 bytes)
    code = bytes([0xAF, 0x56, 0x34, 0x12, 0xA7, 0x10, 0xA3, 0x02, 0x54, 0x02, 0x01])
    instrs = UniversalDisassembler.disassemble(code, base_address=0x800000, arch="65816")

    assert len(instrs) == 4
    assert instrs[0].mnemonic == "lda"
    assert instrs[0].operands == ["$123456"]

    assert instrs[1].mnemonic == "lda"
    assert instrs[1].operands == ["[$10]"]

    assert instrs[2].mnemonic == "lda"
    assert instrs[2].operands == ["$02,s"]

    assert instrs[3].mnemonic == "mvn"
    assert instrs[3].operands == ["$01", "$02"]


def test_prologue_scanner_6502_and_65816():
    # SNES function prologue: php; rep #$20; pha
    snes_blob = bytearray(0x40)
    snes_blob[0x04] = 0x08  # php
    snes_blob[0x05] = 0xC2  # rep
    snes_blob[0x06] = 0x20  # #$20
    snes_blob[0x07] = 0x48  # pha

    snes_funcs = FunctionPrologueScanner.scan(bytes(snes_blob), base_address=0x800000, arch="snes")
    assert len(snes_funcs) >= 1
    assert snes_funcs[0].address == 0x800004
    assert snes_funcs[0].architecture == "65816"

    # NES function prologue: php; pha
    nes_blob = bytearray(0x40)
    nes_blob[0x10] = 0x08  # php
    nes_blob[0x11] = 0x48  # pha

    nes_funcs = FunctionPrologueScanner.scan(bytes(nes_blob), base_address=0x8000, arch="nes")
    assert len(nes_funcs) == 1
    assert nes_funcs[0].address == 0x8010
    assert nes_funcs[0].architecture == "6502"


def test_lifter_6502_to_c():
    # lda #$10 (0xA9, 0x10)
    # adc #$05 (0x69, 0x05)
    # sta $0300 (0x8D, 0x00, 0x03)
    # rts (0x60)
    code = bytes([0xA9, 0x10, 0x69, 0x05, 0x8D, 0x00, 0x03, 0x60])
    ir = BinaryLifter.lift(code, base_address=0x8000, arch="6502", function_name="calc_sum")

    ops = [i.op for i in list(ir.blocks.values())[0].instructions]
    assert IROp.ASSIGN in ops
    assert IROp.ADD in ops
    assert IROp.STORE in ops
    assert IROp.RETURN in ops

    c_code = BinaryLifter.decompile_to_c(ir)
    assert "int calc_sum()" in c_code
    assert "return" in c_code
