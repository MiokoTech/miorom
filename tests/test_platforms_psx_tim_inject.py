import pytest
from PIL import Image
from miorom.platforms.psx.tim import TIMImage
from miorom.graphics.image_bridge import ImageBridge
from miorom.graphics.palette import Color, Palette


def test_tim_from_image_4bpp_roundtrip():
    # 8x8 image with 3 distinct colors
    img = Image.new("RGBA", (8, 8), (0, 0, 0, 255))
    pixels = img.load()
    pixels[0, 0] = (255, 0, 0, 255)
    pixels[1, 0] = (0, 255, 0, 255)
    pixels[2, 0] = (0, 0, 255, 255)

    tim = TIMImage.from_image(img, bpp=4)
    assert tim.bpp == 4
    assert tim.has_clut is True
    assert len(tim.clut_palettes) == 1
    assert tim.width == 8
    assert tim.height == 8

    raw = tim.to_bytes()
    assert len(raw) > 0
    assert raw[:4] == b"\x10\x00\x00\x00"

    reloaded = TIMImage(raw)
    assert reloaded.bpp == 4
    assert reloaded.width == 8
    assert reloaded.height == 8
    assert len(reloaded.clut_palettes) == 1

    out_img = reloaded.to_image()
    assert out_img.size == (8, 8)
    # Check that colors are preserved within 5-bit color precision
    out_pixels = out_img.load()
    r, g, b, _ = out_pixels[0, 0]
    assert r > 240 and g < 20 and b < 20
    r, g, b, _ = out_pixels[1, 0]
    assert r < 20 and g > 240 and b < 20
    r, g, b, _ = out_pixels[2, 0]
    assert r < 20 and g < 20 and b > 240


def test_tim_from_image_8bpp_roundtrip():
    img = Image.new("RGBA", (16, 8), (50, 50, 50, 255))
    pixels = img.load()
    pixels[5, 5] = (200, 100, 50, 255)

    tim = TIMImage.from_image(img, bpp=8)
    assert tim.bpp == 8
    assert tim.has_clut is True

    raw = tim.to_bytes()
    reloaded = TIMImage.from_bytes(raw)
    assert reloaded.bpp == 8
    assert reloaded.width == 16
    assert reloaded.height == 8

    out_img = reloaded.to_image()
    assert out_img.size == (16, 8)


def test_tim_from_image_16bpp_roundtrip():
    img = Image.new("RGBA", (8, 4), (0, 0, 0, 0))  # Transparent background
    pixels = img.load()
    pixels[0, 0] = (255, 255, 255, 255)
    pixels[1, 0] = (120, 80, 200, 255)

    tim = TIMImage.from_image(img, bpp=16)
    assert tim.bpp == 16
    assert tim.has_clut is False

    raw = tim.to_bytes()
    reloaded = TIMImage(raw)
    assert reloaded.bpp == 16
    assert reloaded.has_clut is False

    out_img = reloaded.to_image()
    out_px = out_img.load()
    # Transparent pixel
    assert out_px[2, 2][3] == 0
    # White pixel
    assert out_px[0, 0][:3] == (255, 255, 255)


def test_image_bridge_tim_integration():
    img = Image.new("RGBA", (16, 16), (128, 64, 32, 255))
    tim = ImageBridge.to_tim(img, bpp=4)
    assert isinstance(tim, TIMImage)
    assert tim.bpp == 4

    out_img = ImageBridge.from_tim(tim)
    assert out_img.size == (16, 16)

    raw = tim.to_bytes()
    out_img2 = ImageBridge.from_tim(raw)
    assert out_img2.size == (16, 16)
