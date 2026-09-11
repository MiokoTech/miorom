"""
Tests for miorom.asm.vwf_hook_engine
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Verifies end-to-end VWF width table synthesis, code cave allocation,
trampoline hook generation, and safety checks across ARM, Thumb, MIPS, SNES, and 6502.
"""

import struct
import pytest
from miorom.asm.vwf_hook_engine import (
    VWFHookEngine,
    VWFHookConfig,
    VWFDeploymentReport,
)
from miorom.errors import RelocationError
from miorom.text.vwf import GlyphWidthTable


@pytest.fixture
def sample_width_table() -> GlyphWidthTable:
    """Sample glyph width table for testing."""
    widths = [8] * 96
    # Make 'i', 'l', '.' narrow (3-4px)
    widths[ord("i") - 0x20] = 3
    widths[ord("l") - 0x20] = 3
    widths[ord(".") - 0x20] = 2
    # Make 'W', 'M' wide (11px)
    widths[ord("W") - 0x20] = 11
    widths[ord("M") - 0x20] = 11
    return GlyphWidthTable(widths, base_index=0x20)


def test_arm_vwf_deployment_auto_cave(sample_width_table):
    """Test ARM32 VWF deployment with automatic code cave discovery."""
    # Allocate a 16KB mock ROM buffer filled with 0xAA (non-free)
    rom = bytearray([0xAA] * 0x4000)

    # Hook site at ROM offset 0x1000 (RAM 0x08001000)
    hook_rom_offset = 0x1000
    hook_ram_addr = 0x08001000

    # Original instruction: ADD r1, r1, #8 (4 bytes: 0xE2811008)
    orig_instr = struct.pack("<I", 0xE2811008)
    rom[hook_rom_offset : hook_rom_offset + 4] = orig_instr

    # Create an unused code cave of 0x00 at ROM offset 0x2000 (size 512 bytes)
    cave_rom_offset = 0x2000
    rom[cave_rom_offset : cave_rom_offset + 512] = b"\x00" * 512

    config = VWFHookConfig(
        arch="arm",
        hook_rom_offset=hook_rom_offset,
        hook_ram_addr=hook_ram_addr,
        original_instr_bytes=orig_instr,
        width_table=sample_width_table,
        fallback_width=8,
        min_char_code=0x20,
        char_count=96,
        filler_byte=0x00,
    )

    report = VWFHookEngine.deploy(rom, config)

    assert report.arch == "arm"
    assert report.verified is True
    assert report.table_rom_offset == cave_rom_offset
    assert report.table_ram_addr == 0x08002000
    assert report.table_size == 96

    # Verify width table values in cave
    assert rom[cave_rom_offset + ord("i") - 0x20] == 3
    assert rom[cave_rom_offset + ord("W") - 0x20] == 11

    # Verify hook site now contains an ARM branch instruction (B)
    hook_instr = struct.unpack_from("<I", rom, hook_rom_offset)[0]
    # ARM B opcode prefix: 0xEAxxxxxx
    assert (hook_instr >> 24) == 0xEA

    # Verify displaced instruction exists in cave bytes
    assert orig_instr in report.hook_record.cave_bytes


def test_thumb_vwf_deployment(sample_width_table):
    """Test 16-bit Thumb VWF deployment on GBA."""
    rom = bytearray([0xFF] * 0x2000)

    hook_rom_offset = 0x0400
    hook_ram_addr = 0x08000400
    # Original 2-byte instruction: ADD r1, #8 (0x3108)
    orig_instr = struct.pack("<H", 0x3108)
    rom[hook_rom_offset : hook_rom_offset + 2] = orig_instr

    # Place a cave at 0x1000
    cave_rom_offset = 0x1000
    rom[cave_rom_offset : cave_rom_offset + 256] = b"\x00" * 256

    config = VWFHookConfig(
        arch="thumb",
        hook_rom_offset=hook_rom_offset,
        hook_ram_addr=hook_ram_addr,
        original_instr_bytes=orig_instr,
        width_table=sample_width_table,
        cave_rom_offset=cave_rom_offset,
        fallback_width=8,
    )

    report = VWFHookEngine.deploy(rom, config)

    assert report.arch == "thumb"
    assert report.table_rom_offset == cave_rom_offset
    # Verify Thumb unconditional branch at hook site: 0xE000 | offset
    hook_hw = struct.unpack_from("<H", rom, hook_rom_offset)[0]
    assert (hook_hw & 0xF800) == 0xE000


def test_mips_vwf_deployment(sample_width_table):
    """Test 32-bit MIPS VWF deployment with branch delay slot (PS1)."""
    rom = bytearray([0x00] * 0x3000)

    hook_rom_offset = 0x0800
    hook_ram_addr = 0x80010800
    # MIPS requires 8 bytes: ADDIU $a1, $a1, 8 (0x24A50008) + NOP (0x00000000)
    orig_instr = struct.pack("<2I", 0x24A50008, 0x00000000)
    rom[hook_rom_offset : hook_rom_offset + 8] = orig_instr

    cave_rom_offset = 0x1500
    rom[cave_rom_offset : cave_rom_offset + 512] = b"\x00" * 512

    config = VWFHookConfig(
        arch="mips",
        hook_rom_offset=hook_rom_offset,
        hook_ram_addr=hook_ram_addr,
        original_instr_bytes=orig_instr,
        width_table=sample_width_table,
        cave_rom_offset=cave_rom_offset,
        endian="<",
    )

    report = VWFHookEngine.deploy(rom, config)

    assert report.arch == "mips"
    # Verify MIPS jump instruction at hook site: opcode 0x08 (j)
    j_insn = struct.unpack_from("<I", rom, hook_rom_offset)[0]
    assert (j_insn >> 26) == 0x02  # J opcode in MIPS is 000010 (2)
    # Verify delay slot is NOP
    nop_insn = struct.unpack_from("<I", rom, hook_rom_offset + 4)[0]
    assert nop_insn == 0


def test_snes_vwf_deployment(sample_width_table):
    """Test 16-bit SNES W65C816 VWF deployment with 24-bit far table addressing."""
    rom = bytearray([0xEA] * 0x5000)

    hook_rom_offset = 0x1000
    hook_ram_addr = 0xC08000
    # SNES requires at least 4 bytes: LDA $2100; NOP
    orig_instr = b"\xAD\x00\x21\xEA"
    rom[hook_rom_offset : hook_rom_offset + 4] = orig_instr

    cave_rom_offset = 0x3000
    rom[cave_rom_offset : cave_rom_offset + 512] = b"\x00" * 512

    config = VWFHookConfig(
        arch="snes",
        hook_rom_offset=hook_rom_offset,
        hook_ram_addr=hook_ram_addr,
        original_instr_bytes=orig_instr,
        width_table=sample_width_table,
        cave_rom_offset=cave_rom_offset,
    )

    report = VWFHookEngine.deploy(rom, config)

    assert report.arch == "snes"
    # SNES hook byte should be JML (0x5C)
    assert rom[hook_rom_offset] == 0x5C


def test_6502_vwf_deployment(sample_width_table):
    """Test 8-bit MOS 6502 VWF deployment (NES)."""
    rom = bytearray([0xEA] * 0x2000)

    hook_rom_offset = 0x0500
    hook_ram_addr = 0x8500
    # 6502 requires at least 3 bytes for JMP (0x4C)
    orig_instr = b"\xEA\xEA\xEA"
    rom[hook_rom_offset : hook_rom_offset + 3] = orig_instr

    cave_rom_offset = 0x0C00
    rom[cave_rom_offset : cave_rom_offset + 256] = b"\x00" * 256

    config = VWFHookConfig(
        arch="6502",
        hook_rom_offset=hook_rom_offset,
        hook_ram_addr=hook_ram_addr,
        original_instr_bytes=orig_instr,
        width_table=sample_width_table,
        cave_rom_offset=cave_rom_offset,
    )

    report = VWFHookEngine.deploy(rom, config)

    assert report.arch == "6502"
    # 6502 hook byte should be JMP (0x4C)
    assert rom[hook_rom_offset] == 0x4C


def test_mismatch_guard_raises_error(sample_width_table):
    """Test safety check: raises RelocationError if hook site does not match expected bytes."""
    rom = bytearray([0x00] * 0x1000)
    rom[0x100:0x104] = b"\x11\x22\x33\x44"  # Actual bytes

    config = VWFHookConfig(
        arch="arm",
        hook_rom_offset=0x100,
        hook_ram_addr=0x08000100,
        original_instr_bytes=b"\xAA\xBB\xCC\xDD",  # Mismatched expected
        width_table=sample_width_table,
        cave_rom_offset=0x500,
    )

    with pytest.raises(RelocationError, match="Hook site byte mismatch"):
        VWFHookEngine.deploy(rom, config)

    # Verify ROM remains unmodified
    assert rom[0x100:0x104] == b"\x11\x22\x33\x44"


def test_simulate_mode_preserves_buffer(sample_width_table):
    """Test simulate mode: returns report without modifying the ROM buffer."""
    rom = bytearray([0xAA] * 0x2000)
    orig_instr = b"\x01\x02\x03\x04"
    rom[0x200:0x204] = orig_instr
    rom[0x800:0x900] = b"\x00" * 256

    rom_before = bytes(rom)

    config = VWFHookConfig(
        arch="arm",
        hook_rom_offset=0x200,
        hook_ram_addr=0x08000200,
        original_instr_bytes=orig_instr,
        width_table=sample_width_table,
        cave_rom_offset=0x800,
    )

    report = VWFHookEngine.deploy(rom, config, simulate=True)

    assert report.verified is True
    assert bytes(rom) == rom_before  # No modifications applied
