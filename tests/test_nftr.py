import pytest
from miorom.platforms.nds.nftr import NFTRFont
from miorom.graphics.tiles import Tile


def test_nftr_font_roundtrip_and_metrics():
    font = NFTRFont(height=12, cell_width=8, bpp=2)

    # Add glyph 'A' (ASCII 65) with custom advance = 7
    tile_a = Tile([1 if i % 2 == 0 else 0 for i in range(64)])
    font.set_glyph("A", tile_a, advance=7)

    # Add glyph 'B' with custom advance = 6
    tile_b = Tile([2 if i % 3 == 0 else 0 for i in range(64)])
    font.set_glyph("B", tile_b, advance=6)

    assert font.measure_string("AB") == 13
    assert font.measure_string("ABA") == 20

    # Serialize to bytes
    nftr_bytes = font.to_bytes()
    assert nftr_bytes[:4] == b"RTFN"
    assert len(nftr_bytes) > 64

    # Deserialize back
    loaded_font = NFTRFont.from_bytes(nftr_bytes)
    assert loaded_font.height == 12
    assert loaded_font.bpp == 2
    assert loaded_font.measure_string("AB") == 13

    g_a = loaded_font.get_glyph("A")
    assert g_a is not None
    assert g_a.advance == 7
    assert g_a.tile == tile_a


def test_nftr_nitro_finf_pointers_and_cmap_chain():
    font = NFTRFont(height=12, cell_width=9, bpp=2)
    # Add contiguous run 0x20..0x25 (6 glyphs -> Type 0)
    for c in range(0x20, 0x26):
        font.set_glyph(c, [1] * (9 * 12), advance=8)
    # Add isolated glyph 0x20AC (Euro -> Type 2)
    font.set_glyph(0x20AC, [2] * (9 * 12), advance=9)

    raw = font.to_bytes()
    assert raw[:4] == b"RTFN"
    assert raw[0x10:0x14] == b"FNIF"

    import struct
    magic, size, ftype, h, null_g, def_w, enc, cw, ch, bpp, p_glyph, p_width, p_map = struct.unpack('<4sIBBBBBBBBIII', raw[0x10:0x2C])
    assert magic == b"FNIF"
    assert size == 28
    assert p_glyph == 0x34
    assert p_width > p_glyph
    assert p_map > p_width
    assert raw[p_glyph - 8:p_glyph - 4] == b"PLGC"
    assert raw[p_width - 8:p_width - 4] == b"HDWC"
    assert raw[p_map - 8:p_map - 4] == b"PAMC"

    loaded = NFTRFont.from_bytes(raw)
    assert loaded.get_glyph(0x20AC).advance == 9
    assert loaded.get_glyph(0x20).advance == 8
