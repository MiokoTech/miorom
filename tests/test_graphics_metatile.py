"""
Unit tests for miorom.graphics.metatile.
"""

import pytest

from miorom.graphics.metatile import Metatile16, MetatileTable, MetatileMap
from miorom.graphics.tilemap import Tilemap, TilemapEntry


def test_metatile_table_sequential_8bit():
    # 2 metatiles, 4 bytes each = 8 bytes total
    raw_data = bytes([
        0x10, 0x11, 0x20, 0x21,  # Metatile 0
        0x30, 0x31, 0x40, 0x41,  # Metatile 1
    ])

    table = MetatileTable.unpack_sequential_bytes(raw_data, count=2, fmt="nes")
    assert len(table) == 2

    m0 = table.get(0)
    assert m0 is not None
    assert m0.tl.tile_index == 0x10
    assert m0.tr.tile_index == 0x11
    assert m0.bl.tile_index == 0x20
    assert m0.br.tile_index == 0x21

    m1 = table.get(1)
    assert m1 is not None
    assert m1.tl.tile_index == 0x30

    packed = table.pack_sequential_bytes(fmt="nes")
    assert packed == raw_data


def test_metatile_table_sequential_16bit():
    table = MetatileTable()
    m0 = Metatile16(
        index=0,
        tl=TilemapEntry(tile_index=0x100, flip_x=True, palette_bank=2),
        tr=TilemapEntry(tile_index=0x101, palette_bank=2),
        bl=TilemapEntry(tile_index=0x120, palette_bank=2),
        br=TilemapEntry(tile_index=0x121, flip_y=True, palette_bank=2),
    )
    table.add(m0)

    packed = table.pack_sequential_bytes(fmt="snes")
    assert len(packed) == 8

    dec = MetatileTable.unpack_sequential_bytes(packed, count=1, fmt="snes")
    m_dec = dec.get(0)
    assert m_dec.tl.tile_index == 0x100
    assert m_dec.tl.flip_x is True
    assert m_dec.br.flip_y is True
    assert m_dec.br.palette_bank == 2


def test_metatile_table_planar():
    tl = bytes([0x01, 0x05])
    tr = bytes([0x02, 0x06])
    bl = bytes([0x03, 0x07])
    br = bytes([0x04, 0x08])
    data = tl + tr + bl + br

    table = MetatileTable.unpack_planar_bytes(
        data=data,
        count=2,
        offset_tl=0,
        offset_tr=2,
        offset_bl=4,
        offset_br=6,
    )
    assert len(table) == 2
    assert table.get(0).tl.tile_index == 0x01
    assert table.get(1).br.tile_index == 0x08

    p_tl, p_tr, p_bl, p_br = table.pack_planar_bytes()
    assert p_tl == tl
    assert p_tr == tr
    assert p_bl == bl
    assert p_br == br


def test_metatile_map_expand_and_compress():
    table = MetatileTable()
    # Metatile 0: Grass (tiles 1, 2, 3, 4)
    table.add(Metatile16(
        index=0,
        tl=TilemapEntry(tile_index=1),
        tr=TilemapEntry(tile_index=2),
        bl=TilemapEntry(tile_index=3),
        br=TilemapEntry(tile_index=4),
    ))
    # Metatile 1: Water (tiles 5, 6, 7, 8)
    table.add(Metatile16(
        index=1,
        tl=TilemapEntry(tile_index=5),
        tr=TilemapEntry(tile_index=6),
        bl=TilemapEntry(tile_index=7),
        br=TilemapEntry(tile_index=8),
    ))

    # 2x2 metatile map
    meta_map = MetatileMap(width=2, height=2, map_data=[0, 1, 1, 0])
    tilemap = meta_map.to_tilemap(table)

    # Resulting tilemap should be 4x4 tiles
    assert tilemap.width == 4
    assert tilemap.height == 4

    # Top-left metatile 0
    assert tilemap.get_entry(0, 0).tile_index == 1
    assert tilemap.get_entry(1, 0).tile_index == 2
    assert tilemap.get_entry(0, 1).tile_index == 3
    assert tilemap.get_entry(1, 1).tile_index == 4

    # Top-right metatile 1
    assert tilemap.get_entry(2, 0).tile_index == 5
    assert tilemap.get_entry(3, 0).tile_index == 6

    # Test reverse compression from tilemap
    rec_map, rec_table = MetatileMap.from_tilemap(tilemap)
    assert rec_map.width == 2
    assert rec_map.height == 2
    assert len(rec_table) == 2
    assert rec_map.map_data == [0, 1, 1, 0]


def test_metatile_map_bytes_io():
    meta_map = MetatileMap(width=4, height=4, map_data=list(range(16)))
    raw_1b = meta_map.to_bytes(bytes_per_entry=1)
    assert len(raw_1b) == 16
    dec_1b = MetatileMap.from_bytes(raw_1b, width=4, height=4, bytes_per_entry=1)
    assert dec_1b.map_data == list(range(16))

    raw_2b = meta_map.to_bytes(bytes_per_entry=2, endian=">")
    assert len(raw_2b) == 32
    dec_2b = MetatileMap.from_bytes(raw_2b, width=4, height=4, bytes_per_entry=2, endian=">")
    assert dec_2b.map_data == list(range(16))
