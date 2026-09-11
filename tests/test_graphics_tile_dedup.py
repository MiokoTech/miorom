import pytest
from miorom.graphics.tile_dedup import TileDeduplicator, DeduplicatedTileEntry, TileDedupResult


def test_tile_flips():
    # Construct an 8x8 tile where pixel (x, y) = y * 8 + x
    tile = bytes(range(64))

    flipped_h = TileDeduplicator.flip_horizontal_8x8(tile)
    # Row 0: 0, 1, ..., 7 becomes 7, 6, ..., 0
    assert flipped_h[0] == 7
    assert flipped_h[7] == 0

    flipped_v = TileDeduplicator.flip_vertical_8x8(tile)
    # Row 0 becomes Row 7 (56..63)
    assert flipped_v[0] == 56
    assert flipped_v[7] == 63

    flipped_hv = TileDeduplicator.flip_hv_8x8(tile)
    assert flipped_hv[0] == 63
    assert flipped_hv[63] == 0


def test_tile_deduplication():
    # Tile A: simple pattern
    tile_a = bytearray(64)
    tile_a[0] = 1
    tile_a = bytes(tile_a)

    # Tile B: Tile A flipped horizontally
    tile_b = TileDeduplicator.flip_horizontal_8x8(tile_a)

    # Tile C: Tile A flipped vertically
    tile_c = TileDeduplicator.flip_vertical_8x8(tile_a)

    # Tile D: exact duplicate of Tile A
    tile_d = bytes(tile_a)

    # Tile E: completely different
    tile_e = bytes([2] * 64)

    input_tiles = [tile_a, tile_b, tile_c, tile_d, tile_e]
    res = TileDeduplicator.deduplicate(input_tiles, allow_flip_h=True, allow_flip_v=True, preserve_blank_at_zero=False)

    # Unique tiles should be only 2: tile_a and tile_e!
    assert res.unique_count == 2
    assert res.original_count == 5
    assert res.saved_count == 3

    # Entries check:
    assert res.entries[0].unique_index == 0
    assert res.entries[0].flip_h is False and res.entries[0].flip_v is False

    assert res.entries[1].unique_index == 0
    assert res.entries[1].flip_h is True and res.entries[1].flip_v is False

    assert res.entries[2].unique_index == 0
    assert res.entries[2].flip_h is False and res.entries[2].flip_v is True

    assert res.entries[3].unique_index == 0
    assert res.entries[3].flip_h is False and res.entries[3].flip_v is False

    assert res.entries[4].unique_index == 1
    assert res.entries[4].flip_h is False and res.entries[4].flip_v is False


def test_nametable_word_conversions():
    entry = DeduplicatedTileEntry(orig_index=0, unique_index=42, flip_h=True, flip_v=False)

    snes_word = entry.to_nametable_word_snes(palette=2, priority=1)
    # tile 42 | (palette 2 << 10) | (priority 1 << 13) | (flip_h << 14)
    assert snes_word & 0x03FF == 42
    assert (snes_word >> 10) & 0x07 == 2
    assert (snes_word >> 13) & 0x01 == 1
    assert (snes_word >> 14) & 0x01 == 1
    assert (snes_word >> 15) & 0x01 == 0

    gen_word = entry.to_nametable_word_genesis(palette=1, priority=1)
    assert gen_word & 0x07FF == 42
    assert (gen_word >> 11) & 0x01 == 1
    assert (gen_word >> 12) & 0x01 == 0
    assert (gen_word >> 13) & 0x03 == 1
    assert (gen_word >> 15) & 0x01 == 1

    tile_id, gbc_attr = entry.to_gbc_map_entry(palette=3, vram_bank=1)
    assert tile_id == 42
    assert gbc_attr & 0x07 == 3
    assert (gbc_attr >> 3) & 0x01 == 1
    assert (gbc_attr >> 5) & 0x01 == 1


def test_raw_bpp_deduplication():
    # 2 identical 2bpp tiles (16 bytes each = 32 bytes total)
    raw_2bpp = bytes([0xAA, 0x55] * 8) + bytes([0xAA, 0x55] * 8)
    opt_bytes, entries = TileDeduplicator.deduplicate_raw_bpp(raw_2bpp, bpp=2)

    # 32 bytes should become 16 bytes (1 tile)!
    assert len(opt_bytes) == 16
    assert len(entries) == 2
    assert entries[0].unique_index == 0
    assert entries[1].unique_index == 0
