import pytest
from miorom.platforms.gb.builder import (
    NINTENDO_LOGO,
    calculate_global_checksum,
    calculate_header_checksum,
    GBHeader,
    GBRomBuilder,
)
from miorom.platforms.gb.rom import GBRom


def test_gb_checksum_functions():
    buf = bytearray(0x150)
    # Title 'TEST'
    buf[0x134:0x138] = b"TEST"
    buf[0x147] = 0x01  # MBC1
    buf[0x148] = 0x00  # 32KB

    h_chk = calculate_header_checksum(buf)
    buf[0x14D] = h_chk
    # Validate with GBRom
    gb = GBRom(buf)
    assert gb.is_header_checksum_valid()

    g_chk = calculate_global_checksum(buf)
    assert isinstance(g_chk, int)
    assert 0 <= g_chk <= 0xFFFF


def test_gb_header_parse_and_pack():
    builder = GBRomBuilder(mbc_type=0x01, is_cgb=False, is_sgb=False)
    rom_bytes = builder.build(title="ZELDA")

    header = GBHeader.parse(rom_bytes)
    assert header.title == "ZELDA"
    assert header.mbc_type == 0x01
    assert header.rom_size_code == 0x00
    assert header.is_cgb is False
    assert header.is_sgb is False

    # Repack and verify
    repacked = header.pack()
    assert repacked[0x104:0x134] == NINTENDO_LOGO
    assert calculate_header_checksum(repacked) == repacked[0x14D]


def test_gb_header_cgb_mode():
    builder = GBRomBuilder(mbc_type=0x19, is_cgb=True)
    rom_bytes = builder.build(title="CRYSTAL")

    header = GBHeader.parse(rom_bytes)
    assert header.title == "CRYSTAL"
    assert header.mbc_type == 0x19
    assert header.is_cgb is True


def test_gb_builder_bank_data():
    builder = GBRomBuilder(mbc_type=0x01)
    bank0_code = b"\x3E\x01\xEA\x00\xC0"  # ld a, 1; ld (0xC000), a
    builder.set_bank_data(0, bank0_code)

    bank1_data = b"Custom script text for localization testing."
    builder.set_bank_data(1, bank1_data)

    rom_bytes = builder.build(title="MIOROM")
    assert len(rom_bytes) >= 0x8000
    # Bank 0 data preserved
    assert rom_bytes[:len(bank0_code)] == bank0_code
    # Bank 1 data placed at 0x4000
    assert rom_bytes[0x4000:0x4000 + len(bank1_data)] == bank1_data

    # Verify bootability with GBRom inspector
    gb = GBRom(rom_bytes)
    assert gb.is_logo_valid()
    assert gb.is_header_checksum_valid()
    assert gb.is_global_checksum_valid()


def test_gb_builder_expand():
    builder = GBRomBuilder(mbc_type=0x01)
    rom_32k = builder.build(title="EXPANDME")
    assert len(rom_32k) == 0x8000

    # Expand from 2 banks (32KB) to 4 banks (64KB)
    rom_64k = builder.expand(rom_32k, target_banks=4)
    assert len(rom_64k) == 0x10000
    # Header ROM size code updated to 0x01 (64KB)
    assert rom_64k[0x148] == 0x01
    # Padded area filled with 0xFF
    assert rom_64k[0x8000:0x8010] == bytes([0xFF] * 16)

    # Validate expanded ROM integrity
    gb_expanded = GBRom(rom_64k)
    assert gb_expanded.is_header_checksum_valid()
    assert gb_expanded.is_global_checksum_valid()


def test_gb_builder_invalid_inputs():
    builder = GBRomBuilder()
    with pytest.raises(ValueError):
        builder.set_bank_data(-1, b"\x00")

    # Non power of two banks
    with pytest.raises(ValueError):
        builder.expand(bytearray(0x8000), target_banks=3)

    # Buffer too small
    with pytest.raises(ValueError):
        calculate_header_checksum(b"\x00" * 10)
