import pytest
import struct
from miorom.platforms.gc.dol import DolFile, DolSection


def make_dummy_dol() -> bytes:
    """Construct a minimal valid GameCube DOL binary with text and data sections."""
    header = bytearray(0x100)

    # Text section 0
    text0_offset = 0x100
    text0_addr = 0x80003100
    text0_size = 0x80
    struct.pack_into(">I", header, 0, text0_offset)
    struct.pack_into(">I", header, 0x48, text0_addr)
    struct.pack_into(">I", header, 0x90, text0_size)

    # Data section 0
    data0_offset = 0x180
    data0_addr = 0x80010000
    data0_size = 0x40
    struct.pack_into(">I", header, 0x1C, data0_offset)
    struct.pack_into(">I", header, 0x64, data0_addr)
    struct.pack_into(">I", header, 0xAC, data0_size)

    # BSS and Entry point
    struct.pack_into(">III", header, 0xD8, 0x80020000, 0x1000, text0_addr)

    body = bytearray(header)
    # Text payload: NOPs and blr
    text_data = b"\x60\x00\x00\x00" * (text0_size // 4)
    data_data = b"MioROM GameCube DOL Test Data 12345" + b"\x00" * (data0_size - 35)

    body.extend(text_data)
    body.extend(data_data)
    return bytes(body)


def test_dol_parse_and_properties():
    raw = make_dummy_dol()
    dol = DolFile.from_bytes(raw)

    assert len(dol.text_sections) == 1
    assert len(dol.data_sections) == 1
    assert dol.entry_point == 0x80003100
    assert dol.bss_address == 0x80020000
    assert dol.bss_size == 0x1000

    sec_t = dol.text_sections[0]
    assert sec_t.is_text is True
    assert sec_t.is_data is False
    assert sec_t.address == 0x80003100
    assert sec_t.size == 0x80

    sec_d = dol.data_sections[0]
    assert sec_d.is_text is False
    assert sec_d.is_data is True
    assert sec_d.address == 0x80010000
    assert sec_d.size == 0x40


def test_dol_address_offset_translation():
    raw = make_dummy_dol()
    dol = DolFile.from_bytes(raw)

    # Valid RAM address to offset
    assert dol.address_to_offset(0x80003100) == 0x100
    assert dol.address_to_offset(0x80003110) == 0x110
    assert dol.address_to_offset(0x80010000) == 0x180

    # Unmapped address
    assert dol.address_to_offset(0x80050000) is None

    # Offset to RAM address
    assert dol.offset_to_address(0x100) == 0x80003100
    assert dol.offset_to_address(0x180) == 0x80010000
    assert dol.offset_to_address(0x080) is None


def test_dol_memory_read_write():
    raw = make_dummy_dol()
    dol = DolFile.from_bytes(raw)

    # Read memory
    data_snippet = dol.read_memory(0x80010000, 6)
    assert data_snippet == b"MioROM"

    # Write memory
    dol.write_memory(0x80010000, b"ZakROM")
    assert dol.read_memory(0x80010000, 6) == b"ZakROM"

    # Read out of bounds raises ValueError
    with pytest.raises(ValueError):
        dol.read_memory(0x80010030, 0x20)

    # Unmapped address raises ValueError
    with pytest.raises(ValueError):
        dol.read_memory(0x70000000, 4)


def test_dol_add_section_and_code_cave():
    raw = make_dummy_dol()
    dol = DolFile.from_bytes(raw)

    # Add custom text section
    custom_code = b"\x38\x60\x00\x01\x4e\x80\x00\x20"  # li r3, 1; blr
    new_sec = dol.add_section(is_text=True, address=0x80005000, data=custom_code)
    assert new_sec.index == 1
    assert new_sec.is_text is True
    assert new_sec.address == 0x80005000
    assert new_sec.offset % 32 == 0
    assert dol.read_memory(0x80005000, len(custom_code)) == custom_code

    # Allocate code cave
    addr, off = dol.allocate_code_cave(size=64, is_text=True)
    assert addr >= 0x80005000
    assert off % 32 == 0
    assert dol.read_memory(addr, 64) == b"\x00" * 64


def test_dol_roundtrip_serialization(tmp_path):
    raw = make_dummy_dol()
    dol = DolFile.from_bytes(raw)

    # Serialize to bytes
    serialized = dol.to_bytes()
    assert len(serialized) == len(raw)
    assert serialized == raw

    # Test file roundtrip
    out_file = tmp_path / "test.dol"
    dol.save(out_file)
    reloaded = DolFile.from_file(out_file)

    assert reloaded.entry_point == dol.entry_point
    assert len(reloaded.text_sections) == len(dol.text_sections)
    assert len(reloaded.data_sections) == len(dol.data_sections)
    assert reloaded.to_bytes() == raw
