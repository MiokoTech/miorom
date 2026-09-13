import pytest
from miorom.graphics.pixel_math import (
    interpolate_color,
    apply_vertical_gradient,
    apply_outline_1px,
)
from miorom.graphics.glyph_bank import find_luminance_valleys, GlyphBank


def test_interpolate_color():
    white = (255, 255, 255, 255)
    black = (0, 0, 0, 255)
    mid = interpolate_color(white, black, 0.5)
    assert mid == (127, 127, 127, 255)

    # Clamping
    assert interpolate_color(white, black, -1.0) == white
    assert interpolate_color(white, black, 2.0) == black


def test_apply_vertical_gradient():
    # 2x2 mask: top row opaque (255), bottom row half (128)
    mask = bytes([255, 255, 128, 128])
    red = (255, 0, 0, 255)
    blue = (0, 0, 255, 255)

    grad = apply_vertical_gradient(mask, 2, 2, red, blue)
    assert len(grad) == 16  # 2x2x4

    # Top-left pixel (y=0, x=0): should be pure red with alpha 255
    assert grad[0] == 255
    assert grad[1] == 0
    assert grad[2] == 0
    assert grad[3] == 255

    # Bottom-left pixel (y=1, x=0): should be blue with alpha 128
    assert grad[8] == 0
    assert grad[9] == 0
    assert grad[10] == 255
    assert grad[11] == 128


def test_apply_outline_1px():
    # 3x3 image with single opaque center pixel
    img = bytearray(3 * 3 * 4)
    # Center pixel (1, 1) is white
    center_idx = (1 * 3 + 1) * 4
    img[center_idx : center_idx + 4] = b"\xff\xff\xff\xff"

    outline_color = (50, 30, 0, 255)
    outlined = apply_outline_1px(bytes(img), 3, 3, outline_color)

    # Center must remain white
    assert outlined[center_idx : center_idx + 4] == b"\xff\xff\xff\xff"

    # All 8 surrounding pixels must now be outline_color
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            idx = ((1 + dy) * 3 + (1 + dx)) * 4
            assert outlined[idx : idx + 4] == bytes(outline_color)


def test_find_luminance_valleys_and_auto_dissect():
    # Construct synthetic 10x4 image with two bright 3x4 letters separated by 2 dark columns
    # and connected by a faint shadow at the bottom
    w, h = 10, 4
    buf = bytearray(w * h * 4)

    # Letter 1: x in [1, 2, 3]
    for y in range(3):
        for x in (1, 2, 3):
            idx = (y * w + x) * 4
            buf[idx : idx + 4] = b"\xff\xff\xff\xff"

    # Letter 2: x in [6, 7, 8]
    for y in range(3):
        for x in (6, 7, 8):
            idx = (y * w + x) * 4
            buf[idx : idx + 4] = b"\xff\xff\xff\xff"

    # Continuous faint drop shadow at y=3 connecting x=1..8
    for x in range(1, 9):
        idx = (3 * w + x) * 4
        buf[idx : idx + 4] = b"\x20\x20\x20\x80"  # dark low-lum shadow with alpha=128

    from PIL import Image
    test_img = Image.frombytes("RGBA", (w, h), bytes(buf))

    # Standard auto_dissect without use_valleys fails because shadow connects them into 1 block
    bank_fail = GlyphBank()
    with pytest.raises(ValueError):
        bank_fail.auto_dissect(test_img, chars="AB", use_valleys=False)

    # With use_valleys=True, it cleanly separates the two letters based on core luminance peaks
    bank_success = GlyphBank()
    bank_success.auto_dissect(test_img, chars="AB", use_valleys=True, core_threshold=140, border_padding=0)
    assert "A" in bank_success.glyphs
    assert "B" in bank_success.glyphs
    assert bank_success.glyphs["A"].width == 3
    assert bank_success.glyphs["B"].width == 3
