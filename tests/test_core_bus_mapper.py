import pytest
from miorom.core.bus_mapper import SNESBusMapper, NESBusMapper, GameBoyBusMapper


def test_snes_lorom_mapping():
    # Bank $00:$8000 -> file offset 0
    assert SNESBusMapper.lorom_to_offset(0x008000) == 0
    # Bank $00:$8000 with SMC header (512 bytes)
    assert SNESBusMapper.lorom_to_offset(0x008000, smc_header=True) == 512

    # Bank $80:$8000 mirrors Bank $00:$8000
    assert SNESBusMapper.lorom_to_offset(0x808000) == 0
    # Bank $81:$9000 -> 0x8000 + 0x1000 = 0x9000
    assert SNESBusMapper.lorom_to_offset(0x819000) == 0x9000

    # Roundtrip
    addr = SNESBusMapper.offset_to_lorom(0x9000, mirror=True)
    assert addr == 0x819000
    assert SNESBusMapper.lorom_to_offset(addr) == 0x9000


def test_snes_hirom_mapping():
    # Bank $C0:$0000 -> file offset 0
    assert SNESBusMapper.hirom_to_offset(0xC00000) == 0
    # Bank $40:$0000 mirrors $C0:$0000
    assert SNESBusMapper.hirom_to_offset(0x400000) == 0

    # Bank $C1:$1234 -> offset 0x11234
    assert SNESBusMapper.hirom_to_offset(0xC11234) == 0x11234

    # Roundtrip
    addr = SNESBusMapper.offset_to_hirom(0x11234, mirror=True)
    assert addr == 0xC11234
    assert SNESBusMapper.hirom_to_offset(addr) == 0x11234


def test_nes_nrom_mapping():
    # 32KB PRG: $8000 maps to offset 16 (after iNES header)
    assert NESBusMapper.nrom_to_offset(0x8000, prg_rom_size=32768) == 16
    assert NESBusMapper.nrom_to_offset(0xFFFF, prg_rom_size=32768) == 16 + 32767

    # 16KB PRG: $C000 mirrors $8000
    assert NESBusMapper.nrom_to_offset(0xC000, prg_rom_size=16384) == 16

    # Roundtrip
    assert NESBusMapper.offset_to_nrom(16) == 0x8000


def test_nes_mmc3_prg_mapping():
    prg_size = 128 * 1024  # 128 KB = 16 banks of 8KB (0..15)
    header_size = 16

    # Mode 0: $8000=R6, $A000=R7, $C000=(-2)=14, $E000=(-1)=15
    # Let R6=3, R7=5
    off_8000 = NESBusMapper.mmc3_prg_to_offset(0x8000, r6_bank=3, r7_bank=5, prg_rom_size=prg_size, prg_mode=0)
    assert off_8000 == header_size + (3 * 8192)

    off_a000 = NESBusMapper.mmc3_prg_to_offset(0xA000, r6_bank=3, r7_bank=5, prg_rom_size=prg_size, prg_mode=0)
    assert off_a000 == header_size + (5 * 8192)

    off_c000 = NESBusMapper.mmc3_prg_to_offset(0xC000, r6_bank=3, r7_bank=5, prg_rom_size=prg_size, prg_mode=0)
    assert off_c000 == header_size + (14 * 8192)

    off_e000 = NESBusMapper.mmc3_prg_to_offset(0xE000, r6_bank=3, r7_bank=5, prg_rom_size=prg_size, prg_mode=0)
    assert off_e000 == header_size + (15 * 8192)


def test_gameboy_bus_mapping():
    # Bank 0: $0000-$3FFF is direct offset
    assert GameBoyBusMapper.mbc_to_offset(0x0100, bank=0) == 0x0100
    assert GameBoyBusMapper.offset_to_mbc(0x0100) == (0, 0x0100)

    # Bank 2: $4000-$7FFF -> bank 2 * 0x4000 = 0x8000
    assert GameBoyBusMapper.mbc_to_offset(0x4000, bank=2) == 0x8000
    assert GameBoyBusMapper.offset_to_mbc(0x8000) == (2, 0x4000)

    # MBC1 quirk: bank 0 requested at $4000 maps to bank 1
    assert GameBoyBusMapper.mbc_to_offset(0x4000, bank=0, mbc_type="mbc1") == 0x4000
    # MBC1 quirk: bank 0x20 maps to 0x21
    assert GameBoyBusMapper.mbc_to_offset(0x4000, bank=0x20, mbc_type="mbc1") == 0x21 * 0x4000
