import struct
import pytest

from miorom.compression import (
    SaxmanCodec,
    Saxman,
    ComperCodec,
    Comper,
    compress,
)
from miorom.errors import CompressionError


def test_saxman_empty():
    # With size header (2 bytes)
    comp_sized = Saxman.compress(b"", with_size=True)
    assert len(comp_sized) == 2
    assert Saxman.decompress(comp_sized) == b""

    # Headerless
    comp_raw = Saxman.compress(b"", with_size=False)
    assert comp_raw == b""
    assert Saxman.decompress(comp_raw, with_size=False) == b""


def test_saxman_roundtrip_literals():
    data = b"Hello Sega Genesis Sound Driver!"
    compressed = Saxman.compress(data, with_size=True)
    decompressed = Saxman.decompress(compressed)
    assert decompressed == data


def test_saxman_roundtrip_repetitive():
    data = (b"SEGA_SONIC_SOUND_DATA_BANK_PATTERN_123456789\x00\xFF") * 50
    compressed = Saxman.compress(data, with_size=True)
    assert len(compressed) < len(data)
    decompressed = Saxman.decompress(compressed)
    assert decompressed == data


def test_saxman_header_modes():
    data = b"Data with or without header" * 10
    # Explicit with_size=False
    comp_no_hdr = Saxman.compress(data, with_size=False)
    dec_no_hdr = Saxman.decompress(comp_no_hdr, with_size=False)
    assert dec_no_hdr == data

    # Explicit with_size=True
    comp_hdr = Saxman.compress(data, with_size=True)
    dec_hdr = Saxman.decompress(comp_hdr, with_size=True)
    assert dec_hdr == data

    # Auto-detection
    dec_auto = Saxman.decompress(comp_hdr)
    assert dec_auto == data


def test_comper_empty():
    comp = Comper.compress(b"")
    decomp = Comper.decompress(comp)
    assert decomp == b""


def test_comper_roundtrip_literals():
    # Even-length data (36 bytes)
    even_data = b"16-bit Motorola 68000 word streams!!"
    assert len(even_data) % 2 == 0
    comp_even = Comper.compress(even_data)
    dec_even = Comper.decompress(comp_even)
    assert dec_even == even_data

    # Odd-length data (padded to 16-bit word boundary with trailing 0)
    odd_data = b"Odd byte string"
    comp_odd = Comper.compress(odd_data)
    dec_odd = Comper.decompress(comp_odd)
    assert dec_odd == odd_data + b"\x00"


def test_comper_roundtrip_repetitive():
    data = (b"\x12\x34\x56\x78\x9A\xBC\xDE\xF0") * 50
    compressed = Comper.compress(data)
    assert len(compressed) < len(data)
    decompressed = Comper.decompress(compressed)
    assert decompressed == data


def test_registry_dispatch():
    data = b"Registry dispatch test data for Saxman and Comper" * 8
    # Test dispatch through miorom.compression.compress
    comp_sax = compress(data, fmt="saxman")
    dec_sax = Saxman.decompress(comp_sax)
    assert dec_sax == data

    comp_comp = compress(data, fmt="comper")
    dec_comp = Comper.decompress(comp_comp)
    assert dec_comp == (data if len(data) % 2 == 0 else data + b"\x00")


def test_comper_error_handling():
    # Construct invalid backreference:
    # 16-bit descriptor 0x8000 (bit 15 = 1 dictionary match)
    # neg_dist = 0xFE (dist = (0x100 - 0xFE) * 2 = 4 bytes)
    # length_byte = 1 (num_words = 2, so 4 bytes)
    # But output buffer is empty (0 bytes), so copy_src < 0!
    bad_payload = struct.pack(">HBB", 0x8000, 0xFE, 1)
    with pytest.raises(CompressionError, match="out of bounds"):
        Comper.decompress(bad_payload)
