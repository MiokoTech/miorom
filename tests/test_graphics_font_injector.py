import pytest
from miorom.graphics.font_injector import FontGlyphInjector, LATIN_8X8_BITMAPS
from miorom.graphics.tiles import Tile
from miorom.errors import ParseError


def test_standard_latin_glyph_retrieval():
    tile_a = FontGlyphInjector.get_tile("A")
    assert isinstance(tile_a, Tile)
    assert len(tile_a.pixels) == 64
    # 'A' has active foreground pixels
    assert any(p != 0 for p in tile_a.pixels)

    tile_space = FontGlyphInjector.get_tile(" ")
    # Space has zero active pixels
    assert all(p == 0 for p in tile_space.pixels)

    glyph_e = FontGlyphInjector.get_glyph("é")
    assert glyph_e.char == "é"
    assert glyph_e.width == 8
    assert glyph_e.height == 8
    assert glyph_e.advance > 0


def test_glyph_proportional_width_calculation():
    width_i = FontGlyphInjector.calculate_glyph_width("i")
    width_w = FontGlyphInjector.calculate_glyph_width("W")
    width_m = FontGlyphInjector.calculate_glyph_width("m")
    width_space = FontGlyphInjector.calculate_glyph_width(" ", space_width=3)

    assert width_i < width_w
    assert width_i < width_m
    assert width_space == 3
    assert 1 <= width_i <= 8
    assert 1 <= width_w <= 8


def test_encode_and_inject_glyph_1bpp():
    buf = bytearray(64)  # 8 tiles of 1bpp (8 bytes each)
    # Inject 'A' at tile index 2 (offset 16)
    updated = FontGlyphInjector.inject_glyph(
        buf,
        tile_index_or_offset=2,
        char_or_tile="A",
        bpp=1,
    )

    assert len(updated) == 64
    tile_bytes = updated[16:24]
    assert len(tile_bytes) == 8
    assert any(b != 0 for b in tile_bytes)


def test_encode_and_inject_glyph_2bpp_planar():
    buf = bytearray(128)  # 8 tiles of 2bpp (16 bytes each)
    # Inject 'X' with Game Boy format preset
    updated = FontGlyphInjector.inject_glyph(
        buf,
        tile_index_or_offset=1,
        char_or_tile="X",
        bpp=2,
        format="gb",
        fg_color=3,
    )

    tile_bytes = updated[16:32]
    assert len(tile_bytes) == 16
    assert any(b != 0 for b in tile_bytes)


def test_inject_charset_batch_and_mapping():
    chars = "abcdefghijklmnopqrstuvwxyz"
    initial_buf = bytearray(16)
    mod_buf, mapping = FontGlyphInjector.inject_charset(
        initial_buf,
        start_tile_index=5,
        chars=chars,
        bpp=1,
    )

    assert len(mapping) == 26
    assert mapping["a"] == 5
    assert mapping["z"] == 30
    # Buffer expanded to hold up to tile 31 (31 * 8 = 248 bytes)
    assert len(mod_buf) >= 31 * 8


def test_extract_glyph_roundtrip():
    buf = bytearray(32)
    # Inject 'B' at tile 1
    buf = FontGlyphInjector.inject_glyph(buf, tile_index_or_offset=1, char_or_tile="B", bpp=1)

    extracted = FontGlyphInjector.extract_glyph(bytes(buf), tile_index_or_offset=1, bpp=1, char="B")
    assert extracted.char == "B"
    assert extracted.width == 8
    assert extracted.height == 8
    assert any(p != 0 for p in extracted.bitmap)

    # Out of range extraction raises ParseError
    with pytest.raises(ParseError):
        FontGlyphInjector.extract_glyph(bytes(buf), tile_index_or_offset=99, bpp=1)


def test_generate_vwf_width_table():
    chars = "IlMW"
    table = FontGlyphInjector.generate_vwf_table(chars, space_width=3, padding=1)

    assert len(table) == 4
    # 'I' and 'l' must be narrower than 'M' and 'W'
    assert table[0] < table[2]
    assert table[1] < table[3]


def test_generate_tbl_mapping():
    tbl_text = FontGlyphInjector.generate_tbl_mapping("ABC", start_code=0x80)
    expected = "80=A\n81=B\n82=C\n"
    assert tbl_text == expected
