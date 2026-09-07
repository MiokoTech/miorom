import struct
import pytest

from miorom.helper import (
    StringPoolBuilder,
    TagConverter,
    BinaryRelocator,
    DualTableHelper,
)


def test_string_pool_builder():
    builder = StringPoolBuilder(encoding="utf-16-be", endian=">", stride=4, base_offset=0x100)
    idx0 = builder.add("Hello")
    idx1 = builder.add("World")

    assert idx0 == 0
    assert idx1 == 1
    assert builder.count == 2
    assert builder.get_offset(0) == 0x100

    table_bytes, pool_bytes = builder.build()
    assert len(table_bytes) == 8  # 2 * 4 bytes
    assert len(pool_bytes) > 0

    # Verify first pointer in table_bytes
    p0 = struct.unpack(">I", table_bytes[:4])[0]
    assert p0 == 0x100

    # Verify combined
    combined = builder.build_combined(padding_between=4)
    assert len(combined) == len(table_bytes) + 4 + len(pool_bytes)


def test_tag_converter():
    tc = TagConverter({
        "<PLAYER>": "[0x30e9][0x30b0][0x30ca]",
        "<COLOR>": "[0xff20]",
        "<ENTER>": "\n",
    })

    # Test text apply / revert
    orig = "Hello [0x30e9][0x30b0][0x30ca]!\nWelcome."
    applied = tc.apply(orig)
    assert applied == "Hello <PLAYER>!<ENTER>Welcome."
    reverted = tc.revert(applied)
    assert reverted == orig

    # Test UTF-16 encode / decode with hex escapes
    encoded = tc.encode_utf16("Item <COLOR>Sword")
    decoded = tc.decode_utf16(encoded)
    assert "<COLOR>" in decoded
    assert "Sword" in decoded


def test_binary_relocator():
    orig = bytearray(b"\x00" * 100)
    # Put some 32-bit header values:
    # offset 4: size (100)
    # offset 8: section 2 offset (50)
    struct.pack_into(">I", orig, 4, 100)
    struct.pack_into(">I", orig, 8, 50)

    reloc = BinaryRelocator(orig, endian=">")
    # Replace 10 bytes with 25 bytes (delta = +15)
    delta = reloc.replace_range(offset=20, old_size=10, new_data=b"A" * 25)
    assert delta == 15
    assert len(reloc) == 115

    # Shift header fields
    new_sz = reloc.shift_u32(4, delta)
    new_sec2 = reloc.shift_u32(8, delta)
    assert new_sz == 115
    assert new_sec2 == 65

    # Align
    added = reloc.align_to(32)
    assert len(reloc) % 32 == 0


def test_dual_table_helper_roundtrip():
    t1 = ["Yes", "No", "Cancel"]
    t2 = ["Attack", "Defense", "Magic", "Max HP"]

    repacked = DualTableHelper.repack(t1, t2, encoding="utf-16-be", endian=">")
    assert len(repacked) % 32 == 0  # 32-byte aligned

    ext1, ext2 = DualTableHelper.extract(repacked, encoding="utf-16-be", endian=">")
    assert ext1 == t1
    assert ext2 == t2
