import pytest
from miorom.compression import EnigmaCodec, Enigma, compress
from miorom.errors import CompressionError


def test_enigma_sega_retro_official_vector():
    # Official Sega Retro reference vector
    vector = bytes([0x07, 0x0C, 0x00, 0x00, 0x00, 0x10, 0x05, 0x3D, 0x11, 0x8F, 0xE0])
    decompressed = Enigma.decompress(vector, starting_art_tile=0)

    expected = bytes.fromhex(
        "0000 0001 0010 0010 0010 0010 "
        "4018 4017 4016 4015 4014 4013 4012 4011 4010"
    )
    assert decompressed == expected


def test_enigma_sega_retro_vector_with_art_tile():
    vector = bytes([0x07, 0x0C, 0x00, 0x00, 0x00, 0x10, 0x05, 0x3D, 0x11, 0x8F, 0xE0])
    decompressed = Enigma.decompress(vector, starting_art_tile=0x1000)

    expected = bytes.fromhex(
        "1000 1001 1010 1010 1010 1010 "
        "5018 5017 5016 5015 5014 5013 5012 5011 5010"
    )
    assert decompressed == expected


def test_enigma_roundtrip_plane_map():
    # Construct a realistic Sega Genesis plane tilemap (32x4 words = 128 words = 256 bytes)
    words = []
    # Incremental row
    words.extend(range(0x0020, 0x0030))
    # Repeated literal background tile
    words.extend([0x0005] * 16)
    # Inline flipped tiles (priority + palette 1)
    words.extend([(0x6000 | i) for i in range(16)])
    # Decremental sequence
    words.extend(range(0x0080, 0x0070, -1))

    raw_bytes = bytearray()
    for w in words:
        raw_bytes.extend([(w >> 8) & 0xFF, w & 0xFF])
    data = bytes(raw_bytes)

    compressed = EnigmaCodec.compress(data)
    assert len(compressed) < len(data)

    decompressed = EnigmaCodec.decompress(compressed)
    assert decompressed == data


def test_enigma_dispatch():
    words = [0x0010] * 20 + list(range(0x0020, 0x0030))
    raw = bytearray()
    for w in words:
        raw.extend([(w >> 8) & 0xFF, w & 0xFF])
    data = bytes(raw)

    compressed = compress(data, "enigma")
    decompressed = Enigma.decompress(compressed)
    assert decompressed == data


def test_enigma_error_handling():
    with pytest.raises(CompressionError):
        Enigma.decompress(b"")

    with pytest.raises(CompressionError):
        # Odd number of bytes in compress
        Enigma.compress(b"\x00\x01\x02")
