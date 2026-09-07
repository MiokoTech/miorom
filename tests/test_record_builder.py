import struct
import pytest
from miorom.core import RecordBuilder


def test_record_builder_integers_and_floats():
    b = RecordBuilder("<")
    b.u8(0x12).i8(-5).u16(0x1234).i16(-100).u32(0x12345678).i32(-500).u64(0xDEADBEEFCAFE).f32(3.14)
    data = b.build()

    assert b.size == len(data)
    assert len(data) == 1 + 1 + 2 + 2 + 4 + 4 + 8 + 4  # 22 bytes
    assert data[0] == 0x12


def test_record_builder_strings_and_alignment():
    b = RecordBuilder("<")
    # Fixed string: length 10, text "HELLO" -> 5 bytes text + 5 null bytes
    b.fixed_str("HELLO", length=10)
    assert b.size == 10
    assert b.build() == b"HELLO\x00\x00\x00\x00\x00"

    # Fixed string truncation: text "LONGER_TEXT" with length 4 -> "LONG"
    b_trunc = RecordBuilder("<").fixed_str("LONGER_TEXT", length=4)
    assert b_trunc.build() == b"LONG"

    # Pascal string (1 byte length prefix)
    b_p1 = RecordBuilder("<").pascal_str("TEST", length_size=1)
    assert b_p1.build() == b"\x04TEST"

    # Pascal string (2 byte length prefix)
    b_p2 = RecordBuilder("<").pascal_str("TEST", length_size=2)
    assert b_p2.build() == b"\x04\x00TEST"

    # Pascal string (4 byte length prefix)
    b_p4 = RecordBuilder("<").pascal_str("TEST", length_size=4)
    assert b_p4.build() == b"\x04\x00\x00\x00TEST"

    # Alignment test
    b_align = RecordBuilder("<").u8(0xFF).align(4, pad_byte=0xAA)
    assert b_align.build() == b"\xFF\xAA\xAA\xAA"
    assert b_align.size == 4

    # Bytes field
    b_raw = RecordBuilder("<").bytes_field(b"\x01\x02\x03")
    assert b_raw.build() == b"\x01\x02\x03"
