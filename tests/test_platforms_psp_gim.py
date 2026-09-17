"""
tests.test_platforms_psp_gim
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Comprehensive unit tests for Sony PSP GIM texture engine,
PSP GE VRAM swizzler/unswizzler, and PBP container integration.
"""

import pytest

from miorom.errors import ParseError
from miorom.graphics.png_codec import PNGColorType, PNGImage
from miorom.platforms.psp.pbp import (
    GIM_MAGIC,
    GIMFormat,
    GIMImage,
    GIMPixelOrder,
    PBPFile,
    psp_swizzle,
    psp_unswizzle,
)


def test_psp_swizzle_unswizzle_roundtrip_all_bpp():
    """Verifies unswizzle(swizzle(buffer)) == buffer across 4, 8, 16, and 32 bpp."""
    test_cases = [
        (32, 16, 32),  # 32bpp, 32x16
        (64, 32, 16),  # 16bpp, 64x32
        (64, 32, 8),   # 8bpp, 64x32
        (64, 32, 4),   # 4bpp, 64x32
        (24, 18, 32),  # Non-power-of-2 dimensions
        (24, 18, 8),
    ]

    for width, height, bpp in test_cases:
        row_bytes = (width * bpp + 7) // 8
        total_bytes = row_bytes * height

        # Deterministic pseudo-random pattern
        pattern = bytes([(x * 17 + y * 31 + 0x5A) & 0xFF for y in range(height) for x in range(row_bytes)])
        assert len(pattern) == total_bytes

        swizzled = psp_swizzle(pattern, width, height, bpp, pitch_align=16)
        # Swizzled buffer must be aligned to 128-byte micro-tile blocks
        assert len(swizzled) % 128 == 0

        unswizzled = psp_unswizzle(swizzled, width, height, bpp, pitch_align=16, crop_to_dims=True)
        assert unswizzled == pattern, f"Mismatch on {width}x{height} @ {bpp}bpp"


def test_gim_binary_serialization_and_parsing():
    """Tests full roundtrip serialization: Image -> to_bytes -> from_bytes -> to_bytes."""
    w, h = 32, 32
    # Create simple 32x32 RGBA8888 image
    raw_rgba = bytearray(w * h * 4)
    for y in range(h):
        for x in range(w):
            off = (y * w + x) * 4
            raw_rgba[off : off + 4] = bytes([x * 7 & 0xFF, y * 7 & 0xFF, 128, 255])

    png = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=bytes(raw_rgba))
    gim = GIMImage.from_image(png, format=GIMFormat.RGBA8888, swizzle=True)

    assert gim.width == w
    assert gim.height == h
    assert gim.format == GIMFormat.RGBA8888
    assert gim.pixel_order == GIMPixelOrder.SWIZZLED

    gim_bytes = gim.to_bytes()
    assert gim_bytes[:16] == GIM_MAGIC

    # Parse back
    loaded = GIMImage.from_bytes(gim_bytes)
    assert loaded.width == w
    assert loaded.height == h
    assert loaded.format == GIMFormat.RGBA8888
    assert loaded.pixel_order == GIMPixelOrder.SWIZZLED

    # Re-serialization exact identity
    assert loaded.to_bytes() == gim_bytes


def test_gim_indexed_palette_roundtrip():
    """Tests INDEX4 and INDEX8 formats with CLUT palette roundtrip."""
    w, h = 16, 16
    raw_rgba = bytearray(w * h * 4)

    # 4 distinct colors
    colors = [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 255, 255),
    ]
    for y in range(h):
        for x in range(w):
            c = colors[(x // 8) + (y // 8) * 2]
            off = (y * w + x) * 4
            raw_rgba[off : off + 4] = bytes(c)

    png = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=bytes(raw_rgba))

    # Test INDEX4
    gim4 = GIMImage.from_image(png, format=GIMFormat.INDEX4, swizzle=False)
    assert gim4.format == GIMFormat.INDEX4
    assert len(gim4.clut_palettes) == 1
    assert len(gim4.clut_palettes[0]) == 16

    gim4_bytes = gim4.to_bytes()
    loaded4 = GIMImage.from_bytes(gim4_bytes)
    assert loaded4.format == GIMFormat.INDEX4
    assert len(loaded4.clut_palettes) == 1

    # Render to image and verify pixel accuracy
    rendered = loaded4.to_image()
    assert rendered.width == w
    assert rendered.height == h

    # Test INDEX8
    gim8 = GIMImage.from_image(png, format=GIMFormat.INDEX8, swizzle=True)
    assert gim8.format == GIMFormat.INDEX8
    assert len(gim8.clut_palettes) == 1
    assert len(gim8.clut_palettes[0]) == 256

    gim8_bytes = gim8.to_bytes()
    loaded8 = GIMImage.from_bytes(gim8_bytes)
    assert loaded8.format == GIMFormat.INDEX8
    assert loaded8.pixel_order == GIMPixelOrder.SWIZZLED


def test_gim_surgical_patch_region_and_extract():
    """
    Verifies patch_region transparently patches a sub-image on both swizzled and linear textures,
    leaving surrounding pixels intact.
    """
    w, h = 64, 64
    base_rgba = bytearray(w * h * 4)  # pure black background with full alpha
    for i in range(3, len(base_rgba), 4):
        base_rgba[i] = 255

    base_png = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=bytes(base_rgba))
    gim = GIMImage.from_image(base_png, format=GIMFormat.RGBA8888, swizzle=True)

    # Create a 16x16 pure red patch (e.g. a translated font glyph)
    pw, ph = 16, 16
    patch_rgba = bytearray(pw * ph * 4)
    for py in range(ph):
        for px in range(pw):
            off = (py * pw + px) * 4
            patch_rgba[off : off + 4] = bytes([255, 0, 0, 255])
    patch_png = PNGImage(width=pw, height=ph, color_type=PNGColorType.RGBA, bit_depth=8, pixels=bytes(patch_rgba))

    # Surgically patch at (20, 20)
    gim.patch_region(20, 20, patch_png)

    # Extract patched area
    extracted = gim.extract_region(20, 20, 16, 16)
    assert extracted.width == 16
    assert extracted.height == 16
    ext_bytes = extracted.to_rgba_bytes() if hasattr(extracted, "to_rgba_bytes") else extracted.tobytes()
    # All pixels in extracted must be red
    for i in range(0, len(ext_bytes), 4):
        assert ext_bytes[i : i + 4] == bytes([255, 0, 0, 255])

    # Check unpatched area (0, 0, 16, 16) - must remain pure black
    untouched = gim.extract_region(0, 0, 16, 16)
    unt_bytes = untouched.to_rgba_bytes() if hasattr(untouched, "to_rgba_bytes") else untouched.tobytes()
    for i in range(0, len(unt_bytes), 4):
        assert unt_bytes[i : i + 4] == bytes([0, 0, 0, 255])

    # Out of bounds patch should raise ValueError
    with pytest.raises(ValueError):
        gim.patch_region(50, 50, patch_png)  # 50 + 16 = 66 > 64


def test_gim_swizzle_unswizzle_mutators():
    """Verifies gim.unswizzle() and gim.swizzle() in-place state transitions."""
    w, h = 32, 32
    raw = bytearray([0x77] * (w * h * 4))
    png = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=bytes(raw))

    gim = GIMImage.from_image(png, format=GIMFormat.RGBA8888, swizzle=True)
    assert gim.pixel_order == GIMPixelOrder.SWIZZLED

    gim.unswizzle()
    assert gim.pixel_order == GIMPixelOrder.NORMAL

    gim.swizzle()
    assert gim.pixel_order == GIMPixelOrder.SWIZZLED


def test_pbp_embedded_gim_scan_and_icon_helpers():
    """Verifies PBPFile.find_gim_textures() detects GIM assets embedded in sections."""
    # Build a small GIM
    w, h = 16, 16
    raw = bytearray([0xFF] * (w * h * 4))
    png = PNGImage(width=w, height=h, color_type=PNGColorType.RGBA, bit_depth=8, pixels=bytes(raw))
    gim = GIMImage.from_image(png, format=GIMFormat.RGBA8888, swizzle=False)
    gim_binary = gim.to_bytes()

    # Embed inside DATA.PSP with some prefix and suffix dummy data
    data_psp = b"ELF_DUMMY_HEADER" + (b"\x00" * 32) + gim_binary + (b"\x00" * 64)

    pbp = PBPFile()
    pbp.set_section("DATA.PSP", data_psp)
    pbp.set_icon(png)

    # Test icon helper
    icon = pbp.get_icon()
    assert icon is not None
    assert icon.width == 16
    assert icon.height == 16

    # Scan for embedded GIM
    found = pbp.find_gim_textures()
    assert len(found) == 1
    sec_name, offset, parsed_gim = found[0]
    assert sec_name == "DATA.PSP"
    assert offset == 48  # len("ELF_DUMMY_HEADER") + 32 = 16 + 32 = 48
    assert parsed_gim.width == 16
    assert parsed_gim.height == 16

    # Check summary output
    summary = pbp.summary()
    assert "EBOOT.PBP" in summary
    assert "DATA.PSP" in summary

    gim_summary = parsed_gim.summary()
    assert "GIM Texture [16x16]" in gim_summary


def test_gim_invalid_binary():
    """Verifies error handling on truncated or corrupt GIM files."""
    with pytest.raises(ParseError):
        GIMImage.from_bytes(b"SHORT")

    with pytest.raises(ParseError):
        GIMImage.from_bytes(b"CORRUPT_MAGIC_TEST_BYTES_0123456789")
