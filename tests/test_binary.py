import pytest
from miorom.core.binary import BinaryReader, BinaryWriter


def test_binary_write_and_read():
    writer = BinaryWriter(endian=">")
    writer.write_u32(0x12345678)
    writer.write_u16(0xABCD)
    writer.write_u8(0x42)
    writer.write_string("Hello", encoding="utf-8")
    writer.align(4, pad_byte=0xFF)

    raw = writer.to_bytes()
    assert len(raw) % 4 == 0

    reader = BinaryReader(raw, endian=">")
    assert reader.read_u32() == 0x12345678
    assert reader.read_u16() == 0xABCD
    assert reader.read_u8() == 0x42
    assert reader.read_string(encoding="utf-8") == "Hello"


def test_binary_context_at():
    data = b"\x00\x01\x02\x03\x04\x05\x06\x07"
    reader = BinaryReader(data, endian=">")
    assert reader.read_u8() == 0x00

    with reader.at(4):
        assert reader.read_u8() == 0x04

    # Current position should be restored
    assert reader.tell() == 1
    assert reader.read_u8() == 0x01
