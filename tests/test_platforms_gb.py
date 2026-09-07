import pytest
from miorom.platforms.gb.rom import GBRom


def test_gb_rom_header_and_checksums():
    # 32KB minimal ROM
    data = bytearray(32768)

    # Logo
    data[0x104:0x134] = GBRom.NINTENDO_LOGO
    # Title
    data[0x134:0x143] = b"POKEMON RED\x00\x00\x00"
    # Cartridge type: MBC3+TIMER+RAM+BATTERY (0x10)
    data[0x147] = 0x10
    # ROM size: 32KB << 5 = 1MB
    data[0x148] = 0x05

    gb = GBRom(bytes(data))
    assert gb.title == "POKEMON RED"
    assert gb.cartridge_type == "MBC3+TIMER+RAM+BATTERY"
    assert gb.rom_size_bytes == 1048576
    assert gb.is_logo_valid() is True

    # Checksums
    assert gb.is_header_checksum_valid() is False
    gb.fix_header_checksum()
    assert gb.is_header_checksum_valid() is True

    assert gb.is_global_checksum_valid() is False
    gb.fix_global_checksum()
    assert gb.is_global_checksum_valid() is True

    # Bank resolving
    assert gb.resolve_bank_address(bank=1, addr=0x4000) == 0x4000
    assert gb.resolve_bank_address(bank=2, addr=0x4000) == 0x8000
    assert gb.resolve_bank_address(bank=0, addr=0x1234) == 0x1234
