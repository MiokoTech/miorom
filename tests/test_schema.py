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
