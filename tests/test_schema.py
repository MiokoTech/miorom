import struct
import pytest
from miorom.core.schema import BinaryStruct, U8, U16, U32, FixedString, Array


class EntryHeader(BinaryStruct):
    _endian = "<"
    magic = FixedString(4, default="WG01")
    flags = U16(default=0x0001)
    entry_count = U16(default=2)


class SubEntry(BinaryStruct):
    _endian = "<"
    offset = U32()
    size = U32()


class FileContainer(BinaryStruct):
    _endian = "<"
    header = EntryHeader()
    # Dynamic array referencing count from header.entry_count
    entries = Array(SubEntry, count=2)


def test_schema_fixed_size_and_offsets():
    assert EntryHeader.sizeof() == 8
    assert EntryHeader.offset_of("magic") == 0
    assert EntryHeader.offset_of("flags") == 4
    assert EntryHeader.offset_of("entry_count") == 6


def test_schema_pack_and_unpack():
    hdr = EntryHeader(magic="TEST", flags=0x1234, entry_count=5)
    packed = hdr.to_bytes()

    assert len(packed) == 8
    assert packed[:4] == b"TEST"
    assert struct.unpack_from("<H", packed, 4)[0] == 0x1234
    assert struct.unpack_from("<H", packed, 6)[0] == 5

    unpacked = EntryHeader.from_bytes(packed)
    assert unpacked.magic == "TEST"
    assert unpacked.flags == 0x1234
    assert unpacked.entry_count == 5


def test_schema_nested_struct_and_arrays():
    raw = bytearray()
    # Header: "NARC", flags=0, count=2
    raw.extend(b"NARC\x00\x00\x02\x00")
    # Entry 1: off=0x100, size=0x20
    raw.extend(struct.pack("<II", 0x100, 0x20))
    # Entry 2: off=0x120, size=0x40
    raw.extend(struct.pack("<II", 0x120, 0x40))

    container = FileContainer.from_bytes(bytes(raw))
    assert container.header.magic == "NARC"
    assert len(container.entries) == 2
    assert container.entries[0].offset == 0x100
    assert container.entries[0].size == 0x20
    assert container.entries[1].offset == 0x120
    assert container.entries[1].size == 0x40

    # Roundtrip to_bytes
    assert container.to_bytes() == bytes(raw)


from enum import IntEnum

from miorom.core.schema import (
    Alignment,
    Bitfield,
    ChecksumField,
    EnumField,
    If,
    Padding,
    PascalString,
    SentinelArray,
)


class Compression(IntEnum):
    NONE = 0
    LZ10 = 0x10
    LZ11 = 0x11


class ComplexHeader(BinaryStruct):
    compression = EnumField(U8(), Compression)
    flags = Bitfield(U8(), {"visible": 1, "locked": 2}, default=0)
    name = PascalString(U8())
    conditional = If(lambda struct: struct.flags.visible, U16(), default=0)
    pad = Padding(2)
    items = SentinelArray(U16(), sentinel=b"\xff\xff")
    checksum = ChecksumField(1)


class Aligned(BinaryStruct):
    value = U8()
    aligned_value = Alignment(4)
    result = U8()


def test_schema_enum_bitfield_conditional_pascal_and_sentinel():
    raw = bytes([
        0x11,
        0x03,
        0x04,
        ord("T"),
        ord("E"),
        ord("S"),
        ord("T"),
        0xAB,
        0xCD,
        0x00,
        0x00,
        0x01,
        0x00,
        0x02,
        0x00,
        0xFF,
        0xFF,
        0xD1,
    ])

    parsed = ComplexHeader.from_bytes(raw)
    assert parsed.compression is Compression.LZ11
    assert parsed.flags.visible is True
    assert parsed.flags.locked is True
    assert parsed.name == "TEST"
    assert parsed.conditional == 0xCDAB
    assert parsed.items == [1, 2]

    aligned = Aligned.from_bytes(bytes([0x0A, 0x00, 0x00, 0x00, 0x2B]))
    assert aligned.value == 0x0A
    assert aligned.aligned_value == b"\x00\x00\x00"
    assert aligned.result == 0x2B


def test_schema_checksum_uses_preceding_bytes():
    class Checksummed(BinaryStruct):
        value = U16()
        checksum = ChecksumField(1)

    data = bytes([0x34, 0x12, 0x46])
    parsed = Checksummed.from_bytes(data)
    assert parsed.value == 0x1234
    assert parsed.checksum == 0x46
    assert Checksummed(value=0x1234).to_bytes() == data
