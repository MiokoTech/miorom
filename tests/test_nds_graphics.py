"""
Unit tests for Nintendo DS graphics formats: NCLR (palettes), NCGR (character tiles), NSCR (screen tilemaps).
"""

import pytest

from miorom.platforms.nds.nclr import NCLRFile
from miorom.platforms.nds.ncgr import NCGRFile
from miorom.platforms.nds.nscr import NSCRFile, ScreenEntry
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile


def test_nclr_palette_roundtrip():
    # Create test palette with distinct colors
    colors = [
        Color(0, 0, 0),
        Color(255, 0, 0),
        Color(0, 255, 0),
        Color(0, 0, 255),
        Color(255, 255, 255),
    ]
    pal = Palette(colors=colors)
    nclr = NCLRFile.from_palette(pal, bpp=4)

    raw_bytes = nclr.to_bytes()
    assert raw_bytes.startswith(b"RLCN")

    parsed = NCLRFile.from_bytes(raw_bytes)
    assert parsed.bpp == 4
    assert len(parsed.colors) == 5

    # Check color fidelity (within 5-bit precision range)
    for c_orig, c_parsed in zip(colors, parsed.colors):
        assert abs(c_orig.r - c_parsed.r) <= 8
        assert abs(c_orig.g - c_parsed.g) <= 8
        assert abs(c_orig.b - c_parsed.b) <= 8


def test_ncgr_tile_roundtrip_4bpp_and_8bpp():
    # 4bpp test (2 tiles)
    pixels1 = [(i % 16) for i in range(64)]
    pixels2 = [((i * 3) % 16) for i in range(64)]
    tiles_4bpp = [Tile(pixels1), Tile(pixels2)]

    ncgr_4bpp = NCGRFile(tiles=tiles_4bpp, bpp=4)
    raw_4bpp = ncgr_4bpp.to_bytes()
    assert raw_4bpp.startswith(b"RGCN")

    parsed_4bpp = NCGRFile.from_bytes(raw_4bpp)
    assert parsed_4bpp.bpp == 4
    assert parsed_4bpp.tile_count == 2
    assert parsed_4bpp.tiles[0].pixels == pixels1
    assert parsed_4bpp.tiles[1].pixels == pixels2

    # 8bpp test (1 tile)
    pixels_8bpp = [(i * 4) % 256 for i in range(64)]
    tiles_8bpp = [Tile(pixels_8bpp)]

    ncgr_8bpp = NCGRFile(tiles=tiles_8bpp, bpp=8)
    raw_8bpp = ncgr_8bpp.to_bytes()
    parsed_8bpp = NCGRFile.from_bytes(raw_8bpp)
    assert parsed_8bpp.bpp == 8
    assert parsed_8bpp.tile_count == 1
    assert parsed_8bpp.tiles[0].pixels == pixels_8bpp


def test_nscr_screen_roundtrip():
    entries = [
        ScreenEntry(tile_index=0, flip_x=False, flip_y=False, palette_index=0),
        ScreenEntry(tile_index=42, flip_x=True, flip_y=False, palette_index=2),
        ScreenEntry(tile_index=100, flip_x=False, flip_y=True, palette_index=5),
        ScreenEntry(tile_index=512, flip_x=True, flip_y=True, palette_index=15),
    ]

    nscr = NSCRFile(entries=entries, width_pixels=256, height_pixels=192)
    assert nscr.width_tiles == 32
    assert nscr.height_tiles == 24

    raw_bytes = nscr.to_bytes()
    assert raw_bytes.startswith(b"RCSN")

    parsed = NSCRFile.from_bytes(raw_bytes)
    assert parsed.width_pixels == 256
    assert parsed.height_pixels == 192
    assert len(parsed.entries) == 4

    for orig, res in zip(entries, parsed.entries):
        assert orig.tile_index == res.tile_index
        assert orig.flip_x == res.flip_x
        assert orig.flip_y == res.flip_y
        assert orig.palette_index == res.palette_index
