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
