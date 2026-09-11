import pytest
from miorom.graphics.tiles import Tile, decode_tile, encode_tile, decode_tileset, encode_tileset
from miorom.errors import ParseError


def test_genesis_4bpp_chunky_nibble_order():
    # In Sega Genesis / Mega Drive, 4bpp chunky uses high nibble first
    # Byte 0x12 contains pixel(0) = 1, pixel(1) = 2
    raw = bytearray(32)
    raw[0] = 0x12  # pixel (0,0)=1, (1,0)=2
    raw[1] = 0xAB  # pixel (2,0)=10, (3,0)=11

    # Decode with format="genesis"
    tile_md = decode_tile(bytes(raw), format="genesis")
    assert tile_md.get_pixel(0, 0) == 1
    assert tile_md.get_pixel(1, 0) == 2
    assert tile_md.get_pixel(2, 0) == 10
    assert tile_md.get_pixel(3, 0) == 11

    # Standard GBA/NDS decode (low nibble first)
    tile_gba = decode_tile(bytes(raw), bpp=4, planar=False, high_nibble_first=False)
    assert tile_gba.get_pixel(0, 0) == 2
    assert tile_gba.get_pixel(1, 0) == 1
    assert tile_gba.get_pixel(2, 0) == 11
    assert tile_gba.get_pixel(3, 0) == 10

    # Roundtrip encoding
    encoded_md = encode_tile(tile_md, format="md")
    assert encoded_md == bytes(raw)


def test_snes_8bpp_planar_mode7():
    # SNES 8bpp planar tile: 64 bytes per 8x8 tile
    # 4 pairs of plane bytes per row (planes 0,1, 2,3, 4,5, 6,7)
    tile = Tile()
    tile.set_pixel(0, 0, 0b10101011)  # 171: bit 0, 1, 3, 5, 7 set
    tile.set_pixel(7, 0, 0b00000001)  # 1: bit 0 set
    tile.set_pixel(3, 3, 255)         # 255: all 8 bits set

    encoded = encode_tile(tile, format="snes8")
    assert len(encoded) == 64

    decoded = decode_tile(encoded, format="snes_8bpp")
    assert decoded.get_pixel(0, 0) == 0b10101011
    assert decoded.get_pixel(7, 0) == 1
    assert decoded.get_pixel(3, 3) == 255
    assert decoded == tile


def test_tileset_batch_encoding_and_aliases():
    t1 = Tile([i % 16 for i in range(64)])
    t2 = Tile([(i * 3) % 16 for i in range(64)])
    tiles = [t1, t2]

    # Batch encode with format="megadrive"
    md_bytes = encode_tileset(tiles, format="megadrive")
    assert len(md_bytes) == 64

    decoded_tiles = decode_tileset(md_bytes, format="megadrive")
    assert len(decoded_tiles) == 2
    assert decoded_tiles[0] == t1
    assert decoded_tiles[1] == t2


def test_tile_truncation_detection():
    # Less than 32 bytes for 4bpp
    short_data = b"\x00" * 15
    with pytest.raises(ParseError):
        decode_tile(short_data, bpp=4)

    # Less than 64 bytes for 8bpp
    short_8bpp = b"\x00" * 63
    with pytest.raises(ParseError):
        decode_tile(short_8bpp, bpp=8)
