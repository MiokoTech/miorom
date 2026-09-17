"""
tests.test_platforms_psp_rom
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for PSP Unified ROM, Disc & Package Engine (PSPRom, PSPRomHandler).
Tests ISO 9660, CSO, and PBP containers, metadata extraction, executable management,
filesystem operations, and RomManager auto-dispatch with 100% zero external dependencies.
"""

import os
import tempfile

import pytest

from miorom.errors import ParseError
from miorom.platforms.iso.cso import CSOCompressor
from miorom.platforms.psp.rom import (
    PSPFormat,
    PSPRom,
    create_synthetic_psp_iso,
    create_synthetic_psp_pbp,
    resolve_psp_region,
)
from miorom.rom.manager import RomManager


def test_psp_iso_detection_and_metadata():
    """Verifies format auto-detection, PARAM.SFO parsing, and region resolution on ISO."""
    iso_bytes = create_synthetic_psp_iso(
        game_id="ULUS10001",
        title="Crisis Core Test",
        version="1.02",
        category="UG",
    )
    rom = PSPRom.from_bytes(iso_bytes)

    assert rom.format == PSPFormat.ISO
    assert rom.original_format == PSPFormat.ISO
    assert rom.game_id == "ULUS10001"
    assert rom.title == "Crisis Core Test"
    assert rom.version == "1.02"
    assert rom.category == "UG"
    assert rom.region == "USA"
    assert rom.icon_bytes is not None
    assert rom.background_bytes is not None
    assert rom.boot_audio_bytes is not None


def test_psp_region_resolver_all_territories():
    """Verifies Sony 4-character product code mapping across all world territories."""
    assert resolve_psp_region("ULUS10001") == "USA"
    assert resolve_psp_region("UCUS98765") == "USA"
    assert resolve_psp_region("NPUH10001") == "USA"
    assert resolve_psp_region("ULES00123") == "EUR"
    assert resolve_psp_region("UCES00001") == "EUR"
    assert resolve_psp_region("NPEH00001") == "EUR"
    assert resolve_psp_region("ULJM05000") == "JPN"
    assert resolve_psp_region("NPJH50001") == "JPN"
    assert resolve_psp_region("ULAS42001") == "ASIA"
    assert resolve_psp_region("UCAS40001") == "ASIA"
    assert resolve_psp_region("ULKS46001") == "KOR"
    assert resolve_psp_region("NPKH00001") == "KOR"
    assert resolve_psp_region("HOMEBREW01") == "Global"
    assert resolve_psp_region("") == "Unknown"


def test_psp_cso_loading_and_decompression():
    """Verifies Compressed ISO (CSO) auto-detection, decompression, and virtual filesystem."""
    iso_bytes = create_synthetic_psp_iso(
        game_id="ULES00851",
        title="European PSP Game",
    )
    cso_bytes = CSOCompressor.compress_bytes(iso_bytes)

    rom = PSPRom(cso_bytes)
    assert rom.original_format == PSPFormat.CSO
    assert rom.game_id == "ULES00851"
    assert rom.title == "European PSP Game"
    assert rom.region == "EUR"
    assert rom.has_file("PSP_GAME/PARAM.SFO")
    assert len(rom.get_file("PSP_GAME/PARAM.SFO")) > 0


def test_psp_pbp_loading_and_metadata():
    """Verifies EBOOT.PBP digital package auto-detection and section inspection."""
    pbp_bytes = create_synthetic_psp_pbp(
        game_id="NPUH10002",
        title="Synthetic PBP Game",
        version="1.01",
    )
    rom = PSPRom(pbp_bytes)

    assert rom.format == PSPFormat.PBP
    assert rom.original_format == PSPFormat.PBP
    assert rom.game_id == "NPUH10002"
    assert rom.title == "Synthetic PBP Game"
    assert rom.version == "1.01"
    assert rom.category == "EG"
    assert rom.region == "USA"
    assert rom.icon_bytes == b"\x89PNG\r\n\x1a\n_PBP_ICON"
    assert rom.get_eboot_bin() == b"\x7FELF_PBP_EXEC"


def test_psp_filesystem_listing_and_filtering():
    """Verifies list_files, prefix filtering, and get_file on UMD ISO."""
    iso_bytes = create_synthetic_psp_iso()
    rom = PSPRom.from_bytes(iso_bytes)

    all_files = rom.list_files()
    assert any("PARAM.SFO" in f for f in all_files)
    assert any("BOOT.BIN" in f for f in all_files)

    usrdir_files = rom.list_files("PSP_GAME/USRDIR")
    assert all("USRDIR" in f for f in usrdir_files)
    assert any("UI.GIM" in f.upper() for f in usrdir_files)

    assert rom.has_file("PSP_GAME/USRDIR/data.bin") is True
    assert rom.has_file("PSP_GAME/NONEXISTENT.DAT") is False

    data_bytes = rom.get_file("PSP_GAME/USRDIR/data.bin")
    assert data_bytes == b"SAMPLE_GAME_ASSET_BYTES"


def test_psp_file_replacement_and_expansion():
    """Verifies replacing file within UMD ISO with automatic extent relocation on growth."""
    iso_bytes = create_synthetic_psp_iso()
    rom = PSPRom.from_bytes(iso_bytes)

    # Replace with a large payload requiring new sectors (e.g. 8192 bytes = 4 sectors)
    large_payload = b"TRANSLATED_SCRIPT_PAYLOAD_EXPANDED_" * 250
    rom.replace_file("PSP_GAME/USRDIR/data.bin", large_payload)

    # Re-read and verify contents
    updated = rom.get_file("PSP_GAME/USRDIR/data.bin")
    assert updated == large_payload


def test_psp_executable_helpers():
    """Verifies get_boot_bin, get_eboot_bin, replace_boot_bin, and replace_eboot_bin."""
    iso_bytes = create_synthetic_psp_iso()
    rom = PSPRom.from_bytes(iso_bytes)

    assert rom.get_boot_bin() == b"\x7FELF_BOOT_DUMMY_EXEC_PAYLOAD"
    assert rom.get_eboot_bin() == b"~PSP_EBOOT_DUMMY_EXEC_PAYLOAD"

    new_boot = b"\x7FELF_MODDED_BOOT_CODE_12345"
    rom.replace_boot_bin(new_boot)
    assert rom.get_boot_bin() == new_boot

    new_eboot = b"~PSP_MODDED_EBOOT_CODE_67890"
    rom.replace_eboot_bin(new_eboot)
    assert rom.get_eboot_bin() == new_eboot


def test_psp_gim_texture_discovery():
    """Verifies find_textures scanning game files for embedded Sony GIM images."""
    iso_bytes = create_synthetic_psp_iso(with_gim=True)
    rom = PSPRom.from_bytes(iso_bytes)

    textures = rom.find_textures()
    assert len(textures) >= 1
    fpath, offset, gim = textures[0]
    assert "ui.gim" in fpath.lower()
    assert offset == 0
    assert gim.format is not None


def test_psp_metadata_editing():
    """Verifies set_title, set_icon, and set_background updating container."""
    iso_bytes = create_synthetic_psp_iso(title="Old Japanese Title")
    rom = PSPRom.from_bytes(iso_bytes)
    assert rom.title == "Old Japanese Title"

    rom.set_title("New English Title")
    assert rom.title == "New English Title"

    new_icon = b"\x89PNG\r\n\x1a\n_CUSTOM_ICON_BYTES"
    rom.set_icon(new_icon)
    assert rom.icon_bytes == new_icon

    new_bg = b"\x89PNG\r\n\x1a\n_CUSTOM_BACKGROUND_BYTES"
    rom.set_background(new_bg)
    assert rom.background_bytes == new_bg


def test_psp_format_cross_conversion():
    """Verifies converting ISO to CSO and saving with format detection."""
    iso_bytes = create_synthetic_psp_iso(game_id="ULJM05000", title="Japanese PSP Game")
    rom = PSPRom.from_bytes(iso_bytes)

    cso_bytes = rom.to_bytes(fmt=PSPFormat.CSO)
    assert cso_bytes[:4] == b"CISO"

    reloaded_cso = PSPRom(cso_bytes)
    assert reloaded_cso.game_id == "ULJM05000"
    assert reloaded_cso.region == "JPN"

    # Save to file
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "game.cso")
        rom.save(out_path)
        assert os.path.exists(out_path)
        loaded = PSPRom.from_file(out_path)
        assert loaded.game_id == "ULJM05000"


def test_psp_rom_handler_and_rom_manager_dispatch():
    """Verifies RomManager auto-detects PSP ISO, CSO, and PBP containers."""
    manager = RomManager()

    iso_bytes = create_synthetic_psp_iso(game_id="ULUS10001", title="Manager Test ISO")
    pbp_bytes = create_synthetic_psp_pbp(game_id="NPUH10002", title="Manager Test PBP")
    cso_bytes = CSOCompressor.compress_bytes(iso_bytes)

    assert manager.detect_format(iso_bytes) == "psp"
    assert manager.detect_format(pbp_bytes) == "psp"
    assert manager.detect_format(cso_bytes) == "psp"

    meta_iso = manager.get_metadata(iso_bytes)
    assert meta_iso["platform"] == "psp"
    assert meta_iso["game_id"] == "ULUS10001"
    assert meta_iso["region"] == "USA"

    meta_pbp = manager.get_metadata(pbp_bytes)
    assert meta_pbp["platform"] == "psp"
    assert meta_pbp["game_id"] == "NPUH10002"


def test_psp_error_handling():
    """Verifies ParseError on unrecognized data or non-PSP disc images."""
    with pytest.raises(ParseError, match="Unsupported or unrecognized PSP image format"):
        PSPRom.from_bytes(b"RANDOM_NON_PSP_BYTES_0123456789")

    # Generic ISO without PSP_GAME
    from miorom.platforms.iso.builder import ISOBuilder

    builder = ISOBuilder(volume_id="GENERIC_DISC")
    builder.add_file("README.TXT", b"Not a PSP game")
    generic_iso = builder.build()

    # Generic ISO should not be recognized by PSPRomHandler
    manager = RomManager()
    detected = manager.detect_format(generic_iso)
    assert detected == "iso9660"  # Falls through to generic ISO9660 handler!


def test_psp_pbp_embedded_iso_and_cross_conversion():
    """Verifies PBP with embedded ISO in DATA.PSAR mounts virtual filesystem and enables true ISO/CSO conversion."""
    iso_bytes = create_synthetic_psp_iso(
        game_id="ULUS10001",
        title="PBP Converter Test",
    )
    rom_iso = PSPRom.from_bytes(iso_bytes)
    pbp_bytes = rom_iso.to_bytes(fmt=PSPFormat.PBP)
    assert pbp_bytes[:4] == b"\x00PBP"

    # Load PBP containing embedded ISO
    rom_pbp = PSPRom.from_bytes(pbp_bytes)
    assert rom_pbp.format == PSPFormat.PBP
    assert rom_pbp._iso is not None
    assert rom_pbp.has_file("PSP_GAME/USRDIR/data.bin")
    assert rom_pbp.get_file("PSP_GAME/USRDIR/data.bin") == b"SAMPLE_GAME_ASSET_BYTES"

    # Modify file in PBP and verify synchronization
    rom_pbp.replace_file("PSP_GAME/USRDIR/data.bin", b"NEW_DATA_IN_PBP_ISO")
    assert rom_pbp.get_file("PSP_GAME/USRDIR/data.bin") == b"NEW_DATA_IN_PBP_ISO"

    # Convert PBP to true ISO (must have PVD at sector 16 and contain modified file)
    exported_iso = rom_pbp.to_bytes(fmt=PSPFormat.ISO)
    assert exported_iso[:4] != b"\x00PBP"
    assert exported_iso[16 * 2048 : 16 * 2048 + 6] == b"\x01CD001"
    reloaded_iso = PSPRom.from_bytes(exported_iso)
    assert reloaded_iso.format == PSPFormat.ISO
    assert reloaded_iso.get_file("PSP_GAME/USRDIR/data.bin") == b"NEW_DATA_IN_PBP_ISO"

    # Convert PBP to CSO
    exported_cso = rom_pbp.to_bytes(fmt=PSPFormat.CSO)
    assert exported_cso[:4] == b"CISO"
    reloaded_cso = PSPRom.from_bytes(exported_cso)
    assert reloaded_cso.original_format == PSPFormat.CSO
    assert reloaded_cso.get_file("PSP_GAME/USRDIR/data.bin") == b"NEW_DATA_IN_PBP_ISO"

    # Test Homebrew PBP (without embedded ISO in DATA.PSAR) conversion to ISO
    hb_pbp_bytes = create_synthetic_psp_pbp(game_id="NPUH10002", title="Homebrew App")
    rom_hb = PSPRom.from_bytes(hb_pbp_bytes)
    hb_iso_bytes = rom_hb.to_bytes(fmt=PSPFormat.ISO)
    assert hb_iso_bytes[16 * 2048 : 16 * 2048 + 6] == b"\x01CD001"
    reloaded_hb = PSPRom.from_bytes(hb_iso_bytes)
    assert reloaded_hb.format == PSPFormat.ISO
    assert reloaded_hb.has_file("PSP_GAME/SYSDIR/EBOOT.BIN")


def test_psp_find_iso_file_exact_boundary():
    """Verifies that _find_iso_file matches on directory boundaries and does not falsely match substring prefixes."""
    from miorom.platforms.iso.builder import ISOBuilder

    builder = ISOBuilder(volume_id="TEST_BOUNDARY")
    builder.add_file("PSP_GAME/SYSDIR/REBOOT.BIN", b"REBOOT_DATA")
    builder.add_file("PSP_GAME/SYSDIR/BOOT.BIN", b"BOOT_DATA")
    iso_bytes = builder.build()

    rom = PSPRom.from_bytes(iso_bytes)
    assert rom._find_iso_file("BOOT.BIN") == "PSP_GAME/SYSDIR/BOOT.BIN"
    assert rom._find_iso_file("REBOOT.BIN") == "PSP_GAME/SYSDIR/REBOOT.BIN"


def test_psp_rom_manager_unpack_filepath_and_repack(tmp_path):
    """Verify RomManager unpack via filepath (passing **kwargs) and repack without explicit fmt."""
    iso_bytes = create_synthetic_psp_iso(game_id="ULUS10001", title="PSP TEST GAME")
    iso_path = tmp_path / "game.iso"
    iso_path.write_bytes(iso_bytes)

    out_dir = tmp_path / "unpacked_psp"
    mgr = RomManager()

    # This passes filepath=filepath to handler.unpack
    meta = mgr.unpack(str(iso_path), str(out_dir))
    assert meta["format"] == "psp"
    assert meta["game_id"] == "ULUS10001"
    assert (out_dir / "PSP_GAME" / "PARAM.SFO").is_file()

    # Repack without specifying format, testing filesystem clues
    repacked_bytes = mgr.repack(str(out_dir))
    reloaded = PSPRom.from_bytes(repacked_bytes)
    assert reloaded.game_id == "ULUS10001"
    assert reloaded.has_file("PSP_GAME/PARAM.SFO")


