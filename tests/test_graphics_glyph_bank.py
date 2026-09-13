"""
Unit tests for miorom.graphics.glyph_bank and CLI gfx recompose.
"""

import argparse
import io
import os
import tempfile
import pytest
from PIL import Image

from miorom.graphics.glyph_bank import Glyph, GlyphBank
from miorom.cli.main import cmd_gfx


def create_letter_image(letter: str, width: int = 10, height: int = 14, color: tuple = (255, 255, 255, 255)) -> Image.Image:
    """Creates a synthetic glyph image with a solid fill and translucent border."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for y in range(1, height - 1):
        for x in range(1, width - 1):
            img.putpixel((x, y), color)
    # 1-px border
    for y in range(height):
        img.putpixel((0, y), (0, 0, 0, 128))
        img.putpixel((width - 1, y), (0, 0, 0, 128))
    for x in range(width):
        img.putpixel((x, 0), (0, 0, 0, 128))
        img.putpixel((x, height - 1), (0, 0, 0, 128))
    return img


def test_glyph_creation():
    img = create_letter_image("A", 10, 14)
    g = Glyph(char="A", width=10, height=14, rgba=img.tobytes())
    assert g.char == "A"
    assert g.width == 10
    assert g.height == 14
    assert g.advance_x == 10
    out_img = g.to_image()
    assert out_img.size == (10, 14)


def test_harvest_boxes_and_recompose():
    img_a = create_letter_image("A", 10, 14, (255, 0, 0, 255))
    img_b = create_letter_image("B", 12, 14, (0, 255, 0, 255))

    # Combine into single sprite sheet
    sheet = Image.new("RGBA", (30, 20), (0, 0, 0, 0))
    sheet.paste(img_a, (0, 0))
    sheet.paste(img_b, (15, 0))

    bank = GlyphBank()
    bank.harvest_boxes(sheet, {
        "A": (0, 0, 10, 14),
        "B": (15, 0, 12, 14),
    })

    assert "A" in bank.glyphs
    assert "B" in bank.glyphs
    assert bank.glyphs["A"].width == 10
    assert bank.glyphs["B"].width == 12

    # Recompose "ABA"
    recomposed = bank.recompose("ABA", tracking=1, border_overlap=0)
    # Expected width: 10 + 1 + 12 + 1 + 10 = 34
    assert recomposed.width == 34
    assert recomposed.height == 14

    # Recompose with padding and center alignment
    canvas = bank.recompose("A B", space_width=6, target_width=50, target_height=30, align="center")
    assert canvas.size == (50, 30)


def test_harvest_grid():
    sheet = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    # 4 quadrants of 16x16
    q0 = create_letter_image("1", 16, 16)
    q1 = create_letter_image("2", 16, 16)
    q2 = create_letter_image("3", 16, 16)
    q3 = create_letter_image("4", 16, 16)
    sheet.paste(q0, (0, 0))
    sheet.paste(q1, (16, 0))
    sheet.paste(q2, (0, 16))
    sheet.paste(q3, (16, 16))

    bank = GlyphBank()
    bank.harvest_grid(sheet, chars="1234", cell_w=16, cell_h=16)
    assert len(bank.glyphs) == 4
    assert all(c in bank.glyphs for c in "1234")


def test_harvest_widths():
    sheet = Image.new("RGBA", (30, 16), (0, 0, 0, 0))
    g1 = create_letter_image("X", 8, 16)
    g2 = create_letter_image("Y", 12, 16)
    g3 = create_letter_image("Z", 10, 16)
    sheet.paste(g1, (0, 0))
    sheet.paste(g2, (8, 0))
    sheet.paste(g3, (20, 0))

    bank = GlyphBank()
    bank.harvest_widths(sheet, chars="XYZ", widths=[8, 12, 10], height=16)
    assert bank.glyphs["X"].width == 8
    assert bank.glyphs["Y"].width == 12
    assert bank.glyphs["Z"].width == 10


def test_auto_dissect_and_recompose():
    # Construct an image with distinct horizontal glyph blocks separated by 2-px gap
    w_total = 40
    h_total = 16
    strip = Image.new("RGBA", (w_total, h_total), (0, 0, 0, 0))

    g_n = create_letter_image("N", 8, 16)
    g_a = create_letter_image("A", 8, 16)
    g_m = create_letter_image("M", 10, 16)

    # Place with 2 empty columns between them:
    # N: 0..8, gap: 8..10, A: 10..18, gap: 18..20, M: 20..30
    strip.paste(g_n, (0, 0))
    strip.paste(g_a, (10, 0))
    strip.paste(g_m, (20, 0))

    bank = GlyphBank()
    bank.auto_dissect(strip, chars="N A M")
    assert "N" in bank.glyphs
    assert "A" in bank.glyphs
    assert "M" in bank.glyphs

    # Recompose "MAN"
    out = bank.recompose("MAN", tracking=0, border_overlap=1)
    assert out.size[0] > 0
    assert out.size[1] == 16


def test_missing_glyph_raises():
    bank = GlyphBank()
    bank.add_glyph("A", create_letter_image("A", 8, 8))
    with pytest.raises(KeyError, match="Glyph 'B' not found"):
        bank.recompose("AB")


def test_cli_recompose(capsys):
    # Create test image with two blocks "O" and "K"
    sheet = Image.new("RGBA", (30, 16), (0, 0, 0, 0))
    g_o = create_letter_image("O", 10, 16)
    g_k = create_letter_image("K", 10, 16)
    sheet.paste(g_o, (0, 0))
    sheet.paste(g_k, (15, 0))

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_src:
        sheet.save(f_src.name)
        src_path = f_src.name

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f_out:
        out_path = f_out.name

    try:
        args = argparse.Namespace(
            gfx_command="recompose",
            source_image=src_path,
            phrase="O K",
            grid=None,
            grid_chars="",
            target="KO",
            output=out_path,
            tracking=0,
            border_overlap=0,
            space_width=4,
            target_width=None,
            target_height=None,
            align="left",
        )
        cmd_gfx(args)
        out = capsys.readouterr().out
        assert "Recomposed 'KO'" in out
        assert os.path.exists(out_path)
        res_img = Image.open(out_path)
        assert res_img.size == (20, 16)
    finally:
        if os.path.exists(src_path):
            os.remove(src_path)
        if os.path.exists(out_path):
            os.remove(out_path)
