import pytest
from miorom.core.bitstream import BitReader, BitWriter


def test_bit_reader_msb():
    data = bytes([0b10110010, 0b11001101])
    reader = BitReader(data, bit_order="msb")

    assert reader.total_bits == 16
    assert reader.bits_remaining == 16
    assert not reader.is_eof

    assert reader.read_bit() == 1
    assert reader.read_bit() == 0
    assert reader.read_bit() == 1
    assert reader.read_bit() == 1

    assert reader.read_bits(4) == 0b0010
    assert reader.read_bits(8) == 0b11001101
    assert reader.is_eof
    assert reader.bits_remaining == 0

    with pytest.raises(EOFError):
        reader.read_bit()


def test_bit_reader_lsb():
    data = bytes([0b10110010, 0b11001101])
    reader = BitReader(data, bit_order="lsb")

    # Byte 0: 0b10110010 -> LSB to MSB: 0, 1, 0, 0, 1, 1, 0, 1
    assert reader.read_bit() == 0
    assert reader.read_bit() == 1
    assert reader.read_bit() == 0
    assert reader.read_bit() == 0

    assert reader.read_bits(4) == 0b1011  # (1<<0) | (1<<1) | (0<<2) | (1<<3) = 11


def test_bit_reader_peek_and_skip():
    data = bytes([0xAA, 0x55])
    reader = BitReader(data, bit_order="msb")

    peeked = reader.peek_bits(4)
    assert peeked == 0xA
    assert reader.bits_read == 0

    reader.skip_bits(4)
    assert reader.bits_read == 4
    assert reader.read_bits(4) == 0xA

    reader.align_byte()
    assert reader.bits_read == 8
    assert reader.read_bits(8) == 0x55


def test_bit_reader_signed():
    # 0b11110000 = -16 in 8-bit signed
    data = bytes([0xF0])
    reader = BitReader(data, bit_order="msb")
    assert reader.read_signed_bits(4) == -1  # 0b1111 = -1
    assert reader.read_signed_bits(4) == 0   # 0b0000 = 0


def test_bit_writer_msb():
    writer = BitWriter(bit_order="msb")
    writer.write_bit(1)
    writer.write_bit(0)
    writer.write_bits(0b1100, 4)
    writer.write_bit(1)
    writer.write_bit(1)
    # Total 8 bits: 1, 0, 1, 1, 0, 0, 1, 1 -> 0b10110011 = 0xB3

    writer.write_bits(0x0F, 4)
    writer.align_byte(fill_bit=0)

    out = writer.to_bytes()
    assert len(out) == 2
    assert out[0] == 0xB3
    assert out[1] == 0xF0


def test_bit_writer_lsb():
    writer = BitWriter(bit_order="lsb")
    writer.write_bit(1)
    writer.write_bit(0)
    writer.write_bit(1)
    writer.write_bit(1)
    writer.align_byte(fill_bit=0)

    out = writer.to_bytes()
    assert len(out) == 1
    # 1 | (0<<1) | (1<<2) | (1<<3) = 1 + 4 + 8 = 13 = 0x0D
    assert out[0] == 0x0D


def test_bitstream_roundtrip():
    writer = BitWriter(bit_order="msb")
    writer.write_bits(42, 7)
    writer.write_signed_bits(-5, 5)
    writer.write_bits(0xABCD, 16)
    writer.write_bit(1)
    writer.align_byte(fill_bit=1)

    raw = writer.to_bytes()
    reader = BitReader(raw, bit_order="msb")
    assert reader.read_bits(7) == 42
    assert reader.read_signed_bits(5) == -5
    assert reader.read_bits(16) == 0xABCD
    assert reader.read_bit() == 1
