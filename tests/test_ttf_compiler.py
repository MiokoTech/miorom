import pytest
from miorom.text import TTFCompiler


def test_ttf_compiler_render_glyph():
    compiler = TTFCompiler(font_size=12)
    tile, adv = compiler.render_glyph("A", bpp=2)

    assert len(tile.pixels) == 64
    assert adv > 0
    assert any(p > 0 for p in tile.pixels)


def test_ttf_compiler_quantization_bpp():
    compiler = TTFCompiler(font_size=12)

    # 1bpp
    tile1, _ = compiler.render_glyph("X", bpp=1)
    assert all(p in (0, 1) for p in tile1.pixels)

    # 4bpp
    tile4, _ = compiler.render_glyph("X", bpp=4)
    assert all(0 <= p <= 15 for p in tile4.pixels)


def test_ttf_compiler_to_nftr():
    compiler = TTFCompiler(font_size=10)
    nftr = compiler.to_nftr("ABC", bpp=2)

    assert len(nftr.glyphs) == 3
    assert ord("A") in nftr.glyphs
    assert ord("B") in nftr.glyphs
    assert ord("C") in nftr.glyphs

    # Serialize to bytes
    nftr_bytes = nftr.to_bytes()
    assert nftr_bytes[:4] == b"RTFN"
    assert b"PLGC" in nftr_bytes
    assert b"CWDH" in nftr_bytes
    assert b"CMAP" in nftr_bytes


def test_ttf_compiler_to_bitmap_font():
    compiler = TTFCompiler(font_size=12)
    bf = compiler.to_bitmap_font("Hello World", width=8, height=12)

    assert "H" in bf.glyphs
    assert "e" in bf.glyphs
    assert "l" in bf.glyphs
    assert "o" in bf.glyphs

    width = bf.measure_string("Hello")
    assert width > 0


def test_ttf_compiler_to_raw_tiles():
    compiler = TTFCompiler(font_size=8)
    tile_bytes, width_tbl = compiler.to_raw_tiles("012345", bpp=2)

    # 6 characters * 8x8 2bpp tile (16 bytes per tile) = 96 bytes
    assert len(tile_bytes) == 96
    assert len(width_tbl) == 6
    assert ord("0") in width_tbl
    assert width_tbl[ord("0")] > 0
