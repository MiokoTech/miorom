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

def test_binary_reader_open_file_with_mmap(tmp_path):
    path = tmp_path / "rom.bin"
    payload = b"\x12\x34\x56\x78payload"
    path.write_bytes(payload)

    with BinaryReader.open_file(path, endian=">", use_mmap=True) as reader:
        assert reader.read_u32() == 0x12345678
        assert reader.read_string(null_terminated=False) == "payload"

def test_binary_reader_open_file_without_mmap(tmp_path):
    path = tmp_path / "rom.bin"
    path.write_bytes(b"\x78\x56\x34\x12AB")

    with BinaryReader.open_file(path, endian="<", use_mmap=False) as reader:
        assert reader.read_u32() == 0x12345678
        assert reader.read_bytes(2) == b"AB"


def test_binary_reader_static_unpack():
    data = b"\x12\x34\x56\x78\x9A\xBC\xDE\xF0\x80\xFF\x40\x49\x0f\xdb"
    assert BinaryReader.unpack_u8(data, 0) == 0x12
    assert BinaryReader.unpack_s8(b"\xFF", 0) == -1
    assert BinaryReader.unpack_u16(data, 0, endian=">") == 0x1234
    assert BinaryReader.unpack_u16(data, 0, endian="<") == 0x3412
    assert BinaryReader.unpack_s16(b"\xFF\xFE", 0, endian=">") == -2
    assert BinaryReader.unpack_u32(data, 0, endian=">") == 0x12345678
    assert BinaryReader.unpack_u32(data, 0, endian="<") == 0x78563412
    assert BinaryReader.unpack_s32(b"\xFF\xFF\xFF\xFD", 0, endian=">") == -3
    assert BinaryReader.unpack_u64(data, 0, endian=">") == 0x123456789ABCDEF0
    assert BinaryReader.unpack_s64(b"\xFF" * 8, 0, endian=">") == -1
    # Float & Double
    flt_bytes = BinaryWriter.pack_float(3.140000104904175, endian=">")
    assert abs(BinaryReader.unpack_float(flt_bytes, 0, endian=">") - 3.14) < 1e-5
    dbl_bytes = BinaryWriter.pack_double(3.141592653589793, endian=">")
    assert abs(BinaryReader.unpack_double(dbl_bytes, 0, endian=">") - 3.141592653589793) < 1e-12


def test_binary_writer_static_pack_and_pack_into():
    assert BinaryWriter.pack_u8(0xFF) == b"\xFF"
    assert BinaryWriter.pack_s8(-1) == b"\xFF"
    assert BinaryWriter.pack_u16(0x1234, endian=">") == b"\x12\x34"
    assert BinaryWriter.pack_u16(0x1234, endian="<") == b"\x34\x12"
    assert BinaryWriter.pack_s16(-2, endian=">") == b"\xFF\xFE"
    assert BinaryWriter.pack_u32(0x12345678, endian=">") == b"\x12\x34\x56\x78"
    assert BinaryWriter.pack_u32(0x12345678, endian="<") == b"\x78\x56\x34\x12"
    assert BinaryWriter.pack_s32(-1, endian=">") == b"\xFF\xFF\xFF\xFF"
    assert BinaryWriter.pack_u64(0x0102030405060708, endian=">") == b"\x01\x02\x03\x04\x05\x06\x07\x08"
    assert BinaryWriter.pack_s64(-1, endian=">") == b"\xFF" * 8

    # pack_into
    buf = bytearray(16)
    BinaryWriter.pack_into_u8(buf, 0, 0xAA)
    BinaryWriter.pack_into_s8(buf, 1, -1)
    BinaryWriter.pack_into_u16(buf, 2, 0xBEEF, endian=">")
    BinaryWriter.pack_into_s16(buf, 4, -100, endian="<")
    BinaryWriter.pack_into_u32(buf, 6, 0xCAFEBABE, endian=">")
    BinaryWriter.pack_into_s32(buf, 10, -500, endian=">")

    assert buf[0] == 0xAA
    assert BinaryReader.unpack_s8(buf, 1) == -1
    assert BinaryReader.unpack_u16(buf, 2, endian=">") == 0xBEEF
    assert BinaryReader.unpack_s16(buf, 4, endian="<") == -100
    assert BinaryReader.unpack_u32(buf, 6, endian=">") == 0xCAFEBABE
    assert BinaryReader.unpack_s32(buf, 10, endian=">") == -500


def test_binary_format_gateway():
    assert BinaryReader.calcsize("<IHH") == 8
    packed = BinaryWriter.pack("<IHH", 0x12345678, 0xAAAA, 0x5555)
    assert len(packed) == 8
    unpacked = BinaryReader.unpack("<IHH", packed)
    assert unpacked == (0x12345678, 0xAAAA, 0x5555)

    buf = bytearray(12)
    BinaryWriter.pack_into(">IH", buf, 2, 0xCAFE, 0x12)
    val1, val2 = BinaryReader.unpack_from(">IH", buf, 2)
    assert val1 == 0xCAFE
    assert val2 == 0x12


