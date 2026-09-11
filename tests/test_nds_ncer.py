"""
Unit tests for Nintendo DS NCER (Nitro Character Resource) cell and sprite assembling.
"""

import pytest
from miorom.platforms.nds.ncer import NCERFile, NCERBank, NCERCell, get_ncer_cell_size
from miorom.platforms.nds.ncgr import NCGRFile
from miorom.platforms.nds.nclr import NCLRFile
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile


def test_ncer_cell_sizes():
    assert get_ncer_cell_size(0, 0) == (8, 8)
    assert get_ncer_cell_size(0, 1) == (16, 16)
    assert get_ncer_cell_size(0, 2) == (32, 32)
    assert get_ncer_cell_size(0, 3) == (64, 64)
    assert get_ncer_cell_size(1, 0) == (16, 8)
    assert get_ncer_cell_size(1, 1) == (32, 8)
    assert get_ncer_cell_size(1, 2) == (32, 16)
    assert get_ncer_cell_size(1, 3) == (64, 32)
    assert get_ncer_cell_size(2, 0) == (8, 16)
    assert get_ncer_cell_size(2, 1) == (8, 32)
    assert get_ncer_cell_size(2, 2) == (16, 32)
    assert get_ncer_cell_size(2, 3) == (32, 64)


def test_nclr_pcmp_multi_section():
    # Test palette with PCMP mapping bank 8
    colors = [Color(255, 0, 0)] * 16
    pal = Palette(colors=colors)
    nclr = NCLRFile.from_palette(pal, bpp=4, pmcp_indices=[8])

    raw_bytes = nclr.to_bytes()
    assert b"PMCP" in raw_bytes

    parsed = NCLRFile.from_bytes(raw_bytes)
    assert parsed.pmcp_indices == [8]
    assert 8 in parsed.indexed_palettes
    assert len(parsed.indexed_palettes[8]) == 16

    expanded_pal = parsed.to_palette(expand_pmcp=True)
    assert len(expanded_pal) >= 144
    assert expanded_pal[128] == Color(255, 0, 0)


def test_nscr_paged_coordinates():
    # Large 512x256 map (2 SBBs: SBB 0 = left 32x32, SBB 1 = right 32x32)
    entries = []
    # Fill SBB 0 (1024 entries) with tile 10
    from miorom.platforms.nds.nscr import ScreenEntry
    for _ in range(1024):
        entries.append(ScreenEntry(tile_index=10))
    # Fill SBB 1 (1024 entries) with tile 20
    for _ in range(1024):
        entries.append(ScreenEntry(tile_index=20))

    from miorom.platforms.nds.nscr import NSCRFile
    nscr = NSCRFile(entries=entries, width_pixels=512, height_pixels=256)
    assert nscr.width_tiles == 64
    assert nscr.height_tiles == 32

    # Coordinate (0, 0) is in SBB 0
    e0 = nscr.get_entry(0, 0, paged=True)
    assert e0 is not None and e0.tile_index == 10

    # Coordinate (32, 0) is in SBB 1
    e1 = nscr.get_entry(32, 0, paged=True)
    assert e1 is not None and e1.tile_index == 20


def test_ncer_roundtrip():
    cell1 = NCERCell(x=10, y=20, width=16, height=16, shape=0, size=1, tile_offset=5, palette_index=2)
    cell2 = NCERCell(x=-5, y=0, width=32, height=8, shape=1, size=1, tile_offset=12, palette_index=0, flip_x=True)
    bank = NCERBank(cells=[cell1, cell2], x_min=-5, y_min=0, x_max=26, y_max=36, cell_info=0x0100)

    ncer = NCERFile(banks=[bank], cell_type=1)
    raw = ncer.to_bytes()
    assert raw[:4] == b"RECN"

    reloaded = NCERFile.from_bytes(raw)
    assert reloaded.bank_count == 1
    assert len(reloaded.banks[0].cells) == 2
    r_c1 = reloaded.banks[0].cells[0]
    assert r_c1.x == 10
    assert r_c1.y == 20
    assert r_c1.width == 16
    assert r_c1.height == 16
    assert r_c1.tile_offset == 5
    assert r_c1.palette_index == 2

    r_c2 = reloaded.banks[0].cells[1]
    assert r_c2.x == -5
    assert r_c2.y == 0
    assert r_c2.width == 32
    assert r_c2.height == 8
    assert r_c2.flip_x is True
    assert r_c2.tile_offset == 12
