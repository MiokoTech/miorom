import pytest
from miorom.compression import (
    KosinskiCodec,
    Kosinski,
    NemesisCodec,
    Nemesis,
    compress,
)
from miorom.errors import CompressionError


def test_kosinski_roundtrip_text():
    data = (
        b"Sonic the Hedgehog (1991) - Genesis / Mega Drive. "
        b"Gotta go fast! Ring collection, Green Hill Zone. "
    ) * 10
    compressed = KosinskiCodec.compress(data)
    assert len(compressed) < len(data)

    decompressed = KosinskiCodec.decompress(compressed)
    assert decompressed == data


def test_kosinski_roundtrip_varied_patterns():
    # Mix of single literals, short repeats (inline), medium repeats (full), long repeats (ext)
    data = (
        b"\x00" * 50
        + b"\xAA\xBB\xCC\xDD" * 8
        + bytes(range(64))
        + b"\x12\x34\x56" * 15
        + b"\xFF" * 100
    )
    compressed = Kosinski.compress(data)
    decompressed = Kosinski.decompress(compressed)
    assert decompressed == data


def test_kosinski_dispatch():
    data = b"MioROM Sega Genesis Kosinski Compression Test Data" * 8
    compressed = compress(data, "kosinski")
    decompressed = Kosinski.decompress(compressed)
    assert decompressed == data


def test_kosinski_error_handling():
    with pytest.raises(CompressionError):
        Kosinski.decompress(b"")

    with pytest.raises(CompressionError):
        # Truncated descriptor without terminator
        Kosinski.decompress(b"\x00\x00")


def test_nemesis_roundtrip_normal():
    # 2 tiles (64 bytes)
    tile1 = bytes([0x12, 0x12, 0x34, 0x34] * 8)
    tile2 = bytes([0x00, 0x00, 0x55, 0x55] * 8)
    tiles = tile1 + tile2

    compressed = NemesisCodec.compress(tiles, xor_mode=False)
    assert len(compressed) < len(tiles)

    decompressed = NemesisCodec.decompress(compressed)
    assert decompressed == tiles


def test_nemesis_roundtrip_xor_mode():
    # Gradient / striped pattern that compresses well with XOR mode
    tile = bytes([(i % 16) | ((i % 16) << 4) for i in range(32)])
    tiles = tile * 4

    compressed = Nemesis.compress(tiles, xor_mode=True)
    decompressed = Nemesis.decompress(compressed)
    assert decompressed == tiles


def test_nemesis_dispatch():
    tiles = b"\x00\x11\x22\x33" * 16  # 64 bytes = 2 tiles
    compressed = compress(tiles, "nemesis")
    decompressed = Nemesis.decompress(compressed)
    assert decompressed == tiles


def test_nemesis_error_handling():
    with pytest.raises(CompressionError):
        Nemesis.decompress(b"")

    with pytest.raises(CompressionError):
        # Invalid single byte
        Nemesis.decompress(b"\x00")
