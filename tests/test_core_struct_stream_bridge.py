import pytest
from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import (
    BinaryStruct,
    U8,
    U16,
    U32,
    RawBytes,
    Padding,
    PascalString,
    Array,
    If,
)


class MockHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)
    version = U16()
    flags = U16()
    payload_size = U32()


class MockDynamicItemStruct(BinaryStruct):
    _endian = ">"
    item_id = U16()
    name = PascalString(length_type=U8)
    has_extra = U8()
    extra_val = If(lambda ctx: ctx.has_extra != 0, U16())


def test_fixed_struct_stream_bridge():
    hdr = MockHeaderStruct(magic=b"TEST", version=0x0102, flags=0x8000, payload_size=1024)

    writer = BinaryWriter(endian=">")
    writer.write_u32(0xDEADBEEF)  # Prefix
    writer.write_struct(hdr)       # Write struct
    writer.write_u32(0xCAFEBABE)  # Suffix

    raw = writer.to_bytes()
    assert len(raw) == 4 + MockHeaderStruct.sizeof() + 4

    reader = BinaryReader(raw, endian=">")
    prefix = reader.read_u32()
    assert prefix == 0xDEADBEEF

    read_hdr = reader.read_struct(MockHeaderStruct)
    assert read_hdr.magic == b"TEST"
    assert read_hdr.version == 0x0102
    assert read_hdr.flags == 0x8000
    assert read_hdr.payload_size == 1024

    suffix = reader.read_u32()
    assert suffix == 0xCAFEBABE
    assert reader.remaining == 0


def test_dynamic_struct_stream_bridge():
    item1 = MockDynamicItemStruct(item_id=1, name="Sword", has_extra=1, extra_val=999)
    item2 = MockDynamicItemStruct(item_id=2, name="Shield", has_extra=0, extra_val=None)

    writer = BinaryWriter(endian=">")
    writer.write_struct(item1)
    writer.write_struct(item2)

    raw = writer.to_bytes()

    reader = BinaryReader(raw, endian=">")
    r_item1 = reader.read_struct(MockDynamicItemStruct)
    assert r_item1.item_id == 1
    assert r_item1.name == "Sword"
    assert r_item1.has_extra == 1
    assert r_item1.extra_val == 999

    r_item2 = reader.read_struct(MockDynamicItemStruct)
    assert r_item2.item_id == 2
    assert r_item2.name == "Shield"
    assert r_item2.has_extra == 0
    assert r_item2.extra_val is None

    assert reader.remaining == 0
