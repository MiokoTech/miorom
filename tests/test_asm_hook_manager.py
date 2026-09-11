"""Tests for miorom.asm.hook_manager."""

import struct
import pytest

from miorom.asm.hook_manager import (
    CodeCave,
    HookRecord,
    CodeCaveManager,
    ArmHookBuilder,
    HookManager,
)


# ---------------------------------------------------------------------------
# CodeCaveManager.scan
# ---------------------------------------------------------------------------

def test_scan_finds_single_cave():
    rom = bytearray(b"\xAB\xCD" + b"\x00" * 64 + b"\xEF")
    mgr = CodeCaveManager(fill_byte=0x00)
    caves = mgr.scan(rom, min_size=32)
    assert len(caves) == 1
    assert caves[0].start == 2
    assert caves[0].size == 64
    assert caves[0].used == 0
    assert caves[0].free == 64


def test_scan_finds_multiple_caves():
    rom = bytearray(b"\xFF" * 4 + b"\x00" * 48 + b"\xFF" * 4 + b"\x00" * 48)
    mgr = CodeCaveManager(fill_byte=0x00)
    caves = mgr.scan(rom, min_size=32)
    assert len(caves) == 2
    assert caves[0].start == 4
    assert caves[1].start == 56


def test_scan_ignores_small_runs():
    rom = bytearray(b"\xAA" + b"\x00" * 10 + b"\xBB" + b"\x00" * 64)
    mgr = CodeCaveManager()
    caves = mgr.scan(rom, min_size=32)
    assert len(caves) == 1
    assert caves[0].size == 64


def test_scan_respects_search_bounds():
    rom = bytearray(b"\x00" * 128)
    mgr = CodeCaveManager()
    caves = mgr.scan(rom, min_size=32, search_start=10, search_end=50)
    assert len(caves) == 1
    assert caves[0].start == 10
    assert caves[0].size == 40


def test_scan_ff_fill_byte():
    rom = bytearray(b"\x00" * 8 + b"\xFF" * 64 + b"\x00" * 8)
    mgr = CodeCaveManager(fill_byte=0xFF)
    caves = mgr.scan(rom, min_size=32)
    assert len(caves) == 1
    assert caves[0].start == 8


# ---------------------------------------------------------------------------
# CodeCaveManager.register / allocate / write_to_cave
# ---------------------------------------------------------------------------

def test_register_and_allocate():
    mgr = CodeCaveManager()
    cave = mgr.register(0x1000, 128, label="test_cave")
    assert cave.free == 128
    assert cave.label == "test_cave"

    found_cave, within_offset = mgr.allocate(64)
    assert found_cave is cave
    assert within_offset == 0


def test_allocate_picks_first_fitting_cave():
    mgr = CodeCaveManager()
    small = mgr.register(0x0100, 16)
    large = mgr.register(0x0200, 64)

    cave, offset = mgr.allocate(32)
    assert cave is large
    assert offset == 0


def test_allocate_raises_when_no_space():
    mgr = CodeCaveManager()
    mgr.register(0x0100, 8)
    with pytest.raises(ValueError):
        mgr.allocate(32)


def test_write_to_cave_advances_used():
    buf = bytearray(256)
    mgr = CodeCaveManager()
    cave = mgr.register(0x10, 64)
    payload = b"\x01\x02\x03\x04"
    abs_off = mgr.write_to_cave(buf, cave, payload)
    assert abs_off == 0x10
    assert buf[0x10:0x14] == payload
    assert cave.used == 4
    assert cave.free == 60


def test_write_to_cave_overflow_raises():
    buf = bytearray(256)
    mgr = CodeCaveManager()
    cave = mgr.register(0x10, 4)
    with pytest.raises(ValueError):
        mgr.write_to_cave(buf, cave, b"\x00" * 8)


# ---------------------------------------------------------------------------
# ArmHookBuilder
# ---------------------------------------------------------------------------

def test_build_arm_bl_forward():
    from_addr = 0x08000000
    to_addr = 0x08000100
    bl = ArmHookBuilder.build_arm_bl(from_addr, to_addr)
    assert len(bl) == 4
    word = struct.unpack("<I", bl)[0]
    # Top byte should be 0xEB (BL, cond=AL)
    assert (word >> 24) == 0xEB
    # Decode offset: (to - from - 8) >> 2 = (0x100 - 8) >> 2 = 0xF8 >> 2 = 0x3E
    offset24 = word & 0xFFFFFF
    assert offset24 == 0x3E


def test_build_arm_bl_backward():
    from_addr = 0x08000100
    to_addr = 0x08000000
    bl = ArmHookBuilder.build_arm_bl(from_addr, to_addr)
    word = struct.unpack("<I", bl)[0]
    assert (word >> 24) == 0xEB
    offset24 = word & 0xFFFFFF
    # Sign-extend 24-bit
    if offset24 & 0x800000:
        offset24 -= 0x1000000
    recovered = from_addr + 8 + (offset24 << 2)
    assert recovered == to_addr


def test_build_arm_b():
    from_addr = 0x08001000
    to_addr = 0x08001050
    b = ArmHookBuilder.build_arm_b(from_addr, to_addr)
    word = struct.unpack("<I", b)[0]
    assert (word >> 24) == 0xEA


def test_build_thumb_bl_encoding():
    from_addr = 0x08000000
    to_addr = 0x08001000
    bl = ArmHookBuilder.build_thumb_bl(from_addr, to_addr)
    assert len(bl) == 4
    hw1, hw2 = struct.unpack("<HH", bl)
    assert (hw1 >> 11) == 0x1E   # F prefix (bits 15:11 = 11110)
    assert (hw2 >> 11) == 0x1F   # F8 prefix (bits 15:11 = 11111)


def test_build_thumb_bl_roundtrip():
    from_addr = 0x08000000
    to_addr = 0x08001000
    bl = ArmHookBuilder.build_thumb_bl(from_addr, to_addr)
    hw1, hw2 = struct.unpack("<HH", bl)
    hi11 = hw1 & 0x7FF
    lo11 = hw2 & 0x7FF
    offset22 = (hi11 << 11) | lo11
    # Sign-extend 22 bits
    if offset22 & (1 << 21):
        offset22 -= (1 << 22)
    recovered = from_addr + 4 + (offset22 << 1)
    assert recovered == to_addr


def test_build_thumb_b():
    from_addr = 0x08000000
    to_addr = 0x08000020
    b = ArmHookBuilder.build_thumb_b(from_addr, to_addr)
    assert len(b) == 2
    hw = struct.unpack("<H", b)[0]
    assert (hw >> 11) == 0x1C   # 0b11100


# ---------------------------------------------------------------------------
# HookManager.install_arm_hook
# ---------------------------------------------------------------------------

def test_install_arm_hook_bl():
    buf = bytearray(b"\xDE\xAD\xBE\xEF" + b"\x00" * 256)
    hook_rom = 0
    hook_ram = 0x08000000
    cave_rom = 100
    cave_ram = 0x08000064
    cave_code = b"\x01\x10\xA0\xE3"  # MOV R1, #1

    mgr = HookManager()
    record = mgr.install_arm_hook(
        buf=buf,
        hook_rom_offset=hook_rom,
        hook_ram_addr=hook_ram,
        cave_ram_addr=cave_ram,
        cave_rom_offset=cave_rom,
        cave_code=cave_code,
        mode="bl",
    )

    assert isinstance(record, HookRecord)
    assert record.arch == "arm"
    assert record.hook_size == 4
    assert record.original_bytes == b"\xDE\xAD\xBE\xEF"

    hook_word = struct.unpack("<I", buf[0:4])[0]
    assert (hook_word >> 24) == 0xEB  # BL

    assert len(mgr.hooks) == 1


def test_install_arm_hook_b_mode():
    buf = bytearray(b"\x00" * 256)
    mgr = HookManager()
    record = mgr.install_arm_hook(
        buf=buf,
        hook_rom_offset=0,
        hook_ram_addr=0x08000000,
        cave_ram_addr=0x08000080,
        cave_rom_offset=128,
        cave_code=b"\x00\x00\xA0\xE3",
        mode="b",
    )
    hook_word = struct.unpack("<I", buf[0:4])[0]
    assert (hook_word >> 24) == 0xEA  # B


def test_install_arm_hook_cave_has_return():
    buf = bytearray(b"\x00" * 512)
    hook_rom = 0
    hook_ram = 0x08001000
    cave_rom = 256
    cave_ram = 0x08001100
    cave_code = b"\x01\x00\xA0\xE3"  # MOV R0, #1

    mgr = HookManager()
    mgr.install_arm_hook(
        buf=buf,
        hook_rom_offset=hook_rom,
        hook_ram_addr=hook_ram,
        cave_ram_addr=cave_ram,
        cave_rom_offset=cave_rom,
        cave_code=cave_code,
    )
    # cave: cave_code (4 bytes) + return B (4 bytes)
    cave_return_word = struct.unpack("<I", buf[cave_rom + 4 : cave_rom + 8])[0]
    assert (cave_return_word >> 24) == 0xEA  # B instruction


def test_install_thumb_hook():
    buf = bytearray(b"\x11\x22\x33\x44" + b"\x00" * 256)
    mgr = HookManager()
    record = mgr.install_thumb_hook(
        buf=buf,
        hook_rom_offset=0,
        hook_ram_addr=0x08000000,
        cave_ram_addr=0x08001000,
        cave_rom_offset=64,
        cave_code=b"\x01\x20",  # MOVS R0, #1
        mode="bl",
    )
    assert record.arch == "thumb"
    assert record.original_bytes == b"\x11\x22\x33\x44"
    hw1, hw2 = struct.unpack("<HH", buf[0:4])
    assert (hw1 >> 11) == 0x1E  # Thumb BL prefix
    assert (hw2 >> 11) == 0x1F  # Thumb BL suffix


def test_hook_record_original_bytes_preserved():
    original = b"\xAA\xBB\xCC\xDD"
    buf = bytearray(original + b"\x00" * 256)
    mgr = HookManager()
    record = mgr.install_arm_hook(
        buf=buf,
        hook_rom_offset=0,
        hook_ram_addr=0x08002000,
        cave_ram_addr=0x08003000,
        cave_rom_offset=64,
        cave_code=b"\x00\x00\xA0\xE3",
    )
    assert record.original_bytes == original


def test_caves_property():
    mgr = CodeCaveManager()
    mgr.register(0, 64, "a")
    mgr.register(128, 64, "b")
    caves = mgr.caves
    assert len(caves) == 2


def test_hooks_property():
    buf = bytearray(b"\x00" * 512)
    mgr = HookManager()
    for i in range(3):
        mgr.install_arm_hook(
            buf=buf,
            hook_rom_offset=i * 4,
            hook_ram_addr=0x08000000 + i * 4,
            cave_ram_addr=0x08001000 + i * 8,
            cave_rom_offset=200 + i * 8,
            cave_code=b"\x00\x00\xA0\xE3",
        )
    assert len(mgr.hooks) == 3
