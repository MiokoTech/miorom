"""
tests.test_platforms_gba_rom
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Game Boy Advance Unified ROM Engine (GBARom, GBARomHandler).
Tests header complement check calculation and repair, regional territory mapping,
ROM capacity expansion and trimming, save-type auto-detection and SRAM patching,
LZ77/Sappy asset discovery, and RomManager auto-dispatch.
"""

import json
import os
import tempfile

import pytest

from miorom.errors import ParseError
from miorom.platforms.gba.rom import (
    GBARom,
    create_synthetic_gba_rom,
    fix_gba_checksum,
    resolve_gba_region,
)
from miorom.rom.manager import RomManager


def test_gba_header_fields_and_complement_checksum():
    """Verifies GBA header fields, logo validation, and complement check repair."""
    rom_bytes = create_synthetic_gba_rom(
        title="POKEMON EM",
        game_code="BPEE",
        maker_code="01",
        version=1,
    )
    rom = GBARom(rom_bytes)

    assert rom.title == "POKEMON EM"
    assert rom.game_code == "BPEE"
    assert rom.maker_code == "01"
    assert rom.version == 1
    assert rom.region == "USA"
    assert rom.is_logo_valid() is True
    assert rom.is_header_checksum_valid() is True

    # Mutate title and verify checksum invalidation
    rom.title = "MODDED EM"
    assert rom.is_header_checksum_valid() is False

    # Fix checksum and verify validity
    rom.fix_header_checksum()
    assert rom.is_header_checksum_valid() is True

    # Helper function fix_gba_checksum
    corrupted_data = bytearray(rom.to_bytes())
    corrupted_data[0xBD] = 0x00
    fixed_bytes = fix_gba_checksum(bytes(corrupted_data))
    assert GBARom(fixed_bytes).is_header_checksum_valid() is True


def test_gba_entry_point_calculation():
    """Verifies ARM execution entry point decoded from the 32-bit branch at 0x00."""
    rom_bytes = create_synthetic_gba_rom()
    rom = GBARom(rom_bytes)

    # b 0x080000C0 -> target is 0x080000C0
    assert rom.entry_point == 0x080000C0


def test_gba_regional_resolver_all_territories():
    """Verifies Nintendo GBA 4th character game code territory mapping."""
    assert resolve_gba_region("AGBE") == "USA"
    assert resolve_gba_region("AGBP") == "EUR"
    assert resolve_gba_region("AGBJ") == "JPN"
    assert resolve_gba_region("AGBD") == "GER"
    assert resolve_gba_region("AGBF") == "FRA"
    assert resolve_gba_region("AGBI") == "ITA"
    assert resolve_gba_region("AGBS") == "SPA"
    assert resolve_gba_region("AGBU") == "AUS"
    assert resolve_gba_region("AGBK") == "KOR"
    assert resolve_gba_region("AGBX") == "GLOBAL"
    assert resolve_gba_region("ABC") == "UNKNOWN"


def test_gba_rom_expansion_and_trimming():
    """Verifies clean ROM expansion to 4MB/8MB/16MB/32MB boundaries and trimming."""
    rom_bytes = create_synthetic_gba_rom(size=0x40000)  # 256 KB
    rom = GBARom(rom_bytes)
    assert len(rom.data) == 0x40000

    # Expand to 8 MB
    rom.expand(8)
    assert len(rom.data) == 8 * 1024 * 1024
    assert rom.data[-1] == 0xFF
    assert rom.is_header_checksum_valid() is True

    # Expand to 16 MB
    rom.expand(16)
    assert len(rom.data) == 16 * 1024 * 1024

    # Expand to 32 MB
    rom.expand(32)
    assert len(rom.data) == 32 * 1024 * 1024

    # Expand to maximum 64 MB
    rom.expand(64)
    assert len(rom.data) == 64 * 1024 * 1024

    # Invalid sizes
    with pytest.raises(ValueError, match="Invalid GBA ROM target size"):
        rom.expand(128)
    with pytest.raises(ValueError, match="Cannot shrink ROM"):
        rom.expand(16)

    # Trim back to power-of-2 size
    rom.trim(min_size=0x40000)
    assert len(rom.data) == 0x40000
    assert rom.is_header_checksum_valid() is True


def test_gba_save_detection_and_sram_patching():
    """Verifies save type detection and automatic SRAM patching for flashcarts."""
    rom_bytes = create_synthetic_gba_rom(save_type="FLASH1M")
    rom = GBARom(rom_bytes)

    assert "FLASH (1Mbit" in rom.detect_save_type()

    # Patch to standard SRAM
    modified = rom.patch_save_to_sram()
    assert modified is True
    assert "SRAM" in rom.detect_save_type()

    # Second patch should not modify
    assert rom.patch_save_to_sram() is False


def test_gba_lz10_stream_discovery():
    """Verifies embedded Nintendo LZ77 Type 0x10 graphic stream discovery."""
    rom_bytes = create_synthetic_gba_rom(with_lz10=True)
    rom = GBARom(rom_bytes)

    streams = rom.find_lz10_streams()
    assert len(streams) >= 1
    offset, decomp_size = streams[0]
    assert offset >= 0xC0
    assert decomp_size > 0


def test_gba_sappy_song_table_discovery():
    """Verifies Nintendo Sappy (Music Player 2000) song table scanning."""
    rom_bytes = create_synthetic_gba_rom(with_sappy=True)
    rom = GBARom(rom_bytes)

    tables = rom.find_sappy_songs(min_consecutive=3)
    assert len(tables) >= 1
    assert tables[0] >= 0xC0


def test_gba_rom_handler_manager_integration():
    """Verifies RomManager auto-detection, metadata extraction, unpacking, and repacking."""
    manager = RomManager()
    assert "gba" in manager.handlers

    rom_bytes = create_synthetic_gba_rom(
        title="ZELDA MC",
        game_code="BZMP",
        maker_code="01",
        version=0,
    )

    # Auto-detection
    assert manager.detect_format(rom_bytes) == "gba"

    # Metadata extraction
    meta = manager.get_metadata(rom_bytes)
    assert meta["platform"] == "gba"
    assert meta["title"] == "ZELDA MC"
    assert meta["game_code"] == "BZMP"
    assert meta["region"] == "EUR"
    assert meta["header_checksum_valid"] is True
    assert meta["logo_valid"] is True

    # Unpack and Repack
    with tempfile.TemporaryDirectory() as tmp_dir:
        unpack_dir = os.path.join(tmp_dir, "unpacked")
        repacked_path = os.path.join(tmp_dir, "repacked.gba")

        manager.unpack(rom_bytes, unpack_dir)
        assert os.path.isfile(os.path.join(unpack_dir, "rom.bin"))
        assert os.path.isfile(os.path.join(unpack_dir, "header.json"))

        # Modify header.json
        header_file = os.path.join(unpack_dir, "header.json")
        with open(header_file, "r", encoding="utf-8") as f:
            hdr_data = json.load(f)
        hdr_data["title"] = "ZELDA TRANSL"
        with open(header_file, "w", encoding="utf-8") as f:
            json.dump(hdr_data, f, indent=2)

        # Repack
        manager.repack(unpack_dir, repacked_path)
        assert os.path.isfile(repacked_path)

        # Verify repacked ROM
        with open(repacked_path, "rb") as f:
            repacked_rom = GBARom.from_file(repacked_path)
            assert repacked_rom.title == "ZELDA TRANSL"
            assert repacked_rom.is_header_checksum_valid() is True


def test_gba_error_handling():
    """Verifies that undersized ROM payloads raise ParseError."""
    with pytest.raises(ParseError, match="Data too small"):
        GBARom(b"\x00" * 64)


def test_gba_logo_repair():
    """Verifies that fix_logo restores corrupted Nintendo logo at 0x04..0x9F."""
    rom_bytes = create_synthetic_gba_rom()
    rom = GBARom(rom_bytes)
    assert rom.is_logo_valid() is True

    # Corrupt logo
    rom.data[0x04:0x20] = b"\x00" * 28
    assert rom.is_logo_valid() is False

    # Repair logo
    rom.fix_logo()
    assert rom.is_logo_valid() is True


def test_gba_rtc_detection():
    """Verifies Real-Time Clock (RTC) signature discovery in GBA ROMs."""
    rom_no_rtc = GBARom(create_synthetic_gba_rom(with_rtc=False))
    assert rom_no_rtc.has_rtc is False
    assert "RTC" not in rom_no_rtc.detect_save_type()

    rom_with_rtc = GBARom(create_synthetic_gba_rom(save_type="FLASH1M", with_rtc=True))
    assert rom_with_rtc.has_rtc is True
    assert "FLASH (1Mbit / 128KB) + RTC" == rom_with_rtc.detect_save_type()


def test_gba_pointer_operations_and_relinking():
    """Verifies 32-bit GBA memory pointer conversion, scanning, and relinking."""
    rom = GBARom(create_synthetic_gba_rom())

    # Address translation
    offset = 0x1400
    ptr_ws0 = rom.offset_to_ptr(offset, waitstate=0)
    ptr_ws1 = rom.offset_to_ptr(offset, waitstate=1)
    assert ptr_ws0 == 0x08001400
    assert ptr_ws1 == 0x0A001400

    assert rom.ptr_to_offset(ptr_ws0) == offset
    assert rom.ptr_to_offset(ptr_ws1) == offset
    assert rom.ptr_to_offset(0x02000000) is None  # EWRAM outside ROM

    # Pointer scanning and relinking
    target_old = 0x2000
    target_new = 0x3500

    # Plant pointers at 0x200 (WS0) and 0x208 (WS1)
    rom.data[0x200:0x204] = (0x08000000 | target_old).to_bytes(4, "little")
    rom.data[0x208:0x20C] = (0x0A000000 | target_old).to_bytes(4, "little")

    found = rom.find_pointers(target_old)
    assert 0x200 in found
    assert 0x208 in found

    # Relink pointers
    relinked = rom.relink_pointers(target_old, target_new)
    assert relinked == 2

    # Verify old pointers are gone and new pointers are present with preserved base
    assert rom.find_pointers(target_old) == []
    assert rom.find_pointers(target_new) == [0x200, 0x208]
    assert int.from_bytes(rom.data[0x200:0x204], "little") == 0x08000000 | target_new
    assert int.from_bytes(rom.data[0x208:0x20C], "little") == 0x0A000000 | target_new


def test_gba_swi_scanner_integration():
    """Verifies SWI scanning directly on GBARom instance."""
    rom = GBARom(create_synthetic_gba_rom())

    # Embed two Thumb SWI instructions at offset 0x200
    # 0xDF11 = SWI 0x11 (LZ77UnCompWram), 0xDF01 = SWI 0x01 (RegisterRamReset)
    rom.data[0x200:0x204] = b"\x11\xDF\x01\xDF"

    calls = rom.scan_swi_calls(thumb_mode=True, start_offset=0x200, end_offset=0x204)
    assert len(calls) == 2
    assert calls[0]["name"] == "LZ77UnCompWram"
    assert calls[0]["swi_number"] == 0x11
    assert calls[1]["name"] == "RegisterRamReset"
    assert calls[1]["swi_number"] == 0x01



