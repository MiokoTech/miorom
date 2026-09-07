import struct
import pytest
from miorom.core.integrity import RomIntegrityManager, IntegrityReport
from miorom.platforms.gba.rom import GBARom
from miorom.platforms.gb.rom import GBRom
from miorom.platforms.snes.rom import SNESRom
from miorom.platforms.md.rom import fix_md_checksum


def test_integrity_nds():
    # Construct minimal dummy NDS header (0x200 bytes)
    header = bytearray(0x200)
    header[0x00:0x0C] = b"TESTGAME\x00\x00\x00\x00"
    header[0x0C:0x10] = b"NTRJ"
    header[0x10:0x12] = b"01"
    header[0x12] = 0  # unit code NDS

    # Verify invalid CRC
    rep_initial = RomIntegrityManager.verify(bytes(header), platform="NDS")
    assert rep_initial.platform == "NDS"
    assert rep_initial.is_valid is False

    # Fix
    fixed_bytes, rep_fix = RomIntegrityManager.fix(bytes(header), platform="NDS")
    assert rep_fix.repaired is True
    assert rep_fix.is_valid is True

    # Verify fixed
    rep_verified = RomIntegrityManager.verify(fixed_bytes, platform="NDS")
    assert rep_verified.is_valid is True


def test_integrity_gba():
    # Construct minimal dummy GBA header (192 bytes)
    header = bytearray(0xC0)
    header[0:4] = b"\x2E\x00\x00\xEA"
    header[0x04:0xA0] = GBARom.NINTENDO_LOGO
    header[0xA0:0xAC] = b"TEST_GBA\x00\x00\x00\x00"
    header[0xAC:0xB0] = b"BPEE"
    header[0xB0:0xB2] = b"01"
    header[0xB2] = 0x96
    header[0xBD] = 0x00  # Corrupted checksum

    # Auto-detect and verify
    assert RomIntegrityManager.auto_detect_platform(bytes(header)) == "GBA"
    rep_initial = RomIntegrityManager.verify(bytes(header))
    assert rep_initial.is_valid is False

    # Fix
    fixed_bytes, rep_fix = RomIntegrityManager.fix(bytes(header))
    assert rep_fix.repaired is True
    assert rep_fix.is_valid is True

    # Verify fixed
    rep_verified = RomIntegrityManager.verify(fixed_bytes)
    assert rep_verified.is_valid is True


def test_integrity_gb():
    # Construct minimal dummy GB header (32KB)
    data = bytearray(32768)
    data[0x104:0x134] = GBRom.NINTENDO_LOGO
    data[0x134:0x143] = b"TEST_GB\x00\x00\x00\x00\x00\x00\x00\x00"
    data[0x147] = 0x00
    data[0x148] = 0x00

    # Auto-detect and verify
    assert RomIntegrityManager.auto_detect_platform(bytes(data)) == "GB"
    rep_initial = RomIntegrityManager.verify(bytes(data))
    assert rep_initial.is_valid is False

    # Fix
    fixed_bytes, rep_fix = RomIntegrityManager.fix(bytes(data))
    assert rep_fix.repaired is True
    assert rep_fix.is_valid is True

    # Verify fixed
    rep_verified = RomIntegrityManager.verify(fixed_bytes)
    assert rep_verified.is_valid is True


def test_integrity_n64():
    # Construct minimal dummy N64 ROM (0x101000 bytes)
    rom_buf = bytearray(0x101000)
    rom_buf[0:4] = b"\x80\x37\x12\x40"
    struct.pack_into(">IIIII", rom_buf, 0x04, 0x0F, 0x80000400, 0x1444, 0, 0)
    rom_buf[0x20:0x34] = b"TEST N64 ROM        "

    # Auto-detect and verify
    assert RomIntegrityManager.auto_detect_platform(bytes(rom_buf)) == "N64"
    rep_initial = RomIntegrityManager.verify(bytes(rom_buf))
    assert rep_initial.is_valid is False

    # Fix
    fixed_bytes, rep_fix = RomIntegrityManager.fix(bytes(rom_buf))
    assert rep_fix.repaired is True
    assert rep_fix.is_valid is True

    # Verify fixed
    rep_verified = RomIntegrityManager.verify(fixed_bytes)
    assert rep_verified.is_valid is True


def test_integrity_md():
    # Construct minimal dummy Mega Drive ROM (1024 bytes)
    rom_data = bytearray(1024)
    rom_data[0x100:0x104] = b"SEGA"
    rom_data[0x120:0x150] = b"TEST MEGADRIVE GAME             "
    # Payload from 0x200 that makes checksum non-zero
    rom_data[0x200:0x210] = b"GAME_PAYLOAD_123"

    # Auto-detect and verify
    assert RomIntegrityManager.auto_detect_platform(bytes(rom_data)) == "MD"
    rep_initial = RomIntegrityManager.verify(bytes(rom_data))
    assert rep_initial.is_valid is False

    # Fix
    fixed_bytes, rep_fix = RomIntegrityManager.fix(bytes(rom_data))
    assert rep_fix.repaired is True
    assert rep_fix.is_valid is True

    # Verify fixed
    rep_verified = RomIntegrityManager.verify(fixed_bytes)
    assert rep_verified.is_valid is True


def test_integrity_snes():
    # Construct minimal dummy SNES ROM (32KB LoROM)
    rom_data = bytearray(32768)
    header_offset = 0x7FC0
    rom_data[header_offset : header_offset + 21] = b"TEST SNES ROM        "
    rom_data[header_offset + 0x15] = 0x20  # LoROM FastROM
    rom_data[header_offset + 0x16] = 0x00  # ROM only
    rom_data[header_offset + 0x17] = 0x08  # 256KB
    rom_data[header_offset + 0x18] = 0x00  # RAM size
    rom_data[header_offset + 0x19] = 0x01  # North America
    rom_data[header_offset + 0x1A] = 0x33  # Extended header

    assert RomIntegrityManager.auto_detect_platform(bytes(rom_data)) == "SNES"
    rep_initial = RomIntegrityManager.verify(bytes(rom_data))
    assert rep_initial.is_valid is False

    # Fix
    fixed_bytes, rep_fix = RomIntegrityManager.fix(bytes(rom_data))
    assert rep_fix.repaired is True
    assert rep_fix.is_valid is True

    # Verify fixed
    rep_verified = RomIntegrityManager.verify(fixed_bytes)
    assert rep_verified.is_valid is True


def test_integrity_unknown():
    garbage = b"\x00" * 32
    assert RomIntegrityManager.auto_detect_platform(garbage) is None
    rep = RomIntegrityManager.verify(garbage)
    assert rep.platform == "UNKNOWN"
    assert rep.is_valid is False

    fixed, rep2 = RomIntegrityManager.fix(garbage)
    assert fixed == garbage
    assert rep2.repaired is False
