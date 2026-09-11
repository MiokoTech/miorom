import pytest
from miorom.graphics.planar import (
    PlanarTileCodec,
    decode_planar_tile,
    encode_planar_tile,
    split_tile_bitplanes,
    combine_tile_bitplanes,
)
from miorom.errors import ParseError


@pytest.mark.parametrize("fmt,bpp,size", [
    ("mono_1bpp", 1, 8),
    ("nes_2bpp", 2, 16),
    ("gb_2bpp", 2, 16),
    ("snes_3bpp", 3, 24),
    ("snes_4bpp", 4, 32),
    ("genesis_4bpp", 4, 32),
    ("gba_4bpp", 4, 32),
    ("snes_8bpp", 8, 64),
    ("linear_8bpp", 8, 64),
])
def test_tile_roundtrip(fmt, bpp, size):
    max_val = (1 << bpp) - 1
    # Create distinct pixel pattern
    pixels = [(x * 3 + y * 5) % (max_val + 1) for y in range(8) for x in range(8)]

    encoded = PlanarTileCodec.encode_tile(pixels, fmt)
    assert len(encoded) == size

    decoded = PlanarTileCodec.decode_tile(encoded, fmt)
    assert decoded == pixels


def test_split_and_combine_bitplanes():
    fmt = "snes_4bpp"
    # Pixels using all 4 bitplanes
    pixels = [i % 16 for i in range(64)]
    tile_bytes = PlanarTileCodec.encode_tile(pixels, fmt)

    planes = PlanarTileCodec.split_bitplanes(tile_bytes, fmt)
    assert len(planes) == 4
    for p in planes:
        assert len(p) == 8

    recombined = PlanarTileCodec.combine_bitplanes(planes, fmt)
    assert recombined == tile_bytes


def test_snes_3bpp_capcom_format():
    # SNES 3bpp has 24 bytes: 16 bytes for planes 0-1, 8 bytes for plane 2
    pixels = [7 if i == 0 else 0 for i in range(64)]
    # Pixel (0, 0) is 7 (bits 0, 1, 2 all set)
    encoded = PlanarTileCodec.encode_tile(pixels, "snes_3bpp")
    assert len(encoded) == 24

    # Plane 0 row 0 is byte 0, Plane 1 row 0 is byte 1, Plane 2 row 0 is byte 16
    assert encoded[0] == 0x80
    assert encoded[1] == 0x80
    assert encoded[16] == 0x80

    decoded = PlanarTileCodec.decode_tile(encoded, "snes_3bpp")
    assert decoded == pixels


def test_bulk_linear_conversion():
    fmt = "nes_2bpp"
    tile1 = [1] * 64
    tile2 = [2] * 64
    raw_tiles = PlanarTileCodec.encode_tile(tile1, fmt) + PlanarTileCodec.encode_tile(tile2, fmt)

    linear = PlanarTileCodec.planar_to_linear(raw_tiles, fmt)
    assert len(linear) == 128
    assert list(linear[:64]) == tile1
    assert list(linear[64:]) == tile2

    re_planar = PlanarTileCodec.linear_to_planar(linear, fmt)
    assert re_planar == raw_tiles


def test_invalid_sizes():
    with pytest.raises(ParseError):
        PlanarTileCodec.decode_tile(b"\x00" * 4, "nes_2bpp")

    with pytest.raises(ValueError):
        PlanarTileCodec.encode_tile([0] * 32, "nes_2bpp")
