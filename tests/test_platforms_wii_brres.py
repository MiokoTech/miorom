"""
Unit tests for Nintendo Wii BRRES & TEX0 Resource Engine.
Tests BresIndexGroup Patricia trie, TEX0Image codecs, PLT0Palette, and BRRESFile container.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from miorom.core.schema import U32
from miorom.errors import ParseError
from miorom.graphics.png_codec import PNGCodec, PNGColorType, PNGImage
from miorom.platforms.wii import (
    BresIndexGroup,
    BRRESFile,
    PLT0Palette,
    TEX0Image,
)


def _make_test_rgba(width: int, height: int) -> bytes:
    """Creates a deterministic gradient RGBA image."""
    pixels = bytearray(width * height * 4)
    for y in range(height):
        for x in range(width):
            idx = (y * width + x) * 4
            pixels[idx] = (x * 255) // max(1, width - 1)      # R
            pixels[idx + 1] = (y * 255) // max(1, height - 1)  # G
            pixels[idx + 2] = 128                              # B
            pixels[idx + 3] = 255                              # A
    return bytes(pixels)


def test_bres_index_group_build_and_find() -> None:
    """Tests NW4R Patricia tree construction, serialization, and name lookup."""
    items = [
        ("3DModels(NW4R)", 0x100),
        ("Textures(NW4R)", 0x200),
        ("Palettes(NW4R)", 0x300),
        ("AnmChr(NW4R)", 0x400),
        ("AnmClr(NW4R)", 0x500),
    ]

    group = BresIndexGroup.build(items)
    raw = group.to_bytes()
    assert len(raw) >= 8 + (len(items) + 1) * 16

    g2 = BresIndexGroup.from_bytes(raw)
    assert len(g2.entries) == len(items) + 1

    # Verify Patricia tree find()
    for name, expected_off in items:
        entry = g2.find(name)
        assert entry is not None, f"Failed to find {name}"
        assert entry.name == name
        assert entry.data_offset == expected_off

    # Verify non-existent lookup
    assert g2.find("NonExistent(NW4R)") is None


def test_bres_index_group_empty() -> None:
    """Tests empty index group edge case."""
    group = BresIndexGroup.build([])
    raw = group.to_bytes()
    assert len(raw) == 24
    g2 = BresIndexGroup.from_bytes(raw)
    assert len(g2.entries) == 1
    assert g2.find("anything") is None


def test_tex0_cmpr_roundtrip() -> None:
    """Tests TEX0 image creation, CMPR (DXT1) encoding, serialization, and decoding."""
    w, h = 16, 16
    rgba = _make_test_rgba(w, h)
    png_img = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba)

    tex = TEX0Image.from_image(png_img, name="test_cmpr", format_id=14)
    assert tex.name == "test_cmpr"
    assert tex.width == 16
    assert tex.height == 16
    assert tex.format_id == 14
    assert tex.format_name == "CMPR"
    assert not tex.is_paletted()

    raw_tex0 = tex.to_bytes(bres_offset=-0x80)
    assert raw_tex0[:4] == b"TEX0"
    assert len(raw_tex0) % 32 == 0

    parsed = TEX0Image.from_bytes(raw_tex0, name="test_cmpr")
    assert parsed.width == 16
    assert parsed.height == 16
    assert parsed.format_id == 14

    decoded_rgba = parsed.decode_rgba()
    assert len(decoded_rgba) == w * h * 4

    # Verify summary string
    summ = parsed.summary()
    assert "CMPR" in summ
    assert "16x16" in summ


def test_tex0_rgb565_and_rgba8() -> None:
    """Tests TEX0 formats RGB565 (ID 4) and RGBA8 (ID 6)."""
    w, h = 8, 8
    rgba = _make_test_rgba(w, h)
    png_img = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba)

    # RGB565
    tex_565 = TEX0Image.from_image(png_img, name="rgb565_tex", format_id=4)
    assert tex_565.format_name == "RGB565"
    raw_565 = tex_565.to_bytes()
    parsed_565 = TEX0Image.from_bytes(raw_565)
    dec_565 = parsed_565.decode_rgba()
    assert len(dec_565) == w * h * 4

    # RGBA8
    tex_rgba8 = TEX0Image.from_image(png_img, name="rgba8_tex", format_id=6)
    assert tex_rgba8.format_name == "RGBA8"
    raw_rgba8 = tex_rgba8.to_bytes()
    parsed_rgba8 = TEX0Image.from_bytes(raw_rgba8)
    dec_rgba8 = parsed_rgba8.decode_rgba()
    assert len(dec_rgba8) == w * h * 4


def test_tex0_paletted_ci8_and_plt0() -> None:
    """Tests CI8 (format 9) paletted texture and PLT0 palette generation."""
    w, h = 8, 8
    rgba = _make_test_rgba(w, h)
    png_img = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba)

    tex_ci8 = TEX0Image.from_image(png_img, name="ci8_tex", format_id=9, palette_format=2)
    assert tex_ci8.is_paletted()
    assert tex_ci8.palette_data is not None
    assert len(tex_ci8.palette_data) == 256 * 2  # 256 colors * 2 bytes = 512 bytes

    # Test PLT0Palette
    plt0 = PLT0Palette(
        name="ci8_tex",
        format_id=tex_ci8.palette_format,
        num_entries=len(tex_ci8.palette_data) // 2,
        data=tex_ci8.palette_data,
    )
    plt0_raw = plt0.to_bytes()
    assert plt0_raw[:4] == b"PLT0"
    parsed_plt0 = PLT0Palette.from_bytes(plt0_raw, name="ci8_tex")
    assert parsed_plt0.num_entries == 256
    colors = parsed_plt0.decode_colors()
    assert len(colors) == 256

    # Test decoding paletted TEX0
    dec = tex_ci8.decode_rgba()
    assert len(dec) == w * h * 4


def test_brres_file_full_roundtrip() -> None:
    """Tests complete BRRES archive synthesis and parsing with non-texture section preservation."""
    w, h = 16, 16
    rgba = _make_test_rgba(w, h)
    png_img = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba)

    tex_logo = TEX0Image.from_image(png_img, name="title_logo", format_id=14)
    tex_btn = TEX0Image.from_image(png_img, name="btn_a", format_id=4)
    plt_dummy = PLT0Palette(name="menu_pal", format_id=2, num_entries=16, data=b"\x00\x00" * 16)

    # Dummy MDL0 3D model section (preserved byte-exact)
    dummy_mdl0 = bytearray(64)
    dummy_mdl0[:4] = b"MDL0"
    dummy_mdl0[4:8] = U32().pack(64, endian=">")
    dummy_mdl0[16:20] = b"TEST"

    brres = BRRESFile(
        textures={"title_logo": tex_logo, "btn_a": tex_btn},
        palettes={"menu_pal": plt_dummy},
        other_sections={"3DModels(NW4R)": {"mario_model": bytes(dummy_mdl0)}},
    )

    raw_brres = brres.to_bytes()
    assert raw_brres[:4] == b"bres"
    assert len(raw_brres) % 32 == 0

    # Parse back
    loaded = BRRESFile.from_bytes(raw_brres)
    assert len(loaded.textures) == 2
    assert "title_logo" in loaded.textures
    assert "btn_a" in loaded.textures
    assert loaded.get_texture("title_logo").width == 16
    assert loaded.get_texture("btn_a").format_name == "RGB565"

    assert len(loaded.palettes) == 1
    assert "menu_pal" in loaded.palettes
    assert loaded.palettes["menu_pal"].num_entries == 16

    # Verify non-texture MDL0 section preservation
    assert "3DModels(NW4R)" in loaded.other_sections
    assert "mario_model" in loaded.other_sections["3DModels(NW4R)"]
    restored_mdl0 = loaded.other_sections["3DModels(NW4R)"]["mario_model"]
    assert restored_mdl0[:4] == b"MDL0"
    assert restored_mdl0[16:20] == b"TEST"

    # Verify summary
    summ = loaded.summary()
    assert "title_logo" in summ
    assert "btn_a" in summ
    assert "3DModels(NW4R)" in summ


def test_brres_texture_replacement() -> None:
    """Tests replacing a texture in a BRRES archive and verifying untouched sections."""
    w, h = 16, 16
    rgba_red = b"\xFF\x00\x00\xFF" * (w * h)
    rgba_blue = b"\x00\x00\xFF\xFF" * (w * h)

    tex_orig = TEX0Image.from_image(
        PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba_red),
        name="bg",
        format_id=14,
    )
    dummy_chr0 = b"CHR0" + b"\x00\x00\x00\x20\x00\x00\x00\x03\x00\x00\x00\x00" + b"\x00" * 16

    brres = BRRESFile(
        textures={"bg": tex_orig},
        other_sections={"AnmChr(NW4R)": {"walk_anim": dummy_chr0}},
    )
    raw1 = brres.to_bytes()

    # Load and replace texture with blue image
    loaded = BRRESFile.from_bytes(raw1)
    new_img = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba_blue)
    loaded.set_texture("bg", new_img, format_id=14)

    raw2 = loaded.to_bytes()
    reloaded = BRRESFile.from_bytes(raw2)

    # Verify updated texture
    updated_tex = reloaded.get_texture("bg")
    decoded = updated_tex.decode_rgba()
    # Blue channel at pixel 0 should be dominant
    assert decoded[0] < 50     # R
    assert decoded[2] > 200    # B

    # Verify CHR0 animation is untouched
    assert "AnmChr(NW4R)" in reloaded.other_sections
    assert reloaded.other_sections["AnmChr(NW4R)"]["walk_anim"][:4] == b"CHR0"


def test_tex0_png_export() -> None:
    """Tests zero-dependency PNG export from TEX0Image."""
    w, h = 8, 8
    rgba = _make_test_rgba(w, h)
    tex = TEX0Image.from_image(
        PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba),
        name="export_test",
        format_id=14,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "exported.png")
        tex.to_png(out_path)
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0

        # Decode exported PNG to verify validity
        with open(out_path, "rb") as f:
            png_bytes = f.read()
        pw, ph, p_rgba = PNGCodec.png_to_rgba(png_bytes)
        assert pw == w
        assert ph == h
        assert len(p_rgba) == w * h * 4


def test_brres_file_save_and_from_file() -> None:
    """Tests saving and loading BRRES files from disk."""
    w, h = 8, 8
    rgba = _make_test_rgba(w, h)
    tex = TEX0Image.from_image(
        PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba),
        name="disk_tex",
        format_id=4,
    )
    brres = BRRESFile(textures={"disk_tex": tex})

    with tempfile.TemporaryDirectory() as tmpdir:
        brres_path = os.path.join(tmpdir, "test.brres")
        brres.save(brres_path)
        assert os.path.exists(brres_path)

        loaded = BRRESFile.from_file(brres_path)
        assert len(loaded.textures) == 1
        assert "disk_tex" in loaded.textures
        assert loaded.get_texture("disk_tex").width == 8


def test_brres_errors() -> None:
    """Tests error handling for malformed data and missing assets."""
    with pytest.raises(ParseError):
        BRRESFile.from_bytes(b"bad")
    with pytest.raises(ParseError):
        BRRESFile.from_bytes(b"bres" + b"\x00" * 4)
    with pytest.raises(ParseError):
        TEX0Image.from_bytes(b"NOT_TEX0")
    with pytest.raises(ParseError):
        PLT0Palette.from_bytes(b"NOT_PLT0")

    brres = BRRESFile()
    with pytest.raises(KeyError):
        brres.get_texture("nonexistent")
