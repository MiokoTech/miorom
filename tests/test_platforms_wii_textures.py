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
