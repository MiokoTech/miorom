import pytest
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import (
    Tile,
    decode_tile,
    encode_tile,
    decode_tileset,
    encode_tileset,
)
from miorom.graphics.tilemap import TilemapEntry, Tilemap, TileReducer


def test_color_bgr555_conversion():
    # Pure red in 8-bit is (255, 0, 0), in BGR555 is 0x001F
    red = Color(255, 0, 0)
    assert red.to_bgr555() == 0x001F
    from_bgr = Color.from_bgr555(0x001F)
    assert from_bgr.r == 255 and from_bgr.g == 0 and from_bgr.b == 0

    # Pure green: (0, 255, 0) -> 0x03E0
    green = Color(0, 255, 0)
    assert green.to_bgr555() == 0x03E0

    # Pure blue: (0, 0, 255) -> 0x7C00
    blue = Color(0, 0, 255)
    assert blue.to_bgr555() == 0x7C00


def test_palette_matching():
    pal = Palette([
        Color(0, 0, 0),       # 0: Black
        Color(255, 255, 255), # 1: White
        Color(255, 0, 0),     # 2: Red
        Color(0, 0, 255),     # 3: Blue
    ])
    assert pal.match_color(Color(250, 10, 10)) == 2
    assert pal.match_color(Color(10, 10, 250)) == 3
    assert pal.match_color(Color(20, 20, 20)) == 0


def test_tile_encoding_decoding_1bpp():
    # Diagonal line
    tile = Tile()
    for i in range(8):
        tile.set_pixel(i, i, 1)
    encoded = encode_tile(tile, bpp=1)
    assert len(encoded) == 8
    decoded = decode_tile(encoded, bpp=1)
    assert decoded == tile


def test_tile_encoding_decoding_2bpp():
    tile = Tile([i % 4 for i in range(64)])
    encoded = encode_tile(tile, bpp=2)
    assert len(encoded) == 16
    decoded = decode_tile(encoded, bpp=2)
    assert decoded == tile


def test_tile_encoding_decoding_4bpp_chunky_and_planar():
    tile = Tile([i % 16 for i in range(64)])
    # Chunky (GBA/NDS)
    enc_chunky = encode_tile(tile, bpp=4, planar=False)
    assert len(enc_chunky) == 32
    assert decode_tile(enc_chunky, bpp=4, planar=False) == tile

    # Planar (SNES)
    enc_planar = encode_tile(tile, bpp=4, planar=True)
    assert len(enc_planar) == 32
    assert decode_tile(enc_planar, bpp=4, planar=True) == tile


def test_tile_encoding_decoding_8bpp():
    tile = Tile([i * 4 for i in range(64)])
    enc = encode_tile(tile, bpp=8)
    assert len(enc) == 64
    assert decode_tile(enc, bpp=8) == tile


def test_tile_reducer():
    t1 = Tile([1] * 64)
    t2 = Tile([2] * 64)
    # t3 is t1 flipped horizontally
    t3 = Tile([1] * 64)
    t3.set_pixel(0, 0, 9)
    t3_flipped = t3.flip_x()

    tiles = [t1, t2, t1, t3, t3_flipped]
    unique, entries = TileReducer.reduce(tiles, allow_flip=True)

    # unique should only have 3 tiles: t1, t2, and t3 (since t3_flipped is deduplicated as t3 flipped!)
    assert len(unique) == 3
    assert len(entries) == 5
    assert entries[0].tile_index == 0
    assert entries[1].tile_index == 1
    assert entries[2].tile_index == 0
    assert entries[3].tile_index == 2
    assert entries[4].tile_index == 2
    assert entries[4].flip_x is True
