import struct
import pytest

from miorom.compression import MIO0Codec, MIO0, decompress, compress
from miorom.errors import CompressionError


def test_mio0_empty():
    compressed = MIO0.compress(b"")
    assert compressed.startswith(b"MIO0")
    decompressed = MIO0.decompress(compressed)
    assert decompressed == b""


def test_mio0_short_literals():
    data = b"Hello, MIO0!"
    compressed = MIO0.compress(data)
    assert compressed.startswith(b"MIO0")
    decompressed = MIO0.decompress(compressed)
    assert decompressed == data


def test_mio0_rle_data():
    data = b"X" * 150 + b"Y" * 80 + b"\x00" * 300
    compressed = MIO0.compress(data)
    assert len(compressed) < len(data)
    decompressed = MIO0.decompress(compressed)
    assert decompressed == data


def test_mio0_periodic_patterns():
    data = (b"\x12\x34\x56") * 60 + (b"\xAB\xCD") * 40
    compressed = MIO0.compress(data)
    assert len(compressed) < len(data)
    decompressed = MIO0.decompress(compressed)
    assert decompressed == data


def test_mio0_golden_specimen():
    """
    Handcrafted MIO0 payload:
    Decompressed length: 8 bytes
    Uncompressed byte: 'A' (0x41)
    Compressed token: length 7, distance 1 -> token = ((7 - 3) << 12) | 0 = 0x4000
    Layout byte: 0x80 (bit 7 = 1 for literal, bit 6 = 0 for LZ token)
    Result: b"AAAAAAAA"
    """
    header = b"MIO0" + struct.pack(">III", 8, 20, 22)
    layout = b"\x80"
    pad = b"\x00\x00\x00"  # pad to offset 20
    comp = struct.pack(">H", 0x4000)  # offset 20
    uncomp = b"\x41"  # offset 22
    payload = header + layout + pad + comp + uncomp

    decompressed = MIO0Codec.decompress(payload)
    assert decompressed == b"AAAAAAAA"


def test_mio0_registry_dispatch():
    data = b"Nintendo 64 Super Mario 64 texture test data" * 10
    compressed = compress(data, fmt="mio0")
    assert compressed[:4] == b"MIO0"
    # Auto-detect through magic
    decompressed = decompress(compressed)
    assert decompressed == data


def test_mio0_corrupted_errors():
    # Too short for header
    with pytest.raises(CompressionError, match="too short"):
        MIO0.decompress(b"MIO0")

    # Invalid magic
    with pytest.raises(CompressionError, match="Invalid MIO0 magic"):
        MIO0.decompress(b"BAD0" + b"\x00" * 12)

    # Offset out of bounds
    corrupted_offset = b"MIO0" + struct.pack(">III", 100, 9999, 9999)
    with pytest.raises(CompressionError, match="past end of data"):
        MIO0.decompress(corrupted_offset)

    # Backreference out of bounds (dist > current output)
    # 1 layout byte 0x00 (first op is compressed token)
    # comp_offset = 20, token with dist = 50 (but output is empty)
    bad_comp = struct.pack(">H", (0 << 12) | 49)  # length 3, dist 50
    bad_payload = b"MIO0" + struct.pack(">III", 10, 20, 22) + b"\x00\x00\x00\x00" + bad_comp + b""
    with pytest.raises(CompressionError, match="out of bounds"):
        MIO0.decompress(bad_payload)
