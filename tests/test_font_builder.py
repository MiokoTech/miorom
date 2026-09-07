import pytest
from miorom.text.font_builder import BitmapFont, Glyph


def test_bitmap_font_ascii_art_and_measure():
    font = BitmapFont(default_height=8, default_advance=6)

    # Add glyph 'A' (5x5)
    font.add_glyph_from_ascii_art(
        "A",
        """
.###.
#...#
#####
#...#
#...#
""",
        advance=6,
    )

    # Add glyph 'B' (5x5)
    font.add_glyph_from_ascii_art(
        "B",
        """
####.
#...#
####.
#...#
####.
""",
        advance=6,
    )

    g_a = font.get_glyph("A")
    assert g_a is not None
    assert g_a.width == 5
    assert g_a.height == 5
    assert g_a.advance == 6
    assert g_a.get_pixel(1, 0) == 255
    assert g_a.get_pixel(0, 0) == 0

    # Measure
    assert font.measure_string("AB") == 12
    assert font.measure_string("ABC") == 18  # 'C' uses default_advance=6

    # Convert to tile
    tile_a = g_a.to_tile()
    assert tile_a.get_pixel(1, 0) == 1
    assert tile_a.get_pixel(0, 0) == 0

    # Render line
    w, h, grid = font.render_line("AB")
    assert w == 12
    assert h == 8
    assert grid[0][1] == 255
