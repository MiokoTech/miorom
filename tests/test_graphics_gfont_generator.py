"""
Unit tests for miorom.graphics.gfont_generator.
"""

import os
import tempfile
import pytest
from PIL import Image

from miorom.graphics.gfont_generator import GFontCGenerator
from miorom.platforms.wii.tpl import TPLFile


def test_gfont_generator_init_and_available_characters():
    gen = GFontCGenerator()
    chars = gen.available_characters
    assert "A" in chars
    assert "K" in chars
    assert "Y" in chars
    assert "U" in chars
    assert len(chars) >= 22


def test_gfont_generator_render_image():
    gen = GFontCGenerator()
    im = gen.render_image("KAYU", width=80, height=20, align="center", tracking=1, border_overlap=1)
    assert im.size == (80, 20)
    assert im.mode == "RGBA"

    # Verify non-empty pixels exist and are centered
    alpha = [im.getpixel((x, 10))[3] for x in range(80)]
    assert any(a > 0 for a in alpha[:40])
    assert any(a > 0 for a in alpha[40:])


def test_gfont_generator_render_ascii():
    gen = GFontCGenerator()
    ascii_out = gen.render_ascii("KAYU", width=80, height=20)
    assert isinstance(ascii_out, str)
    lines = ascii_out.splitlines()
    assert len(lines) == 20
    assert any(line.strip() for line in lines)


def test_gfont_generator_render_tpl_rgb5a3():
    gen = GFontCGenerator()
    tpl = gen.render_tpl("KAYU", width=80, height=20, format="RGB5A3")
    assert isinstance(tpl, TPLFile)
    assert len(tpl.images) == 1
    img = tpl.images[0]
    assert img.format_id == 5  # RGB5A3
    assert (img.width, img.height) == (80, 20)
    tpl_bytes = tpl.to_bytes()
    assert len(tpl_bytes) == 3264


def test_gfont_generator_render_tpl_ci4():
    gen = GFontCGenerator()
    tpl = gen.render_tpl("KAYU", width=80, height=20, format="CI4")
    assert isinstance(tpl, TPLFile)
    assert len(tpl.images) == 1
    img = tpl.images[0]
    assert img.format_id == 8  # CI4
    assert (img.width, img.height) == (80, 20)
    tpl_bytes = tpl.to_bytes()
    assert len(tpl_bytes) == 1088


def test_gfont_generator_generate_and_save():
    gen = GFontCGenerator()
    with tempfile.TemporaryDirectory() as td:
        png_p = os.path.join(td, "test_kayu.png")
        tpl_p = os.path.join(td, "test_kayu.tpl")

        im, tpl = gen.generate_and_save(
            "KAYU",
            out_png=png_p,
            out_tpl=tpl_p,
            width=80,
            height=20,
            format="RGB5A3",
        )

        assert os.path.exists(png_p)
        assert os.path.exists(tpl_p)
        assert os.path.getsize(tpl_p) == 3264

        loaded_tpl = TPLFile.from_file(tpl_p)
        assert loaded_tpl.images[0].format_id == 5
