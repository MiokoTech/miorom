"""
Unit tests for FontDissector, FontCandidate, and VWF Width Table Hunter.
"""

import json
import pytest
import struct

from miorom.graphics.font_dissector import (
    FontDissector,
    FontCandidate,
    FontGeometry,
    DissectedGlyph,
    WidthTableCandidate,
)
from miorom.graphics.font_injector import LATIN_8X8_BITMAPS


def test_glyph_pixels_roundtrip_1bpp():
    """Test encoding and decoding 1bpp 8x8, 8x16, and 16x16 glyphs."""
    geom_8x8 = FontGeometry(8, 8, 1, "1bpp_linear", 8)

    # Glyph 'A' from LATIN_8X8_BITMAPS
    bitmap_a = LATIN_8X8_BITMAPS["A"]
    raw_a = bytes(bitmap_a)

    pixels = FontDissector.decode_glyph_pixels(raw_a, geom_8x8)
    assert len(pixels) == 64
    assert pixels[0] == 0  # top left margin

    reencoded = FontDissector.encode_glyph_pixels(pixels, geom_8x8)
    assert reencoded == raw_a

    # Test 8x16 1bpp
    geom_8x16 = FontGeometry(8, 16, 1, "1bpp_linear", 16)
    raw_16 = bytes(list(bitmap_a) + [0] * 8)
    pixels_16 = FontDissector.decode_glyph_pixels(raw_16, geom_8x16)
    assert len(pixels_16) == 128
    reencoded_16 = FontDissector.encode_glyph_pixels(pixels_16, geom_8x16)
    assert reencoded_16 == raw_16

    # Test 16x16 1bpp
    geom_16x16 = FontGeometry(16, 16, 1, "1bpp_linear", 32)
    raw_kanji = bytearray(32)
    raw_kanji[2] = 0x3C  # row 1
    raw_kanji[3] = 0x3C
    pixels_k = FontDissector.decode_glyph_pixels(bytes(raw_kanji), geom_16x16)
    assert len(pixels_k) == 256
    reencoded_k = FontDissector.encode_glyph_pixels(pixels_k, geom_16x16)
    assert reencoded_k == bytes(raw_kanji)


def test_glyph_pixels_roundtrip_tile_formats():
    """Test 2bpp (GB) and 4bpp (Genesis/GBA) tile codecs."""
    geom_gb = FontGeometry(8, 8, 2, "gb_2bpp", 16)
    # Create arbitrary 2bpp test tile
    pixels = [0] * 64
    pixels[10] = 1
    pixels[11] = 2
    pixels[12] = 3
    encoded_gb = FontDissector.encode_glyph_pixels(pixels, geom_gb)
    assert len(encoded_gb) == 16
    decoded_gb = FontDissector.decode_glyph_pixels(encoded_gb, geom_gb)
    assert decoded_gb == pixels

    # Genesis 4bpp
    geom_gen = FontGeometry(8, 8, 4, "genesis_4bpp", 32)
    pixels_4 = [0] * 64
    pixels_4[0] = 5
    pixels_4[1] = 12
    encoded_gen = FontDissector.encode_glyph_pixels(pixels_4, geom_gen)
    assert len(encoded_gen) == 32
    decoded_gen = FontDissector.decode_glyph_pixels(encoded_gen, geom_gen)
    assert decoded_gen == pixels_4


def test_measure_glyph():
    """Test bounding box calculation and natural advance width."""
    geom = FontGeometry(8, 8, 1, "1bpp_linear", 8)

    # Empty space glyph
    empty_pixels = [0] * 64
    bbox_space, adv_w_space, adv_h_space = FontDissector._measure_glyph(empty_pixels, 8, 8)
    assert bbox_space == (0, 0, 0, 0)
    assert adv_w_space == 4  # space width default

    # Glyph 'A'
    raw_a = bytes(LATIN_8X8_BITMAPS["A"])
    pixels_a = FontDissector.decode_glyph_pixels(raw_a, geom)
    bbox_a, adv_w_a, adv_h_a = FontDissector._measure_glyph(pixels_a, 8, 8)
    min_x, min_y, max_x, max_y = bbox_a
    assert min_x >= 1
    assert max_x <= 7
    assert adv_w_a >= 6


def test_scan_fonts_1bpp():
    """Test heuristic detection of a 1bpp font bank embedded in a noisy ROM buffer."""
    geom = FontGeometry(8, 8, 1, "1bpp_linear", 8)

    # Build 64 valid 1bpp font glyphs from LATIN_8X8_BITMAPS and numbers
    sample_chars = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
    font_bytes = bytearray()
    for c in sample_chars:
        bitmap = LATIN_8X8_BITMAPS.get(c, (0x00, 0x3C, 0x42, 0x42, 0x7E, 0x42, 0x42, 0x00))
        font_bytes.extend(bitmap)

    assert len(font_bytes) == 64 * 8  # 512 bytes

    # Construct ROM: noise + font bank at 0x1000 + noise
    rom = bytearray(b"\xCC" * 8192)
    rom[0x1000 : 0x1000 + len(font_bytes)] = font_bytes

    candidates = FontDissector.scan_fonts(
        bytes(rom),
        min_glyphs=32,
        max_bpp=1,
        step=8,
    )

    assert len(candidates) >= 1
    top = candidates[0]
    assert top.offset == 0x1000
    assert top.glyph_count >= 64
    assert top.geometry.format_name == "1bpp_linear"
    assert top.geometry.bpp == 1
    assert top.confidence >= 0.85
    assert len(top.glyphs) >= 64


def test_hunt_width_table():
    """Test discovering a VWF width table in ROM data."""
    glyph_count = 64
    # Create realistic width distribution (varying between 3 and 8)
    widths = [
        4, 2, 4, 6, 6, 6, 6, 2, 4, 4, 5, 5, 3, 5, 3, 5,
        6, 5, 6, 6, 6, 6, 6, 6, 6, 6, 3, 3, 5, 5, 5, 5,
        6, 6, 6, 6, 6, 6, 6, 6, 4, 5, 6, 5, 7, 7, 6, 6,
        6, 6, 6, 6, 6, 6, 6, 7, 6, 6, 6, 4, 5, 4, 5, 6,
    ]
    width_bytes = bytes(widths)

    rom = bytearray(b"\xFF" * 4096)
    rom[0x200 : 0x200 + glyph_count] = width_bytes

    tables = FontDissector.hunt_width_table(
        bytes(rom),
        glyph_count=glyph_count,
        max_glyph_width=8,
    )

    assert len(tables) >= 1
    top = tables[0]
    assert top.offset == 0x200
    assert top.entry_count == 64
    assert top.widths == widths
    assert 4.0 <= top.average_width <= 7.0
    assert top.confidence >= 0.85


def test_auto_dissect_and_export():
    """Test full auto-dissection, PNG spritesheet export, and JSON metrics export."""
    sample_chars = " !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_"
    font_bytes = bytearray()
    for c in sample_chars:
        bitmap = LATIN_8X8_BITMAPS.get(c, (0x00, 0x3C, 0x42, 0x42, 0x7E, 0x42, 0x42, 0x00))
        font_bytes.extend(bitmap)

    # Width table
    widths = bytes([6 if c != " " else 4 for c in sample_chars])

    rom = bytearray(b"\x00" * 4096)
    rom[0x400 : 0x400 + len(font_bytes)] = font_bytes
    rom[0x700 : 0x700 + len(widths)] = widths

    candidate = FontDissector.auto_dissect(bytes(rom), min_glyphs=32)
    assert candidate is not None
    assert candidate.offset == 0x400
    assert candidate.glyph_count >= 64

    # Export PNG spritesheet
    png_data = candidate.export_sheet_png(columns=16)
    assert png_data.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_data) > 100

    # Export JSON metrics
    metrics_json = candidate.export_metrics_json()
    metrics = json.loads(metrics_json)
    assert metrics["font_offset"] == "0x00000400"
    assert metrics["glyph_count"] >= 64
    assert len(metrics["glyphs"]) >= 64
    assert "bounding_box" in metrics["glyphs"][0]


def test_inject_glyphs_and_width_table():
    """Test roundtrip modification and injection of custom glyphs and width tables."""
    geom = FontGeometry(8, 8, 1, "1bpp_linear", 8)
    initial_font = bytearray(b"\x00" * (64 * 8))

    candidate = FontCandidate(
        offset=0x100,
        glyph_count=64,
        geometry=geom,
        confidence=0.95,
        glyphs=[],
    )

    rom = bytearray(b"\x00" * 2048)
    rom[0x100 : 0x100 + len(initial_font)] = initial_font

    # Inject custom pixel pattern for glyph index 5
    custom_pixels = [1 if (x == y or x == 7 - y) else 0 for y in range(8) for x in range(8)]
    updated_rom = FontDissector.inject_glyphs(
        rom,
        candidate,
        {5: custom_pixels},
    )

    # Verify bytes at offset 0x100 + 5*8
    target_offset = 0x100 + 5 * 8
    decoded = FontDissector.decode_glyph_pixels(updated_rom[target_offset : target_offset + 8], geom)
    assert decoded == custom_pixels

    # Inject custom width table
    new_widths = [5, 6, 7, 8, 4]
    updated_rom = FontDissector.inject_width_table(
        updated_rom,
        table_offset=0x500,
        widths=new_widths,
        entry_size=1,
    )

    assert list(updated_rom[0x500 : 0x505]) == new_widths
