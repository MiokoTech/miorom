import struct
import pytest
from miorom.core.overlay_mapper import MemoryOverlayMapper, OverlayRegion


def test_memory_overlay_mapper_dual_translation():
    mapper = MemoryOverlayMapper()

    # Region 1: Main code (RAM 0x02000000..0x02010000 -> ROM 0x000000..0x010000)
    reg_main = OverlayRegion(
        region_id="MAIN",
        name="arm9_main",
        ram_address=0x02000000,
        ram_size=0x10000,
        rom_offset=0x0000,
        rom_size=0x10000,
    )
    mapper.add_region(reg_main)

    # Region 2: Overlay 5 (RAM 0x02100000..0x02108000 -> ROM 0x080000..0x088000)
    reg_ov5 = OverlayRegion(
        region_id=5,
        name="overlay9_0005",
        ram_address=0x02100000,
        ram_size=0x8000,
        rom_offset=0x080000,
        rom_size=0x8000,
    )
    mapper.add_region(reg_ov5)

    # Test RAM -> ROM
    # 0x02004000 -> 0x004000
    assert mapper.ram_to_rom(0x02004000) == 0x004000
    # 0x02101234 -> 0x081234
    assert mapper.ram_to_rom(0x02101234) == 0x081234

    # Test ROM -> RAM
    assert mapper.rom_to_ram(0x004000) == 0x02004000
    assert mapper.rom_to_ram(0x081234) == 0x02101234


def test_parse_psx_exe_header():
    header = bytearray(0x800)
    header[:8] = b"PS-X EXE"
    # Text destination: 0x80010000
    struct.pack_into("<I", header, 0x18, 0x80010000)
    # Text size: 0x20000
    struct.pack_into("<I", header, 0x1C, 0x20000)

    mapper = MemoryOverlayMapper.parse_psx_exe(bytes(header))
    assert len(mapper.regions) == 1
    reg = mapper.regions[0]
    assert reg.ram_address == 0x80010000
    assert reg.rom_offset == 0x800

    # Translate address
    assert mapper.ram_to_rom(0x80010100) == 0x900
    assert mapper.rom_to_ram(0x900) == 0x80010100
