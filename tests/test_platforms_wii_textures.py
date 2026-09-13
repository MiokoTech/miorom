import pytest
from PIL import Image

from miorom.platforms.wii.tpl import TPLFile, TPLImage
from miorom.platforms.wii.bti import BTIImage, BTIHeaderStruct
from miorom.compression.yaz0 import Yaz0


def create_test_image(width: int = 16, height: int = 16) -> Image.Image:
    """Creates a predictable test image with colored quadrants and transparency."""
    img = Image.new("RGBA", (width, height))
    pixels = img.load()
    for y in range(height):
        for x in range(width):
            if x < width // 2 and y < height // 2:
                pixels[x, y] = (255, 0, 0, 255)      # Red quadrant
            elif x >= width // 2 and y < height // 2:
                pixels[x, y] = (0, 255, 0, 255)      # Green quadrant
            elif x < width // 2 and y >= height // 2:
                pixels[x, y] = (0, 0, 255, 255)      # Blue quadrant
            else:
                pixels[x, y] = (255, 255, 0, 128)    # Yellow translucent quadrant
    return img


def test_tpl_rgb5a3_roundtrip():
    orig_img = create_test_image(16, 16)
    tpl = TPLFile.from_image(orig_img, format_id=5)  # RGB5A3
    assert len(tpl.images) == 1
    assert tpl.images[0].width == 16
    assert tpl.images[0].height == 16
    assert tpl.images[0].format_id == 5

    tpl_bytes = tpl.to_bytes()
    assert len(tpl_bytes) > 0

    # Load back
    loaded_tpl = TPLFile.from_bytes(tpl_bytes)
    assert len(loaded_tpl.images) == 1
    img0 = loaded_tpl.images[0]
    assert img0.width == 16
    assert img0.height == 16
    assert img0.format_id == 5

    # Decode
    out_img = loaded_tpl.to_image(0)
    assert out_img.size == (16, 16)

    # Check color accuracy (allowing 5-bit/4-bit quantization variance)
    red_pix = out_img.getpixel((2, 2))
    assert red_pix[0] > 240
    assert red_pix[1] < 15
    assert red_pix[2] < 15


def test_tpl_cmpr_dxt1_roundtrip():
    orig_img = create_test_image(16, 16)
    tpl = TPLFile.from_image(orig_img, format_id=14)  # CMPR
    assert tpl.images[0].format_id == 14

    tpl_bytes = tpl.to_bytes()
    loaded_tpl = TPLFile.from_bytes(tpl_bytes)
    out_img = loaded_tpl.to_image(0)

    assert out_img.size == (16, 16)
    red_pix = out_img.getpixel((2, 2))
    assert red_pix[0] > 200


def test_tpl_multi_image():
    img1 = create_test_image(8, 8)
    img2 = create_test_image(16, 8)

    tpl1 = TPLFile.from_image(img1, format_id=4)  # RGB565
    tpl2 = TPLFile.from_image(img2, format_id=6)  # RGBA8

    multi_tpl = TPLFile(images=[tpl1.images[0], tpl2.images[0]])
    data = multi_tpl.to_bytes()

    loaded = TPLFile.from_bytes(data)
    assert len(loaded.images) == 2
    assert loaded.images[0].width == 8 and loaded.images[0].height == 8
    assert loaded.images[0].format_id == 4
    assert loaded.images[1].width == 16 and loaded.images[1].height == 8
    assert loaded.images[1].format_id == 6

    dec1 = loaded.to_image(0)
    dec2 = loaded.to_image(1)
    assert dec1.size == (8, 8)
    assert dec2.size == (16, 8)


def test_bti_basic_roundtrip():
    orig_img = create_test_image(16, 16)
    bti = BTIImage.from_image(orig_img, format_id=5)  # RGB5A3
    assert bti.width == 16
    assert bti.height == 16
    assert bti.format_id == 5
    assert bti.format_name == "RGB5A3"

    raw_bytes = bti.to_bytes(compress_yaz0=False)
    assert len(raw_bytes) >= BTIHeaderStruct.sizeof()

    loaded = BTIImage.from_bytes(raw_bytes)
    assert loaded.width == 16
    assert loaded.height == 16
    assert loaded.format_id == 5

    out_img = loaded.to_image()
    assert out_img.size == (16, 16)
    red_pix = out_img.getpixel((2, 2))
    assert red_pix[0] > 240


def test_bti_yaz0_compression():
    orig_img = create_test_image(16, 16)
    bti = BTIImage.from_image(orig_img, format_id=4)  # RGB565

    # Serialize with Yaz0 compression
    compressed_data = bti.to_bytes(compress_yaz0=True)
    assert compressed_data.startswith(b"Yaz0")

    # Load back with transparent Yaz0 decompression
    loaded = BTIImage.from_bytes(compressed_data)
    assert loaded.width == 16
    assert loaded.height == 16
    assert loaded.format_id == 4

    out_img = loaded.to_image()
    assert out_img.size == (16, 16)


def test_tpl_palette_roundtrip_rgb5a3():
    from miorom.platforms.wii.tpl import decode_gx_palette, encode_gx_palette
    orig_palette = [
        (0, 0, 0, 0),         # Fully transparent
        (255, 0, 0, 255),     # Solid red (RGB555)
        (0, 255, 0, 255),     # Solid green (RGB555)
        (0, 0, 255, 255),     # Solid blue (RGB555)
        (255, 255, 255, 128), # Translucent white (ARGB3444)
    ]
    raw = encode_gx_palette(orig_palette, format_id=2)
    assert len(raw) == len(orig_palette) * 2
    decoded = decode_gx_palette(raw, len(orig_palette), format_id=2)
    assert len(decoded) == len(orig_palette)
    assert decoded[0][3] == 0
    assert decoded[1][0] > 240 and decoded[1][1] < 15 and decoded[1][3] == 255
    assert 100 < decoded[4][3] < 160


def test_tpl_palette_roundtrip_rgb565():
    from miorom.platforms.wii.tpl import decode_gx_palette, encode_gx_palette
    orig_palette = [
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
    ]
    raw = encode_gx_palette(orig_palette, format_id=1)
    decoded = decode_gx_palette(raw, len(orig_palette), format_id=1)
    assert decoded[0][0] > 240
    assert decoded[1][1] > 240
    assert decoded[2][2] > 240


def test_tpl_palette_roundtrip_ia8():
    from miorom.platforms.wii.tpl import decode_gx_palette, encode_gx_palette
    orig_palette = [
        (200, 200, 200, 255),
        (50, 50, 50, 128),
    ]
    raw = encode_gx_palette(orig_palette, format_id=0)
    decoded = decode_gx_palette(raw, len(orig_palette), format_id=0)
    assert decoded[0][3] == 255
    assert decoded[1][3] == 128


def test_tpl_ci4_roundtrip():
    img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    colors = [
        (0, 0, 0, 0),
        (255, 0, 0, 255),
        (0, 255, 0, 255),
        (0, 0, 255, 255),
        (255, 255, 0, 255),
        (255, 0, 255, 255),
        (0, 255, 255, 255),
        (128, 128, 128, 255),
    ]
    for y in range(16):
        for x in range(16):
            c_idx = (x // 4 + (y // 4) * 4) % len(colors)
            img.putpixel((x, y), colors[c_idx])

    tpl = TPLFile.from_image(img, format_id=8, palette_format_id=2)
    assert len(tpl.images) == 1
    t_img = tpl.images[0]
    assert t_img.format_id == 8
    assert t_img.is_paletted
    assert t_img.color_count == 16
    assert "CI4" in t_img.summary()

    # Serialize
    tpl_bytes = tpl.to_bytes()
    assert len(tpl_bytes) > 0

    # Deserialize
    loaded = TPLFile.from_bytes(tpl_bytes)
    assert len(loaded.images) == 1
    loaded_img = loaded.images[0]
    assert loaded_img.format_id == 8
    assert loaded_img.is_paletted
    assert loaded_img.color_count == 16

    # Decode and verify dimensions and colors
    dec_img = loaded.to_image(0)
    assert dec_img.size == (16, 16)
    red_pix = dec_img.getpixel((4, 0))
    assert red_pix[0] > 240 and red_pix[1] < 15

    # Check terminal ascii rendering
    ascii_art = loaded_img.to_terminal_ascii(max_width=16)
    assert len(ascii_art) > 0
    assert isinstance(ascii_art, str)


def test_tpl_ci8_roundtrip():
    img = Image.new("RGBA", (32, 16))
    for y in range(16):
        for x in range(32):
            img.putpixel((x, y), (x * 8, y * 16, 100, 255))

    tpl = TPLFile.from_image(img, format_id=9, palette_format_id=2)
    assert tpl.images[0].format_id == 9
    assert tpl.images[0].is_paletted
    assert tpl.images[0].color_count == 256

    tpl_bytes = tpl.to_bytes()
    loaded = TPLFile.from_bytes(tpl_bytes)
    assert loaded.images[0].format_id == 9
    assert loaded.images[0].color_count == 256

    dec_img = loaded.to_image(0)
    assert dec_img.size == (32, 16)


def test_retail_gfontc29_tpl():
    import os
    path = "/sdcard/MiokoTech/Rune Factory - Frontier/workspace/graphics/menu_arc/win_recipe/win_recipe/timg/gfontC29.tpl"
    if not os.path.exists(path):
        pytest.skip("Retail sample gfontC29.tpl not found on test system.")

    tpl = TPLFile.from_file(path)
    assert len(tpl.images) == 1
    img = tpl.images[0]
    assert img.width == 80
    assert img.height == 20
    assert img.format_id == 8  # CI4
    assert img.is_paletted
    assert img.palette_format_id == 2  # RGB5A3
    assert img.color_count == 16
    assert len(img.raw_data) == 960

    # Test decoding
    pil_img = tpl.to_image(0)
    assert pil_img.size == (80, 20)

    # Test roundtrip serialization
    data = tpl.to_bytes()
    reloaded = TPLFile.from_bytes(data)
    assert reloaded.images[0].width == 80
    assert reloaded.images[0].height == 20
    assert reloaded.images[0].format_id == 8
    assert reloaded.images[0].color_count == 16

    reloaded_img = reloaded.to_image(0)
    assert reloaded_img.tobytes() == pil_img.tobytes()

