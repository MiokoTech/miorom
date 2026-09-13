"""
Unit tests for miorom.graphics.texture_inspector and CLI gfx commands.
"""

import argparse
import io
import os
import pytest
from PIL import Image

from miorom.graphics.texture_inspector import (
    TextureInspector,
    TextureInspectReport,
    TextureDiffReport,
)
from miorom.platforms.wii.tpl import TPLFile
from miorom.cli.main import cmd_gfx


def create_sample_image(width: int = 16, height: int = 16, with_gradient: bool = False) -> Image.Image:
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            if with_gradient:
                alpha = int(255 * (y / max(1, height - 1)))
                pixels[x, y] = (x * 10, y * 10, 100, alpha)
            else:
                if x < width // 2 and y < height // 2:
                    pixels[x, y] = (255, 0, 0, 255)
                elif x >= width // 2 and y < height // 2:
                    pixels[x, y] = (0, 255, 0, 255)
                elif x < width // 2 and y >= height // 2:
                    pixels[x, y] = (0, 0, 255, 255)
                else:
                    pixels[x, y] = (255, 255, 0, 128)
    return img


def test_texture_inspector_tpl_ci4():
    img = create_sample_image(16, 16)
    tpl = TPLFile.from_image(img, format_id=8, palette_format_id=2)
    tpl_bytes = tpl.to_bytes()

    report = TextureInspector.inspect(tpl_bytes)
    assert isinstance(report, TextureInspectReport)
    assert report.container_type == "TPL"
    assert report.width == 16
    assert report.height == 16
    assert report.format_name == "CI4"
    assert report.is_paletted is True
    assert report.palette_format == "RGB5A3"
    assert report.palette_color_count == 16
    assert report.data_size == len(tpl_bytes)
    assert len(report.summary()) > 0
    assert report.to_dict()["format_name"] == "CI4"


def test_texture_inspector_png():
    img = create_sample_image(16, 16)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()

    report = TextureInspector.inspect(png_bytes)
    assert report.container_type == "PNG"
    assert report.width == 16
    assert report.height == 16
    assert "PNG" in report.format_name


def test_texture_diff_identical():
    img = create_sample_image(16, 16)
    tpl = TPLFile.from_image(img, format_id=5)
    tpl_bytes = tpl.to_bytes()

    diff_report = TextureInspector.diff(tpl_bytes, tpl_bytes)
    assert isinstance(diff_report, TextureDiffReport)
    assert diff_report.dimensions_match is True
    assert diff_report.formats_match is True
    assert diff_report.modified_pixel_count == 0
    assert diff_report.max_delta == 0
    assert diff_report.bounding_box is None
    assert "None (Identical)" in diff_report.summary()


def test_texture_diff_modifications():
    img1 = create_sample_image(16, 16)
    img2 = create_sample_image(16, 16)
    # Modify a 4x4 patch in img2 at (4, 4) to (7, 7)
    for y in range(4, 8):
        for x in range(4, 8):
            img2.putpixel((x, y), (200, 200, 200, 255))

    tpl1 = TPLFile.from_image(img1, format_id=6)
    tpl2 = TPLFile.from_image(img2, format_id=6)

    diff_report = TextureInspector.diff(tpl1.to_bytes(), tpl2.to_bytes())
    assert diff_report.dimensions_match is True
    assert diff_report.formats_match is True
    assert diff_report.modified_pixel_count == 16
    assert diff_report.max_delta > 0
    assert diff_report.bounding_box == (4, 4, 7, 7)


def test_texture_diff_dimension_mismatch():
    img1 = create_sample_image(16, 16)
    img2 = create_sample_image(32, 16)

    tpl1 = TPLFile.from_image(img1, format_id=5)
    tpl2 = TPLFile.from_image(img2, format_id=5)

    diff_report = TextureInspector.diff(tpl1.to_bytes(), tpl2.to_bytes())
    assert diff_report.dimensions_match is False
    assert any("Dimension mismatch" in w for w in diff_report.warnings)


def test_texture_diff_alpha_degradation():
    img_smooth = create_sample_image(16, 16, with_gradient=True)
    # Binary alpha version: round alpha to 0 or 255
    img_binary = Image.new("RGBA", (16, 16))
    for y in range(16):
        for x in range(16):
            r, g, b, a = img_smooth.getpixel((x, y))
            img_binary.putpixel((x, y), (r, g, b, 255 if a >= 128 else 0))

    tpl_smooth = TPLFile.from_image(img_smooth, format_id=6)
    tpl_binary = TPLFile.from_image(img_binary, format_id=6)

    diff_report = TextureInspector.diff(tpl_smooth.to_bytes(), tpl_binary.to_bytes())
    assert diff_report.alpha_preserved is False
    assert any("alpha gradients" in w for w in diff_report.warnings)


def test_texture_ascii_render():
    img = create_sample_image(16, 16)
    tpl = TPLFile.from_image(img, format_id=5)
    ascii_out = TextureInspector.render_ascii(tpl.to_bytes(), max_width=20)
    assert len(ascii_out) > 0
    assert isinstance(ascii_out, str)


def test_cli_gfx_integration(capsys):
    img = create_sample_image(16, 16)
    tpl = TPLFile.from_image(img, format_id=8, palette_format_id=2)
    buf = io.BytesIO()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".tpl", delete=False) as f:
        f.write(tpl.to_bytes())
        tmp_path = f.name

    try:
        # Test inspect
        args_inspect = argparse.Namespace(gfx_command="inspect", input_file=tmp_path, json=False)
        cmd_gfx(args_inspect)
        out = capsys.readouterr().out
        assert "MioROM Forensic Texture Inspection" in out
        assert "CI4" in out

        # Test json inspect
        args_json = argparse.Namespace(gfx_command="inspect", input_file=tmp_path, json=True)
        cmd_gfx(args_json)
        out_json = capsys.readouterr().out
        assert '"container_type": "TPL"' in out_json

        # Test ascii
        args_ascii = argparse.Namespace(gfx_command="ascii", input_file=tmp_path, width=20)
        cmd_gfx(args_ascii)
        out_ascii = capsys.readouterr().out
        assert len(out_ascii) > 0

        # Test diff
        args_diff = argparse.Namespace(
            gfx_command="diff",
            original_file=tmp_path,
            modified_file=tmp_path,
            json=False,
        )
        cmd_gfx(args_diff)
        out_diff = capsys.readouterr().out
        assert "MioROM Forensic Texture Diff" in out_diff
        assert "None (Identical)" in out_diff

    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
