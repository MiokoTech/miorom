"""
Unit tests for miorom.graphics.tilemap.
"""

import pytest

from miorom.graphics.tilemap import (
    TilemapEntry,
    Tilemap,
    TileReducer,
    decode_nes_nametable,
    encode_nes_nametable,
    decode_genesis_tilemap,
    encode_genesis_tilemap,
    decode_gbc_tilemap,
    encode_gbc_tilemap,
)
from miorom.graphics.tiles import Tile


def test_tilemap_entry_formats():
    # GBA / NDS format
    entry_gba = TilemapEntry(tile_index=0x234, flip_x=True, flip_y=False, palette_bank=3)
    val_gba = entry_gba.to_u16("gba")
    dec_gba = TilemapEntry.from_u16(val_gba, "gba")
    assert dec_gba.tile_index == 0x234
    assert dec_gba.flip_x is True
    assert dec_gba.flip_y is False
    assert dec_gba.palette_bank == 3

    # SNES format
    entry_snes = TilemapEntry(tile_index=0x150, flip_x=False, flip_y=True, palette_bank=5, priority=1)
    val_snes = entry_snes.to_u16("snes")
    dec_snes = TilemapEntry.from_u16(val_snes, "snes")
    assert dec_snes.tile_index == 0x150
    assert dec_snes.flip_x is False
    assert dec_snes.flip_y is True
    assert dec_snes.palette_bank == 5
    assert dec_snes.priority == 1

    # Genesis format
    entry_gen = TilemapEntry(tile_index=0x580, flip_x=True, flip_y=True, palette_bank=2, priority=1)
    val_gen = entry_gen.to_u16("genesis")
    dec_gen = TilemapEntry.from_u16(val_gen, "genesis")
    assert dec_gen.tile_index == 0x580
    assert dec_gen.flip_x is True
    assert dec_gen.flip_y is True
    assert dec_gen.palette_bank == 2
    assert dec_gen.priority == 1

    # GBC format
    entry_gbc = TilemapEntry(tile_index=0x42, flip_x=True, flip_y=False, palette_bank=6, priority=1, vram_bank=1)
    val_gbc = entry_gbc.to_u16("gbc")
    dec_gbc = TilemapEntry.from_u16(val_gbc, "gbc")
    assert dec_gbc.tile_index == 0x42
    assert dec_gbc.flip_x is True
    assert dec_gbc.palette_bank == 6
    assert dec_gbc.priority == 1
    assert dec_gbc.vram_bank == 1


def test_tilemap_submap_and_paste():
    tm = Tilemap(width=4, height=4)
    for y in range(4):
        for x in range(4):
            tm.set_entry(x, y, TilemapEntry(tile_index=y * 4 + x))

    assert tm.get_entry(2, 1).tile_index == 6

    # Extract 2x2 submap
    sub = tm.submap(1, 1, 2, 2)
    assert sub.width == 2
    assert sub.height == 2
    assert sub.get_entry(0, 0).tile_index == 5
    assert sub.get_entry(1, 0).tile_index == 6
    assert sub.get_entry(0, 1).tile_index == 9
    assert sub.get_entry(1, 1).tile_index == 10

    # Paste onto a target tilemap
    target = Tilemap(width=4, height=4)
    target.paste(sub, dest_x=2, dest_y=2)
    assert target.get_entry(2, 2).tile_index == 5
    assert target.get_entry(3, 2).tile_index == 6
    assert target.get_entry(2, 3).tile_index == 9
    assert target.get_entry(3, 3).tile_index == 10


def test_nes_nametable_roundtrip():
    # Build 32x30 tilemap with varying palettes across quadrants
    tm = Tilemap(width=32, height=30)
    for y in range(30):
        for x in range(32):
            # Assign palette based on 2x2 quadrant within 4x4 block
            sub_x = (x % 4) // 2
            sub_y = (y % 4) // 2
            pal = (sub_y * 2 + sub_x) % 4
            tm.set_entry(x, y, TilemapEntry(tile_index=(x + y) % 256, palette_bank=pal))

    raw_bytes = encode_nes_nametable(tm)
    assert len(raw_bytes) == 1024

    decoded_tm = decode_nes_nametable(raw_bytes)
    assert decoded_tm.width == 32
    assert decoded_tm.height == 30

    for y in range(30):
        for x in range(32):
            orig = tm.get_entry(x, y)
            dec = decoded_tm.get_entry(x, y)
            assert dec.tile_index == orig.tile_index
            assert dec.palette_bank == orig.palette_bank


def test_genesis_tilemap_roundtrip():
    tm = Tilemap(width=8, height=8)
    for i in range(64):
        tm.entries[i] = TilemapEntry(
            tile_index=i * 10,
            flip_x=(i % 2 == 1),
            flip_y=(i % 4 >= 2),
            palette_bank=(i % 4),
            priority=(1 if i > 32 else 0),
        )

    raw = encode_genesis_tilemap(tm, endian=">")
    assert len(raw) == 128

    dec = decode_genesis_tilemap(raw, width=8, height=8, endian=">")
    assert dec.width == 8
    assert dec.height == 8
    for i in range(64):
        assert dec.entries[i] == tm.entries[i]


def test_gbc_tilemap_roundtrip():
    tm = Tilemap(width=16, height=16)
    for i in range(256):
        tm.entries[i] = TilemapEntry(
            tile_index=i % 256,
            flip_x=(i % 2 == 1),
            flip_y=(i % 4 == 0),
            palette_bank=i % 8,
            priority=1 if i > 128 else 0,
            vram_bank=1 if i % 2 == 0 else 0,
        )

    vram0, vram1 = encode_gbc_tilemap(tm)
    assert len(vram0) == 256
    assert len(vram1) == 256

    dec = decode_gbc_tilemap(vram0, vram1, width=16, height=16)
    for i in range(256):
        assert dec.entries[i].tile_index == tm.entries[i].tile_index
        assert dec.entries[i].flip_x == tm.entries[i].flip_x
        assert dec.entries[i].flip_y == tm.entries[i].flip_y
        assert dec.entries[i].palette_bank == tm.entries[i].palette_bank
        assert dec.entries[i].vram_bank == tm.entries[i].vram_bank


def test_tilemap_render_pixels():
    # Tile 0: all 1s, Tile 1: diagonal
    tile0 = Tile([1] * 64)
    tile1_pixels = [0] * 64
    for i in range(8):
        tile1_pixels[i * 8 + i] = 2
    tile1 = Tile(tile1_pixels)

    tm = Tilemap(width=2, height=1)
    tm.set_entry(0, 0, TilemapEntry(tile_index=0, palette_bank=0))
    tm.set_entry(1, 0, TilemapEntry(tile_index=1, flip_x=True, palette_bank=1))

    rendered = tm.render_pixels(tiles=[tile0, tile1], combine_palette=True, colors_per_palette=16)
    assert len(rendered) == 8
    assert len(rendered[0]) == 16

    # Check tile 0 pixel
    assert rendered[0][0] == 1

    # Check tile 1 pixel flipped x (diagonal (i, 7-i))
    # Original diagonal has pixel at (0, 0). Flipped x has it at (7, 0).
    # Since tile 1 is at tx=1, base_x = 8. So column is 8 + 7 = 15.
    assert rendered[0][15] == 16 + 2  # palette 1 (16) + color 2
