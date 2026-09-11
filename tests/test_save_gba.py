import pytest
from miorom.save.gba_save import (
    GBASaveType,
    GBASaveInfo,
    GBASaveDetector,
    GBASavePatcher,
)


def test_gba_save_detection():
    # Construct synthetic GBA ROM fragments with SDK tags
    dummy_rom_flash1m = b"\xEA\x00\x00\x2E" * 100 + b"FLASH1M_V103" + b"\x00" * 500
    dummy_rom_flash512 = b"\xEA\x00\x00\x2E" * 100 + b"FLASH512_V130" + b"\x00" * 500
    dummy_rom_eeprom = b"\xEA\x00\x00\x2E" * 100 + b"EEPROM_V124" + b"\x00" * 500
    dummy_rom_sram = b"\xEA\x00\x00\x2E" * 100 + b"SRAM_V110" + b"\x00" * 500
    dummy_rom_none = b"\x00" * 1000

    info1 = GBASaveDetector.detect(dummy_rom_flash1m)
    assert info1 is not None
    assert info1.save_type == GBASaveType.FLASH_128K
    assert "FLASH1M" in info1.tag
    assert info1.size_bytes == 131072

    info2 = GBASaveDetector.detect(dummy_rom_flash512)
    assert info2 is not None
    assert info2.save_type == GBASaveType.FLASH_64K
    assert "FLASH512" in info2.tag

    info3 = GBASaveDetector.detect(dummy_rom_eeprom)
    assert info3 is not None
    assert info3.save_type == GBASaveType.EEPROM_8K

    info4 = GBASaveDetector.detect(dummy_rom_sram)
    assert info4 is not None
    assert info4.save_type == GBASaveType.SRAM

    assert GBASaveDetector.detect(dummy_rom_none) is None


def test_gba_save_patching_flash_to_sram():
    dummy_rom = b"\x00" * 200 + b"FLASH1M_V103\x00\x00" + b"\x00" * 400

    info_before = GBASaveDetector.detect(dummy_rom)
    assert info_before.save_type == GBASaveType.FLASH_128K

    patched, was_patched, msg = GBASavePatcher.patch_to_sram(dummy_rom)
    assert was_patched is True
    assert len(patched) == len(dummy_rom)

    info_after = GBASaveDetector.detect(patched)
    assert info_after is not None
    assert info_after.save_type == GBASaveType.SRAM
    assert "SRAM_V" in info_after.tag


def test_gba_save_patching_eeprom_to_sram():
    dummy_rom = b"\x00" * 100 + b"EEPROM_V124\x00\x00" + b"\x00" * 200
    patched, was_patched, msg = GBASavePatcher.patch_to_sram(dummy_rom)
    assert was_patched is True

    info_after = GBASaveDetector.detect(patched)
    assert info_after.save_type == GBASaveType.SRAM


def test_gba_save_already_sram():
    dummy_rom = b"\x00" * 100 + b"SRAM_V111" + b"\x00" * 200
    patched, was_patched, msg = GBASavePatcher.patch_to_sram(dummy_rom)
    assert was_patched is False
    assert "already uses native SRAM" in msg
