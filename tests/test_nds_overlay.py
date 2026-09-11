import pytest
from miorom.platforms.nds.overlay import (
    NDSOverlayCompressor,
    NDSOverlayManager,
    NDSOverlayTable,
    OverlayAllocationReport,
)
from miorom.platforms.nds.rom import NDSFileEntry, NDSHeader, NDSOverlayEntry, NDSRom


def make_dummy_overlay_entry_bytes(
    overlay_id: int = 1,
    ram_address: int = 0x02000000,
    ram_size: int = 0x1000,
    bss_size: int = 0x200,
    sinit_init: int = 0x02000800,
    sinit_init_end: int = 0x02000900,
    file_id: int = 5,
    flags: int = 0x01000000,
) -> bytes:
    buf = bytearray(32)
    buf[0:4] = overlay_id.to_bytes(4, "little")
    buf[4:8] = ram_address.to_bytes(4, "little")
    buf[8:12] = ram_size.to_bytes(4, "little")
    buf[12:16] = bss_size.to_bytes(4, "little")
    buf[16:20] = sinit_init.to_bytes(4, "little")
    buf[20:24] = sinit_init_end.to_bytes(4, "little")
    buf[24:28] = file_id.to_bytes(4, "little")
    buf[28:32] = flags.to_bytes(4, "little")
    return bytes(buf)


def test_overlay_table_parse_and_pack():
    raw = make_dummy_overlay_entry_bytes(overlay_id=0) + make_dummy_overlay_entry_bytes(overlay_id=1, ram_address=0x02100000)
    table = NDSOverlayTable.from_bytes(raw)

    assert len(table) == 2
    entry0 = table.get_entry(0)
    assert entry0 is not None
    assert entry0.id == 0
    assert entry0.ram_address == 0x02000000
    assert entry0.ram_size == 0x1000
    assert entry0.bss_size == 0x200
    assert entry0.file_id == 5
    assert entry0.flags == 0x01000000

    entry1 = table.get_entry(1)
    assert entry1 is not None
    assert entry1.ram_address == 0x02100000

    # Serialization roundtrip
    serialized = table.to_bytes()
    assert serialized == raw


def test_overlay_table_mutations():
    table = NDSOverlayTable([])
    new_entry = NDSOverlayEntry(
        id=42,
        ram_address=0x02200000,
        ram_size=0x4000,
        bss_size=0x100,
        sinit_init=0,
        sinit_init_end=0,
        file_id=12,
        flags=0,
    )
    table.add_entry(new_entry)
    assert len(table) == 1

    # Duplicate add raises ValueError
    with pytest.raises(ValueError):
        table.add_entry(new_entry)

    # Relocate
    table.relocate(42, 0x02250000)
    assert table.get_entry(42).ram_address == 0x02250000

    # Update entry fields
    table.update_entry(42, ram_size=0x5000, is_compressed=True)
    e = table.get_entry(42)
    assert e.ram_size == 0x5000
    assert (e.flags & 0x01000000) != 0

    # Unknown ID raises KeyError
    with pytest.raises(KeyError):
        table.update_entry(999, ram_size=100)


def test_overlay_compressor():
    original_text = b"Nintendo DS Translation Script Block - Repeated Data 12345 " * 20
    compressed = NDSOverlayCompressor.compress(original_text)
    assert len(compressed) < len(original_text)
    assert NDSOverlayCompressor.is_compressed(compressed, flags=0x01000000) is True

    decompressed = NDSOverlayCompressor.decompress(compressed, flags=0x01000000)
    assert decompressed == original_text


def test_overlay_manager_replace_and_relocate():
    # Build minimal dummy NDS ROM
    rom_data = bytearray(0x4000)
    # Header minimal structure
    rom_data[0x50:0x54] = (0x1000).to_bytes(4, "little")  # arm9 overlay offset
    rom_data[0x54:0x58] = (64).to_bytes(4, "little")      # arm9 overlay size (2 entries)
    rom_data[0x48:0x4C] = (0x800).to_bytes(4, "little")   # FAT offset
    rom_data[0x4C:0x50] = (32).to_bytes(4, "little")      # FAT size (4 files)

    # Write FAT entry for file_id 0 at 0x800
    rom_data[0x800:0x804] = (0x2000).to_bytes(4, "little")  # top
    rom_data[0x804:0x808] = (0x2200).to_bytes(4, "little")  # bottom (512 bytes)

    # Write overlay table entry at 0x1000
    entry_bytes = make_dummy_overlay_entry_bytes(overlay_id=0, file_id=0, flags=0)
    rom_data[0x1000:0x1020] = entry_bytes

    # Write file payload at 0x2000
    rom_data[0x2000:0x2010] = b"Original Overlay"

    rom = NDSRom(bytes(rom_data))
    mgr = NDSOverlayManager(rom)

    extracted = mgr.extract_overlay(0, processor="arm9", decompress=False)
    assert extracted[:16] == b"Original Overlay"

    # Replace with smaller payload (fits in place)
    new_script = b"Translated Dialogue Text"
    report = mgr.replace_overlay_data(0, new_script, processor="arm9", compress=False)
    assert isinstance(report, OverlayAllocationReport)
    assert report.overlay_id == 0

    re_extracted = mgr.extract_overlay(0, processor="arm9", decompress=False)
    assert re_extracted[:len(new_script)] == new_script
