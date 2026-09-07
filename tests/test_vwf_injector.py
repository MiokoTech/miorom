import struct
import pytest
from miorom.text.vwf_injector import (
    DynamicVWFInjector,
    VWFHookReport,
)
from miorom.text.vwf import GlyphWidthTable


def test_build_width_table_binary():
    widths = {
        ord("i"): 3,
        ord("l"): 3,
        ord("W"): 11,
        ord("M"): 11,
        ord("A"): 8,
    }
    table_bytes = DynamicVWFInjector.build_width_table_binary(
        glyph_widths=widths,
        default_width=7,
        start_char=0x20,
        count=96,
    )
    assert len(table_bytes) == 96
    # 'i' is ASCII 0x69. Offset in table = 0x69 - 0x20 = 0x49 = 73
    assert table_bytes[ord("i") - 0x20] == 3
    assert table_bytes[ord("W") - 0x20] == 11
    # Unspecified char 'X' uses default_width (7)
    assert table_bytes[ord("X") - 0x20] == 7


def test_generate_arm_vwf_hook():
    table_vaddr = 0x02100000
    hook_code = DynamicVWFInjector.generate_arm_vwf_hook(
        table_vaddr=table_vaddr,
        fallback_width=12,
        endian="<",
    )
    assert len(hook_code) == 40  # 10 words * 4 bytes = 40 bytes
    # Verify CMP r0, #0x20 (0xE3500020) at offset 0
    first_word = struct.unpack_from("<I", hook_code, 0)[0]
    assert first_word == 0xE3500020
    # Verify table_vaddr literal at offset 36
    last_word = struct.unpack_from("<I", hook_code, 36)[0]
    assert last_word == table_vaddr


def test_generate_mips_vwf_hook():
    table_vaddr = 0x80050000
    hook_code = DynamicVWFInjector.generate_mips_vwf_hook(
        table_vaddr=table_vaddr,
        fallback_width=10,
        endian=">",
    )
    assert len(hook_code) == 24  # 6 instructions * 4 bytes = 24 bytes
    # Check lui $t0, 0x8005 (0x3C088005)
    first_insn = struct.unpack_from(">I", hook_code, 0)[0]
    assert first_insn == 0x3C088005


def test_generate_snes_vwf_hook():
    hook = DynamicVWFInjector.generate_snes_vwf_hook(
        table_bank=0x07,
        table_offset=0x9000,
    )
    assert len(hook) == 16
    # Check PHP (0x08)
    assert hook[0] == 0x08
    # Check LDA.L table, X opcode (0xBF)
    assert hook[9] == 0xBF
    assert hook[10] == 0x00  # low byte of 0x9000
    assert hook[11] == 0x90  # high byte of 0x9000
    assert hook[12] == 0x07  # bank
    # Check RTL (0x6B)
    assert hook[-1] == 0x6B
