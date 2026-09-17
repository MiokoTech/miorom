"""
tests.test_platforms_psx_rom
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for PlayStation 1 Unified ROM, Disc & Package Engine (PSXRom, PSXRomHandler).
Tests Mode 1 ISO (2048 b/s) and Mode 2 Form 1 raw CD-ROM BIN (2352 b/s) disc images,
EDC checksum verification, SYSTEM.CNF parsing, region resolution, executable modification,
multi-media asset discovery (TIM, VAG, STR), and RomManager auto-dispatch.
"""

import os
import struct
import tempfile

import pytest

from miorom.audio.vag import VAGHeader
from miorom.core.schema import pack_into
from miorom.errors import ParseError
from miorom.platforms.cdrom.disc import (
    SYNC_PATTERN,
    calculate_cdrom_edc,
)
from miorom.platforms.psx.exe import PSXExe
from miorom.platforms.psx.rom import (
    PSXFormat,
    PSXRom,
    create_synthetic_psx_bin,
    create_synthetic_psx_iso,
    resolve_psx_region,
)
from miorom.platforms.psx.tim import TIMImage
from miorom.rom.manager import RomManager


def test_psx_iso_detection_and_metadata():
    """Verifies format auto-detection, SYSTEM.CNF parsing, and metadata extraction on Mode 1 ISO."""
    iso_bytes = create_synthetic_psx_iso(
        game_id="SLUS-00001",
        title="CRASH BANDICOOT",
        with_main_exe=True,
        with_tim=True,
    )
    rom = PSXRom.from_bytes(iso_bytes)

    assert rom.format == PSXFormat.ISO
    assert rom.original_format == PSXFormat.ISO
    assert rom.sector_size == 2048
    assert rom.title == "CRASH BANDICOOT"
    assert rom.game_id == "SLUS-00001"
    assert rom.region == "USA"
    assert rom.boot_path == "SLUS_000.01"
    assert rom.system_cnf.get("TCB") == "4"
    assert rom.system_cnf.get("EVENT") == "16"
    assert rom.system_cnf.get("STACK") == "801FFFF0"


def test_psx_bin_detection_and_metadata():
    """Verifies Mode 2 Form 1 (2352 b/s) raw CD-ROM BIN auto-detection and metadata extraction."""
    bin_bytes = create_synthetic_psx_bin(
        game_id="SLES-00123",
        title="EUROPEAN PS1 GAME",
        with_main_exe=True,
        with_tim=True,
    )
    rom = PSXRom(bin_bytes)

    assert rom.format == PSXFormat.BIN
    assert rom.original_format == PSXFormat.BIN
    assert rom.sector_size == 2352
    assert rom.game_id == "SLES-00123"
    assert rom.region == "EUR"
    assert rom.boot_path == "SLES_001.23"


def test_psx_region_resolver_all_territories():
    """Verifies Sony PlayStation 1 product code mapping across all world territories."""
    assert resolve_psx_region("SLUS-00001") == "USA"
    assert resolve_psx_region("SCUS-94101") == "USA"
    assert resolve_psx_region("SLES-00123") == "EUR"
    assert resolve_psx_region("SCES-00001") == "EUR"
    assert resolve_psx_region("SLPS-00001") == "JPN"
    assert resolve_psx_region("SLPM-86001") == "JPN"
    assert resolve_psx_region("SCPS-10001") == "JPN"
    assert resolve_psx_region("SLAJ-25001") == "ASIA"
    assert resolve_psx_region("UNKNOWN-999") == "UNKNOWN"


def test_psx_filesystem_operations_and_replace():
    """Verifies file listing, extraction, and in-place replacement with reallocation."""
    iso_bytes = create_synthetic_psx_iso(
        game_id="SCUS-94228",
        title="SPYRO THE DRAGON",
    )
    rom = PSXRom.from_bytes(iso_bytes)

    files = rom.list_files()
    assert any("SYSTEM.CNF" in f for f in files)
    assert any("SCUS_942.28" in f for f in files)
    assert any("ICON.TIM" in f for f in files)

    # Read SYSTEM.CNF
    cnf_data = rom.get_file("SYSTEM.CNF")
    assert b"BOOT" in cnf_data

    # Replace file with smaller content
    updated_cnf = b"BOOT = cdrom:\\SCUS_942.28;1\r\nTCB = 8\r\n"
    rom.replace_file("SYSTEM.CNF", updated_cnf)
    assert rom.get_file("SYSTEM.CNF") == updated_cnf

    # Replace file with larger content requiring sector reallocation (>2048 bytes)
    big_payload = b"PATCHED_LARGE_DATA_BLOCK_" * 150  # ~3750 bytes (> 1 sector)
    rom.replace_file("SYSTEM.CNF", big_payload)
    assert rom.get_file("SYSTEM.CNF") == big_payload

    # Re-parse serialized ISO to ensure virtual filesystem is structurally valid
    exported_iso = rom.to_bytes(PSXFormat.ISO)
    reloaded_rom = PSXRom.from_bytes(exported_iso)
    assert reloaded_rom.get_file("SYSTEM.CNF") == big_payload


def test_psx_main_exe_inspection_and_modification():
    """Verifies primary boot executable parsing via PSXExe and roundtrip modification."""
    iso_bytes = create_synthetic_psx_iso(
        game_id="SLPS-00001",
        title="RIDGE RACER JPN",
    )
    rom = PSXRom.from_bytes(iso_bytes)

    exe = rom.get_main_exe()
    assert exe is not None
    assert isinstance(exe, PSXExe)
    assert exe.pc == 0x80010000
    assert exe.gp == 0x80080000
    assert exe.t_addr == 0x80010000
    assert exe.t_size == 2048
    assert exe.sp_base == 0x801FFFF0

    # Modify executable PC and payload
    exe.pc = 0x80020000
    rom.replace_main_exe(exe)

    # Re-fetch and verify modification persisted
    modified_exe = rom.get_main_exe()
    assert modified_exe is not None
    assert modified_exe.pc == 0x80020000


def test_psx_media_asset_discovery():
    """Verifies multi-media asset discovery: TIM textures, VAG audio, and STR videos."""
    # Synthesize ISO containing TIM, VAG audio, and STR video
    iso_bytes = create_synthetic_psx_iso(
        game_id="SLUS-00001",
        title="MEDIA TEST GAME",
        with_tim=True,
        with_str=True,
    )
    rom = PSXRom.from_bytes(iso_bytes)

    # 1. Discover TIM textures
    tim_list = rom.find_textures()
    assert len(tim_list) >= 1
    fpath, offset, tim_obj = tim_list[0]
    assert "ICON.TIM" in fpath
    assert offset == 0
    assert isinstance(tim_obj, TIMImage)
    assert tim_obj.bpp == 16

    # 2. Inject dummy VAG audio file and scan
    vag_header_bytes = bytearray(48)
    vag_header_bytes[:4] = b"VAGp"
    pack_into(">IIII", vag_header_bytes, 4, 3, 0, 32, 22050)
    vag_dummy_data = bytes(vag_header_bytes) + b"\x00" * 32
    rom.replace_file("SYSTEM.CNF", vag_dummy_data)

    vag_list = rom.find_audio()
    assert len(vag_list) >= 1
    vag_path, vag_off, vag_hdr = vag_list[0]
    assert isinstance(vag_hdr, VAGHeader)
    assert vag_hdr.sample_rate == 22050

    # 3. Discover STR cutscene movie
    video_list = rom.find_videos()
    assert len(video_list) >= 1
    v_path, v_off, demuxer = video_list[0]
    assert "INTRO.STR" in v_path
    assert len(demuxer.sectors) >= 1


def test_psx_bin_mode2_form1_edc_integrity():
    """Verifies bit-exact 2352-byte Mode 2 Form 1 raw CD-ROM BIN packaging with EDC checksums."""
    iso_bytes = create_synthetic_psx_iso(
        game_id="SLUS-00001",
        title="EDC INTEGRITY TEST",
    )
    rom = PSXRom.from_bytes(iso_bytes)
    bin_bytes = rom.to_bytes(PSXFormat.BIN)

    num_sectors = len(bin_bytes) // 2352
    assert len(bin_bytes) % 2352 == 0
    assert num_sectors >= 17

    for sec_idx in range(num_sectors):
        sec = bin_bytes[sec_idx * 2352 : (sec_idx + 1) * 2352]
        # Sync pattern
        assert sec[:12] == SYNC_PATTERN
        # Mode 2
        assert sec[15] == 0x02
        # Form 1 subheader flag (submode = 0x08)
        assert sec[18] == 0x08
        # EDC checksum validation (calculated over bytes 16..2072)
        expected_edc = struct.unpack("<I", sec[2072:2076])[0]
        calculated_edc = calculate_cdrom_edc(sec[16:2072])
        assert expected_edc == calculated_edc, f"Sector {sec_idx} EDC mismatch!"


def test_psx_rom_handler_manager_integration():
    """Verifies RomManager auto-detection, metadata extraction, unpacking, and repacking."""
    manager = RomManager()
    assert "psx" in manager.handlers

    iso_bytes = create_synthetic_psx_iso(
        game_id="SLUS-00001",
        title="HANDLER TEST GAME",
    )

    # Auto-detection
    assert manager.detect_format(iso_bytes) == "psx"

    bin_bytes = create_synthetic_psx_bin(
        game_id="SLUS-00001",
        title="HANDLER TEST GAME",
    )
    assert manager.detect_format(bin_bytes) == "psx"

    # Metadata extraction
    meta = manager.get_metadata(iso_bytes)
    assert meta["platform"] == "psx"
    assert meta["game_id"] == "SLUS-00001"
    assert meta["title"] == "HANDLER TEST GAME"
    assert meta["region"] == "USA"
    assert meta["file_count"] >= 3

    # Unpack and Repack
    with tempfile.TemporaryDirectory() as tmp_dir:
        unpack_dir = os.path.join(tmp_dir, "unpacked")
        repacked_iso_path = os.path.join(tmp_dir, "repacked.iso")
        repacked_bin_path = os.path.join(tmp_dir, "repacked.bin")

        manager.unpack(iso_bytes, unpack_dir)
        assert os.path.isfile(os.path.join(unpack_dir, "SYSTEM.CNF"))

        # Repack as ISO
        manager.repack(unpack_dir, repacked_iso_path)
        assert os.path.isfile(repacked_iso_path)
        with open(repacked_iso_path, "rb") as f:
            repacked_iso = PSXRom.from_bytes(f.read())
            assert repacked_iso.format == PSXFormat.ISO
            assert repacked_iso.has_file("SYSTEM.CNF")

        # Repack as BIN
        manager.repack(unpack_dir, repacked_bin_path)
        assert os.path.isfile(repacked_bin_path)
        with open(repacked_bin_path, "rb") as f:
            repacked_bin = PSXRom.from_bytes(f.read())
            assert repacked_bin.format == PSXFormat.BIN
            assert repacked_bin.has_file("SYSTEM.CNF")


def test_psx_error_handling():
    """Verifies that invalid payloads raise appropriate ParseError or FileNotFoundError."""
    # Data too small
    with pytest.raises(ParseError, match="too small"):
        PSXRom(b"\x00" * 100)

    # Invalid ISO image
    with pytest.raises(ParseError, match="Failed to mount"):
        PSXRom(b"\x00" * (2048 * 20))

    # Replace nonexistent file
    iso_bytes = create_synthetic_psx_iso()
    rom = PSXRom.from_bytes(iso_bytes)
    with pytest.raises(FileNotFoundError):
        rom.replace_file("NONEXISTENT_FILE.DAT", b"HELLO")


def test_psx_bin_mode1_support():
    """Verify 2352-byte/sector Mode 1 raw CD-ROM BIN auto-detection, parsing, and repacking."""
    bin_bytes = create_synthetic_psx_bin(
        game_id="SLUS-00001",
        title="MODE 1 PS1 GAME",
        mode=1,
    )
    rom = PSXRom(bin_bytes)
    assert rom.format == PSXFormat.BIN_MODE1
    assert rom.sector_size == 2352
    assert rom.bin_mode == 1
    assert rom.game_id == "SLUS-00001"
    assert rom.has_file("SYSTEM.CNF")

    # Verify repacking to Mode 1 BIN
    repacked = rom.to_bytes()
    assert len(repacked) == len(bin_bytes)
    num_sectors = len(repacked) // 2352
    for sec_idx in range(num_sectors):
        sec = repacked[sec_idx * 2352 : (sec_idx + 1) * 2352]
        assert sec[:12] == SYNC_PATTERN
        assert sec[15] == 0x01
        expected_edc = struct.unpack("<I", sec[2064:2068])[0]
        calculated_edc = calculate_cdrom_edc(sec[:2064])
        assert expected_edc == calculated_edc

    reloaded = PSXRom(repacked)
    assert reloaded.format == PSXFormat.BIN_MODE1
    assert reloaded.has_file("SYSTEM.CNF")
    assert "MODE1/2352" in rom.generate_cue()


def test_psx_replace_system_cnf_refresh():
    """Verify replacing SYSTEM.CNF dynamically refreshes game_id, boot_path, and region."""
    iso_bytes = create_synthetic_psx_iso(game_id="SLUS-00001")
    rom = PSXRom(iso_bytes)
    assert rom.game_id == "SLUS-00001"
    assert rom.region == "USA"

    new_cnf = b"BOOT = cdrom:\\SLES_999.99;1\r\n"
    rom.replace_file("SYSTEM.CNF", new_cnf)
    assert rom.game_id == "SLES-99999"
    assert rom.region == "EUR"
    assert rom.boot_path == "SLES_999.99"


def test_psx_rom_manager_unpack_filepath_and_repack(tmp_path):
    """Verify RomManager unpack via filepath (passing **kwargs) and repack without explicit fmt."""
    iso_bytes = create_synthetic_psx_iso(game_id="SLUS-00001", title="PSX TEST GAME")
    iso_path = tmp_path / "game.iso"
    iso_path.write_bytes(iso_bytes)

    out_dir = tmp_path / "unpacked_psx"
    mgr = RomManager()

    # This passes filepath=filepath to handler.unpack
    meta = mgr.unpack(str(iso_path), str(out_dir))
    assert meta["format"] == "psx"
    assert meta["game_id"] == "SLUS-00001"
    assert (out_dir / "SYSTEM.CNF").is_file()

    # Repack without specifying format, testing filesystem clues
    repacked_bytes = mgr.repack(str(out_dir))
    reloaded = PSXRom.from_bytes(repacked_bytes)
    assert reloaded.game_id == "SLUS-00001"
    assert reloaded.has_file("SYSTEM.CNF")


