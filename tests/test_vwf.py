import pytest

from miorom.text.vwf import GlyphWidthTable, VWFMetrics
from miorom.text.charmap import CharMap


def test_glyph_width_table_measurement_and_wrapping():
    # Widths for ASCII characters: base_index=32 (space=32)
    # Default widths: 'i'=4, 'l'=4, 'W'=12, 'M'=12, others=8
    widths = [8] * 128
    widths[ord("i")] = 4
    widths[ord("l")] = 4
    widths[ord("W")] = 12
    widths[ord("M")] = 12

    table = GlyphWidthTable(widths=widths, base_index=0, metrics=VWFMetrics(space_width=4, tracking=1))

    # 'ili' = 4 + 1 + 4 + 1 + 4 = 14 px
    w_ili = table.measure_text("ili")
    assert w_ili == 14

    # 'WMW' = 12 + 1 + 12 + 1 + 12 = 38 px
    w_wmw = table.measure_text("WMW")
    assert w_wmw == 38

    # Proportional text wrapping within 40px
    # "ili WMW ili"
    # line 1: "ili WMW" -> 14 + 1 (tracking before space) + 4 (space) + 1 + 38 = 58 px > 40px!
    # So it should wrap into ["ili", "WMW", "ili"] or similar
    lines = table.wrap_text("ili WMW ili", max_pixel_width=40)
    assert len(lines) >= 2


def test_glyph_width_table_binary_serialization_and_patch():
    widths = [6, 7, 8, 9, 10]
    table = GlyphWidthTable(widths)
    binary = table.to_binary(entry_size=1)
    assert binary == bytes([6, 7, 8, 9, 10])

    rom_buf = bytearray(32)
    table.patch_buffer(rom_buf, offset=8)
    assert rom_buf[8:13] == bytes([6, 7, 8, 9, 10])

    restored = GlyphWidthTable.from_binary(bytes(rom_buf), count=5, entry_size=1, offset=8)
    assert restored.widths == widths
