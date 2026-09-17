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


def test_detect_dma_copies_complete():
    """Verifies that a complete ARM DMA3 transfer pattern is accurately detected."""
    # Synthetic ARM DMA3 transfer routine:
    # 0x08000000: ldr r3, [pc, #24]  -> literal at 0x08000020 (0x040000D4: DMA3SAD)
    # 0x08000004: ldr r0, [pc, #24]  -> literal at 0x08000024 (0x08001000: source)
    # 0x08000008: ldr r1, [pc, #24]  -> literal at 0x08000028 (0x02000000: dest)
    # 0x0800000C: ldr r2, [pc, #24]  -> literal at 0x0800002C (0x84000100: control, count=256)
    # 0x08000010: str r0, [r3]       -> store source to DMA3SAD
    # 0x08000014: str r1, [r3, #4]   -> store dest to DMA3DAD
    # 0x08000018: str r2, [r3, #8]   -> store control to DMA3CNT
    # 0x0800001C: bx lr
    # Literal pool:
    # 0x08000020: 0x040000D4
    # 0x08000024: 0x08001000
    # 0x08000028: 0x02000000
    # 0x0800002C: 0x84000100
    code = struct.pack(
        "<IIIIIIIIIIII",
        0xE59F3018,
        0xE59F0018,
        0xE59F1018,
        0xE59F2018,
        0xE5830000,
        0xE5831004,
        0xE5832008,
        0xE12FFF1E,
        0x040000D4,
        0x08001000,
        0x02000000,
        0x84000100,
    )
    records = MemoryOverlayMapper.detect_dma_copies(code, 0x08000000)
    assert len(records) == 1
    rec = records[0]
    assert rec.pc_address == 0x08000010
    assert rec.source_address == 0x08001000
    assert rec.destination_address == 0x02000000
    assert rec.word_count == 0x0100


def test_detect_dma_copies_negative_cases():
    """Verifies that non-DMA or incomplete patterns return an empty list without false positives."""
    # 1. User reproduction snippet: literal 0x040000D4 without matching STR instructions
    code_repro = struct.pack("<III", 0xE59F0000, 0x040000D4, 0xE58F1000)
    assert MemoryOverlayMapper.detect_dma_copies(code_repro, 0x08000000) == []

    # 2. Literal loaded into register, but no stores
    code_no_stores = struct.pack(
        "<IIII",
        0xE59F3000,
        0xE12FFF1E,
        0x040000D4,
        0x00000000,
    )
    assert MemoryOverlayMapper.detect_dma_copies(code_no_stores, 0x08000000) == []

    # 3. Partial store: only STR to SAD, missing DAD and CNT
    code_partial = struct.pack(
        "<IIIIII",
        0xE59F300C,
        0xE59F000C,
        0xE5830000,
        0xE12FFF1E,
        0x040000D4,
        0x08001000,
    )
    assert MemoryOverlayMapper.detect_dma_copies(code_partial, 0x08000000) == []

    # 4. Empty and short buffers
    assert MemoryOverlayMapper.detect_dma_copies(b"", 0x08000000) == []
    assert MemoryOverlayMapper.detect_dma_copies(b"\x00" * 8, 0x08000000) == []


def test_compressed_overlay_translation_rejected():
    """Verifies that linear address translation is rejected on compressed overlays."""
    from miorom.errors import CompressedOverlayError

    # NDS y9.bin overlay entry with compression flag (bit 24 set: 0x01000800)
    entry = struct.pack(
        "<8I",
        0,           # overlay id
        0x02000000,  # ram address
        0x2000,      # ram size
        0,           # bss size
        0,           # sinit_init
        0,           # sinit_init_end
        0,           # file id
        0x01000800,  # flags (bit 24 set -> compressed)
    )
    mapper = MemoryOverlayMapper.parse_nds_overlays(entry, fat_entries=[(0x1000, 0x1800)])
    region = mapper.regions[0]

    assert region.is_compressed is True

    # By default, returns None to avoid returning misleading linear offsets
    assert mapper.rom_to_ram(0x1100) is None
    assert mapper.ram_to_rom(0x02000100) is None
    assert region.rom_to_ram(0x1100) is None
    assert region.ram_to_rom(0x02000100) is None

    # When raise_on_compressed=True, raises CompressedOverlayError with actionable message
    with pytest.raises(CompressedOverlayError, match="is compressed"):
        mapper.rom_to_ram(0x1100, raise_on_compressed=True)

    with pytest.raises(CompressedOverlayError, match="is compressed"):
        mapper.ram_to_rom(0x02000100, raise_on_compressed=True)

    with pytest.raises(CompressedOverlayError, match="is compressed"):
        region.rom_to_ram(0x1100, raise_on_compressed=True)

    with pytest.raises(CompressedOverlayError, match="is compressed"):
        region.ram_to_rom(0x02000100, raise_on_compressed=True)


def test_uncompressed_overlay_translation_normal():
    """Verifies that uncompressed overlays (flags bit 24 unset) continue to translate linearly."""
    entry = struct.pack(
        "<8I",
        0,           # overlay id
        0x02000000,  # ram address
        0x2000,      # ram size
        0,           # bss size
        0,           # sinit_init
        0,           # sinit_init_end
        0,           # file id
        0x00000800,  # flags (bit 24 unset -> uncompressed)
    )
    mapper = MemoryOverlayMapper.parse_nds_overlays(entry, fat_entries=[(0x1000, 0x3000)])
    region = mapper.regions[0]

    assert region.is_compressed is False

    # Linear translation operates normally
    assert mapper.rom_to_ram(0x1100) == 0x02000100
    assert mapper.ram_to_rom(0x02000100) == 0x1100
    assert region.rom_to_ram(0x1100) == 0x02000100
    assert region.ram_to_rom(0x02000100) == 0x1100


