import struct
import pytest
from miorom.core.mapper import ByteOffsetMapper
from miorom.core.buffer import RelocatableBuffer


def test_byte_offset_mapper_basic():
    old_data = b"ABCDEFGHIJ0123456789"  # 20 bytes
    # Replace "0123456789" (at offset 10) with something longer (15 bytes)
    new_data = b"ABCDEFGHIJ__EXPANDED_DATA__"  # 27 bytes (+7 delta)

    mapper = ByteOffsetMapper(old_data, new_data)

    # Offsets before 10 should be unchanged
    assert mapper.map_offset(0) == 0
    assert mapper.map_offset(5) == 5
    assert mapper.map_offset(9) == 9

    # Offsets at end of old_data (offset 20) should shift by +7 -> 27
    assert mapper.map_offset(20) == 27


def test_byte_offset_mapper_remap_pointers():
    old_data = b"HEADER\x00\x00" + b"TEXT1\x00" + b"TEXT2\x00"
    # Target 1 is at 8 ("TEXT1"), Target 2 is at 14 ("TEXT2")
    # Expand TEXT1 to "TEXT1_MUCH_LONGER\x00" (+12 bytes)
    new_data = b"HEADER\x00\x00" + b"TEXT1_MUCH_LONGER\x00" + b"TEXT2\x00"

    mapper = ByteOffsetMapper(old_data, new_data)

    old_ptrs = [8, 14]
    new_ptrs = mapper.remap_pointers(old_ptrs)

    assert new_ptrs[0] == 8  # TEXT1 start hasn't shifted
    assert new_ptrs[1] == 14 + 12  # TEXT2 shifted by +12 bytes


def test_relocatable_buffer_chained_edits_and_anchors():
    # Construct a simulated entry:
    # 0x00 - 0x03: Size field (u16 at 0x00, total size)
    # 0x04 - 0x05: Pointer to String 1 (u16 at 0x04)
    # 0x06 - 0x07: Pointer to String 2 (u16 at 0x06)
    # 0x08 - 0x13: String 1 ("Hello\x00") -> at 0x08
    # 0x14 - 0x1F: String 2 ("World\x00") -> at 0x14
    # Total size: 0x20 (32 bytes)
    raw = bytearray(32)
    struct.pack_into("<H", raw, 0x00, 32)      # Size field
    struct.pack_into("<H", raw, 0x04, 0x08)    # Pointer to String 1
    struct.pack_into("<H", raw, 0x06, 0x14)    # Pointer to String 2
    raw[0x08:0x0E] = b"Hello\x00"
    raw[0x14:0x1A] = b"World\x00"

    buf = RelocatableBuffer(bytes(raw))

    # Register fields
    buf.register_anchored_field(pos=0x00, size=2, endian="<", anchor_type="size_delta")
    buf.register_pointer(pos=0x04, size=2, endian="<")
    buf.register_pointer(pos=0x06, size=2, endian="<")

    # Perform chained edits:
    # Edit 1: replace "Hello" with "Halo Dunia yang Indah" (+16 bytes)
    buf.replace_text("Hello", "Halo Dunia yang Indah")

    # Edit 2: replace "World" with "Bumi Tercinta" (+8 bytes)
    buf.replace_text("World", "Bumi Tercinta")

    # Total delta should be +24 bytes
    assert buf.delta == 24
    assert buf.current_size == 32 + 24

    # Relocate all pointers and fields
    report = buf.relocate_all()
    assert report["pointers_updated"] == 2
    assert report["fields_updated"] == 1

    final_data = buf.to_bytes()

    # Verify updated size field at 0x00
    new_size = struct.unpack_from("<H", final_data, 0x00)[0]
    assert new_size == 32 + 24  # 56 bytes

    # Verify updated pointer to String 1 (starts at 0x08)
    ptr1 = struct.unpack_from("<H", final_data, 0x04)[0]
    assert ptr1 == 0x08

    # Verify updated pointer to String 2 (shifted by Edit 1's +16 bytes)
    ptr2 = struct.unpack_from("<H", final_data, 0x06)[0]
    assert ptr2 == 0x14 + 16

    # Verify string contents at those pointers
    assert final_data[ptr1:ptr1+21] == b"Halo Dunia yang Indah"
    assert final_data[ptr2:ptr2+13] == b"Bumi Tercinta"


def test_relocatable_buffer_ambiguity_detection():
    data = b"HEADER\x00Yes\x00MIDDLE\x00Yes\x00FOOTER\x00"
    buf = RelocatableBuffer(data)

    # First occurrence (index 0)
    pos1, delta1 = buf.replace_text("Yes", "Ya", occurrence=0)
    assert pos1 == 7
    assert b"HEADER\x00Ya\x00MIDDLE\x00Yes\x00FOOTER\x00" == buf.to_bytes()

    # Out of range occurrence
    with pytest.raises(IndexError):
        buf.replace_text("Ya", "Nope", occurrence=5)
