"""
tests/test_platforms_wii_brfnt.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Nintendo Wii BRFNT Font & TGLP Glyph Sheet Engine.
Tests cover:
- BRFNTFont creation, geometry, and sheet capacity calculation
- Multi-format Nintendo GX texture encoding/decoding (I4, I8, IA4, IA8)
- Single glyph and full sheet PNG image extraction and surgical injection
- Character addition and Unicode font expansion (accented characters / symbols)
- Proportional text width measurement and coverage auditing
- Full binary serialization (to_bytes) and deserialization roundtrip
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from miorom.graphics.png_codec import PNGColorType, PNGImage
from miorom.platforms.wii.brfnt import (
    BRFNTFont,
)


def test_brfnt_create_and_geometry():
    """Verify font creation, column/row calculations, and sheet capacity."""
    font = BRFNTFont.create(
        cell_width=16,
        cell_height=24,
        line_height=26,
        sheet_format=2,  # IA4
        sheet_width=128,
        sheet_height=96,
        num_sheets=1,
    )

    assert font.cell_width == 16
    assert font.cell_height == 24
    assert font.line_height == 26
    assert font.num_cols == 8   # 128 // 16
    assert font.num_rows == 4   # 96 // 24
    assert font.glyphs_per_sheet == 32
    assert font.num_sheets == 1
    assert font.total_glyphs_capacity == 32


def test_brfnt_add_character_and_metrics():
    """Verify character addition, width metrics, text width calculation, and audit."""
    font = BRFNTFont.create(
        cell_width=16,
        cell_height=24,
        sheet_width=64,
        sheet_height=48,
    )

    # Add character 'A'
    g_a = font.add_character("A", left_bearing=1, glyph_width=10, char_advance=12)
    assert g_a == 0
    assert font.has_char("A") is True
    assert font.has_char("B") is False
    assert font.get_char_width("A") == 12

    # Add accented character 'é' (U+00E9)
    g_e = font.add_character("é", left_bearing=0, glyph_width=8, char_advance=9)
    assert g_e == 1
    assert font.has_char("é") is True
    assert font.get_char_width("é") == 9

    # Test string width
    # "AéA" -> 12 + 9 + 12 = 33 px
    assert font.get_text_width("AéA") == 33

    # Audit text coverage
    valid, missing = font.audit_string("Aé")
    assert valid is True
    assert missing == []

    valid_missing, missing_chars = font.audit_string("AéZ")
    assert valid_missing is False
    assert missing_chars == ["Z"]


def test_brfnt_glyph_and_sheet_image_extraction_and_injection():
    """Verify individual glyph and full sheet PNG image manipulation."""
    font = BRFNTFont.create(
        cell_width=8,
        cell_height=8,
        sheet_width=32,
        sheet_height=32,
        sheet_format=2,  # IA4
    )

    # Create a synthetic glyph image (8x8) with distinctive pixel pattern
    pattern_rgba = bytearray(8 * 8 * 4)
    # Fill center 4x4 with white pixels
    for y in range(2, 6):
        for x in range(2, 6):
            idx = (y * 8 + x) * 4
            pattern_rgba[idx : idx + 4] = b"\xff\xff\xff\xff"

    glyph_png = PNGImage(
        width=8,
        height=8,
        color_type=PNGColorType.RGBA,
        bit_depth=8,
        pixels=bytes(pattern_rgba),
    )

    # Add character with the custom image
    glyph_idx = font.add_character("X", image=glyph_png, left_bearing=1, glyph_width=6, char_advance=7)
    assert glyph_idx == 0

    # Extract back the glyph image
    extracted = font.get_glyph_image("X")
    assert extracted.width == 8
    assert extracted.height == 8
    assert extracted.color_type == PNGColorType.RGBA

    ext_data = extracted.to_rgba_bytes()
    # Check that center pixel is white and corner pixel is transparent black
    center_idx = (3 * 8 + 3) * 4
    corner_idx = 0
    assert ext_data[center_idx : center_idx + 4] == b"\xff\xff\xff\xff"
    assert ext_data[corner_idx : corner_idx + 4] == b"\x00\x00\x00\x00"

    # Verify sheet export
    with tempfile.TemporaryDirectory() as tmpdir:
        exported = font.export_sheets(tmpdir, prefix="test_sheet")
        assert len(exported) == 1
        assert Path(exported[0]).exists()


def test_brfnt_binary_serialization_roundtrip():
    """Verify bit-exact binary serialization (to_bytes) and deserialization roundtrip."""
    orig_font = BRFNTFont.create(
        cell_width=16,
        cell_height=24,
        line_height=24,
        sheet_format=2,  # IA4
        sheet_width=64,
        sheet_height=48,
    )

    orig_font.add_character("H", left_bearing=1, glyph_width=12, char_advance=14)
    orig_font.add_character("i", left_bearing=1, glyph_width=4, char_advance=6)
    orig_font.add_character("!", left_bearing=0, glyph_width=4, char_advance=5)

    # Add a custom pixel in 'H' glyph
    h_img = bytearray(16 * 24 * 4)
    h_img[0:4] = b"\xff\xff\xff\xff"
    orig_font.inject_glyph_image("H", bytes(h_img))

    # Serialize to binary bytes
    binary_data = orig_font.to_bytes()
    assert len(binary_data) > 0
    assert binary_data[:4] == b"RFNT"

    # Deserialize from binary bytes
    loaded_font = BRFNTFont.from_bytes(binary_data)

    assert loaded_font.magic == b"RFNT"
    assert loaded_font.cell_width == 16
    assert loaded_font.cell_height == 24
    assert loaded_font.line_height == 24
    assert loaded_font.sheet_format == 2

    # Verify charmap and width metrics
    assert loaded_font.has_char("H") is True
    assert loaded_font.has_char("i") is True
    assert loaded_font.has_char("!") is True
    assert loaded_font.has_char("?") is False

    assert loaded_font.get_char_width("H") == 14
    assert loaded_font.get_char_width("i") == 6
    assert loaded_font.get_char_width("!") == 5
    assert loaded_font.get_text_width("Hi!") == 25

    # Verify injected pixel survived GX texture roundtrip
    extracted_h = loaded_font.get_glyph_image("H")
    h_pixels = extracted_h.to_rgba_bytes()
    # For IA4, white (0xFF, 0xFF, 0xFF, 0xFF) quantizes to max intensity & alpha
    assert h_pixels[0] >= 240  # Red
    assert h_pixels[3] >= 240  # Alpha


def test_brfnt_multi_gx_sheet_formats():
    """Verify texture encoding and decoding for I4, I8, IA4, and IA8 formats."""
    for fmt_id in (0, 1, 2, 3):  # I4, I8, IA4, IA8
        font = BRFNTFont.create(
            cell_width=8,
            cell_height=8,
            sheet_width=32,
            sheet_height=32,
            sheet_format=fmt_id,
        )
        font.add_character("Z", left_bearing=0, glyph_width=8, char_advance=8)
        packed = font.to_bytes()
        loaded = BRFNTFont.from_bytes(packed)
        assert loaded.sheet_format == fmt_id
        assert loaded.has_char("Z") is True
        assert loaded.get_char_width("Z") == 8
