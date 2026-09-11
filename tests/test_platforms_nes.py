"""
Unit tests for NESRom platform handler (iNES / NES 2.0).
"""

import struct
import pytest

from miorom.platforms.nes.rom import NESRom, NESHeaderStruct
from miorom.errors import ParseError


def create_mock_nes(
    prg_16k_units: int = 2,
    chr_8k_units: int = 1,
    mapper: int = 0,
    mirroring: int = 0,
    has_battery: bool = False,
    has_trainer: bool = False,
    is_nes20: bool = False,
) -> bytes:
    header = bytearray(16)
    header[0:4] = b"NES\x1a"
    header[4] = prg_16k_units & 0xFF
    header[5] = chr_8k_units & 0xFF

    flags6 = (mirroring & 1)
    if has_battery:
        flags6 |= 0x02
    if has_trainer:
        flags6 |= 0x04
    flags6 |= (mapper & 0x0F) << 4
    header[6] = flags6

    flags7 = (mapper & 0xF0)
    if is_nes20:
        flags7 |= 0x08
    header[7] = flags7

    if is_nes20:
        header[8] = (mapper >> 8) & 0x0F

    data = bytearray(header)
    if has_trainer:
        data.extend(b"\xEA" * 512)

    prg_bytes = b"\xAA" * (prg_16k_units * 16384)
    data.extend(prg_bytes)

    chr_bytes = b"\x55" * (chr_8k_units * 8192)
    data.extend(chr_bytes)

    return bytes(data)


def test_nes_rom_basic_nrom():
    raw = create_mock_nes(prg_16k_units=2, chr_8k_units=1, mapper=0, mirroring=1)
    rom = NESRom(raw)

    assert rom.mapper_id == 0
    assert rom.mapper_name == "NROM"
    assert rom.prg_size == 32768
    assert rom.chr_size == 8192
    assert rom.mirroring == "vertical"
    assert rom.has_battery is False
    assert rom.has_trainer is False
    assert rom.has_chr_ram is False
    assert len(rom.prg_rom) == 32768
    assert len(rom.chr_rom) == 8192
    assert rom.prg_rom[:4] == b"\xAA\xAA\xAA\xAA"
    assert rom.chr_rom[:4] == b"\x55\x55\x55\x55"


def test_nes_rom_mmc3_and_battery():
    # Mapper 4 = MMC3, horizontal mirroring (0), battery (True)
    raw = create_mock_nes(prg_16k_units=8, chr_8k_units=16, mapper=4, mirroring=0, has_battery=True)
    rom = NESRom(raw)

    assert rom.mapper_id == 4
    assert "MMC3" in rom.mapper_name
    assert rom.has_battery is True
    assert rom.mirroring == "horizontal"
    assert rom.prg_size == 8 * 16384
    assert rom.chr_size == 16 * 8192


def test_nes_rom_trainer_strip_and_add():
    raw = create_mock_nes(prg_16k_units=1, chr_8k_units=0, mapper=2, has_trainer=True)
    rom = NESRom(raw)

    assert rom.has_trainer is True
    assert rom.trainer is not None
    assert len(rom.trainer) == 512
    assert rom.has_chr_ram is True
    assert rom.chr_size == 0
    assert rom.chr_rom == b""

    # Strip trainer
    stripped = rom.strip_trainer()
    assert stripped is True
    assert rom.has_trainer is False
    assert rom.trainer is None
    assert len(rom.data) == 16 + 16384

    # Add trainer back
    custom_trainer = b"\x42" * 512
    added = rom.add_trainer(custom_trainer)
    assert added is True
    assert rom.has_trainer is True
    assert rom.trainer == custom_trainer
    assert len(rom.data) == 16 + 512 + 16384


def test_nes_rom_replace_prg_and_chr():
    raw = create_mock_nes(prg_16k_units=1, chr_8k_units=1, mapper=1)
    rom = NESRom(raw)

    new_prg = b"\x77" * 32768  # 2 x 16KB
    rom.set_prg_rom(new_prg)
    assert rom.prg_size == 32768
    assert rom.prg_rom == new_prg

    new_chr = b"\x88" * 16384  # 2 x 8KB
    rom.set_chr_rom(new_chr)
    assert rom.chr_size == 16384
    assert rom.chr_rom == new_chr

    rebuilt = NESRom(rom.to_bytes())
    assert rebuilt.prg_size == 32768
    assert rebuilt.chr_size == 16384
    assert rebuilt.prg_rom == new_prg
    assert rebuilt.chr_rom == new_chr


def test_nes_rom_invalid_magic():
    with pytest.raises(ParseError):
        NESRom(b"NOT_A_NES_ROM_DATA")
