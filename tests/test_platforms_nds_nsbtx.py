import pytest
from PIL import Image

from miorom.platforms.nds.nsbtx import (
    NSBTXFile,
    NSBTXTexture,
    NSBTXPalette,
    BTX0HeaderStruct,
    encode_bgr555_color,
)
from miorom.errors import ParseError


def test_nsbtx_direct_color_roundtrip():
    # 16x16 Direct Color texture (Format 7, 2 bytes/pixel, total 512 bytes)
    width, height = 16, 16
    raw_tex = bytearray()
    for y in range(height):
        for x in range(width):
            if x < 8:
                # Opaque Red (bit 15 = 1, r = 31)
                raw_tex.extend([0x1F, 0x80])
            else:
                # Opaque Blue (bit 15 = 1, b = 31)
                raw_tex.extend([0x00, 0xFC])

    tex = NSBTXTexture(
        name="tex_flag",
        width=width,
        height=height,
        format_id=7,  # Direct Color
        color0_transparent=False,
        raw_data=bytes(raw_tex),
    )

    nsbtx = NSBTXFile(textures=[tex], palettes=[])
    data = nsbtx.to_bytes()
    assert data.startswith(b"BTX0")

    # Load back
    loaded = NSBTXFile.from_bytes(data)
    assert len(loaded.textures) == 1
    t0 = loaded.textures[0]
    assert t0.name == "tex_flag"
    assert t0.width == 16
    assert t0.height == 16
    assert t0.format_id == 7

    # Render image
    img = loaded.to_image("tex_flag")
    assert img.size == (16, 16)
    red_pixel = img.getpixel((2, 2))
    assert red_pixel[0] == 255
    assert red_pixel[2] == 0
    assert red_pixel[3] == 255

    blue_pixel = img.getpixel((10, 2))
    assert blue_pixel[0] == 0
    assert blue_pixel[2] == 255
    assert blue_pixel[3] == 255


def test_nsbtx_paletted_roundtrip():
    # 8x8 Texture with 16-color palette (Format 3, 4bpp, 32 bytes)
    width, height = 8, 8
    raw_tex = bytearray([0x01] * 32)  # pixels alternate color 1 and color 0

    tex = NSBTXTexture(
        name="tex_icon",
        width=width,
        height=height,
        format_id=3,  # 16-color
        color0_transparent=True,
        raw_data=bytes(raw_tex),
    )

    pal_colors = [(0, 0, 0), (255, 255, 0)] + [(0, 0, 0)] * 14
    pal = NSBTXPalette(name="pal_icon", colors=pal_colors)

    nsbtx = NSBTXFile(textures=[tex], palettes=[pal])
    data = nsbtx.to_bytes()

    loaded = NSBTXFile.from_bytes(data)
    assert loaded.get_texture_names() == ["tex_icon"]
    assert loaded.get_palette_names() == ["pal_icon"]

    rgba = loaded.decode_rgba("tex_icon", "pal_icon")
    assert len(rgba) == 8 * 8 * 4

    img = loaded.to_image("tex_icon", "pal_icon")
    # Color 1 is yellow (255, 255, 0)
    p1 = img.getpixel((0, 0))
    assert p1[0] == 255
    assert p1[1] == 255
    assert p1[2] == 0


def test_nsbtx_multi_texture():
    t1 = NSBTXTexture("t1", 8, 8, 7, False, bytes(8 * 8 * 2))
    t2 = NSBTXTexture("t2", 16, 16, 7, False, bytes(16 * 16 * 2))

    nsbtx = NSBTXFile(textures=[t1, t2])
    data = nsbtx.to_bytes()

    loaded = NSBTXFile.from_bytes(data)
    assert loaded.get_texture_names() == ["t1", "t2"]
    assert loaded.textures[0].width == 8
    assert loaded.textures[1].width == 16


def test_nsbtx_error_handling():
    with pytest.raises(ParseError):
        NSBTXFile.from_bytes(b"")

    with pytest.raises(ParseError):
        # Invalid magic
        NSBTXFile.from_bytes(b"INVALID_HEADER_DATA_STREAM")
