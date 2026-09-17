import os
import tempfile

from miorom.graphics.glyph_bank import Glyph, GlyphBank
from miorom.graphics.image_bridge import ImageBridge
from miorom.graphics.palette import Color, Palette
from miorom.graphics.png_codec import PNGCodec, PNGColorType, PNGImage
from miorom.graphics.tiles import Tile
from miorom.platforms.psx.tim import TIMImage
from miorom.platforms.wii.bti import BTIImage
from miorom.platforms.wii.tpl import TPLFile


def test_png_codec_encode_decode_grayscale():
    w, h = 8, 4
    pixels = bytes([x * 8 for x in range(w * h)])
    png_bytes = PNGCodec.encode_grayscale(w, h, pixels)
    assert png_bytes.startswith(PNGCodec.PNG_SIGNATURE)

    decoded = PNGCodec.decode(png_bytes)
    assert decoded.width == w
    assert decoded.height == h
    assert decoded.color_type == PNGColorType.GRAYSCALE
    assert decoded.bit_depth == 8
    assert decoded.pixels == pixels

    rgba = decoded.to_rgba_bytes()
    assert len(rgba) == w * h * 4
    for i in range(w * h):
        v = pixels[i]
        assert rgba[i * 4 : i * 4 + 4] == bytes([v, v, v, 255])


def test_png_codec_encode_decode_rgba():
    w, h = 4, 4
    rgba_src = bytearray()
    for y in range(h):
        for x in range(w):
            rgba_src.extend([x * 60, y * 60, (x + y) * 30, 255 - x * 20])
    rgba_src = bytes(rgba_src)

    png_bytes = PNGCodec.encode_rgba(w, h, rgba_src)
    assert png_bytes.startswith(PNGCodec.PNG_SIGNATURE)

    decoded = PNGCodec.decode(png_bytes)
    assert decoded.width == w
    assert decoded.height == h
    assert decoded.color_type == PNGColorType.RGBA
    assert decoded.bit_depth == 8
    assert decoded.to_rgba_bytes() == rgba_src


def test_png_codec_encode_decode_rgb():
    w, h = 3, 2
    rgb_src = bytes([10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180])
    png_bytes = PNGCodec.encode_rgb(w, h, rgb_src)

    decoded = PNGCodec.decode(png_bytes)
    assert decoded.width == w
    assert decoded.height == h
    assert decoded.color_type == PNGColorType.RGB
    assert decoded.to_rgb_bytes() == rgb_src

    rgba = decoded.to_rgba_bytes()
    for i in range(w * h):
        assert rgba[i * 4 : i * 4 + 3] == rgb_src[i * 3 : i * 3 + 3]
        assert rgba[i * 4 + 3] == 255


def test_png_codec_encode_decode_indexed_with_trns():
    w, h = 4, 2
    indices = bytes([0, 1, 2, 3, 3, 2, 1, 0])
    palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    transparency = [255, 128, 0, 255]

    png_bytes = PNGCodec.encode_indexed(w, h, indices, palette, transparency=transparency)
    decoded = PNGCodec.decode(png_bytes)

    assert decoded.width == w
    assert decoded.height == h
    assert decoded.color_type == PNGColorType.INDEXED
    assert decoded.palette == palette
    assert decoded.transparency == bytes(transparency)

    rgba = decoded.to_rgba_bytes()
    assert rgba[0:4] == bytes([255, 0, 0, 255])
    assert rgba[4:8] == bytes([0, 255, 0, 128])
    assert rgba[8:12] == bytes([0, 0, 255, 0])


def test_image_bridge_zero_dep_roundtrip():
    pal = Palette([
        Color(0, 0, 0, 255),
        Color(255, 0, 0, 255),
        Color(0, 255, 0, 255),
        Color(0, 0, 255, 255),
    ])
    t1 = Tile([1] * 64)
    t2 = Tile([2] * 64)
    tiles = [t1, t2]

    # to_image works regardless of Pillow
    img = ImageBridge.to_image(tiles, pal, width_in_tiles=2)
    assert hasattr(img, "size") or hasattr(img, "width")
    w = img.size[0] if hasattr(img, "size") else img.width
    h = img.size[1] if hasattr(img, "size") else img.height
    assert (w, h) == (16, 8)

    # to_png saves valid PNG
    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = os.path.join(tmpdir, "test_tiles.png")
        ImageBridge.to_png(tiles, pal, width_in_tiles=2, output_path=png_path)
        assert os.path.exists(png_path)
        with open(png_path, "rb") as f:
            data = f.read()
        assert data.startswith(PNGCodec.PNG_SIGNATURE)

        # from_image can read the saved PNG file
        extracted, extracted_pal, _ = ImageBridge.from_image(png_path, bpp=2, target_palette=pal)
        assert len(extracted) == 2
        assert extracted[0].pixels == t1.pixels
        assert extracted[1].pixels == t2.pixels


def test_tim_image_zero_dep_roundtrip():
    # Build 4-bpp TIM
    pal = Palette([Color(i * 16, i * 16, i * 16, 255) for i in range(16)])
    t1 = Tile([1] * 64)
    t2 = Tile([2] * 64)

    # Use PNGImage to construct TIM without Pillow
    png_img = ImageBridge.to_image([t1, t2], pal, width_in_tiles=2)
    tim = TIMImage.from_image(png_img, bpp=4, target_palette=pal)
    assert tim.width == 16
    assert tim.height == 8
    assert tim.bpp == 4

    # to_image
    rendered = tim.to_image()
    assert rendered is not None

    # to_png
    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = os.path.join(tmpdir, "test_tim.png")
        tim.to_png(png_path)
        assert os.path.exists(png_path)
        with open(png_path, "rb") as f:
            data = f.read()
        assert data.startswith(PNGCodec.PNG_SIGNATURE)


def test_tpl_bti_zero_dep():
    # 8x8 RGBA test
    rgba = bytes([255, 128, 0, 255] * 64)
    png_img = PNGImage(width=8, height=8, color_type=PNGColorType.RGBA, bit_depth=8, pixels=rgba)

    # TPL from_image without Pillow
    tpl = TPLFile.from_image(png_img, format_id=5)
    assert len(tpl.images) == 1
    tpl_img = tpl.to_image(0)
    assert tpl_img is not None

    with tempfile.TemporaryDirectory() as tmpdir:
        tpl_png = os.path.join(tmpdir, "test_tpl.png")
        tpl.to_png(tpl_png, image_index=0)
        assert os.path.exists(tpl_png)

        # BTI from_image without Pillow
        bti = BTIImage.from_image(png_img, format_id=5)
        assert bti.width == 8
        assert bti.height == 8
        bti_png = os.path.join(tmpdir, "test_bti.png")
        bti.to_png(bti_png)
        assert os.path.exists(bti_png)


def test_glyph_bank_zero_dep():
    rgba = bytes([200, 50, 50, 255] * 64)
    glyph = Glyph(char="A", width=8, height=8, rgba=rgba, advance_x=8)
    bank = GlyphBank()
    bank.glyphs["A"] = glyph

    # recompose
    rec = bank.recompose("A", target_width=16, target_height=16)
    assert rec is not None

    with tempfile.TemporaryDirectory() as tmpdir:
        png_path = os.path.join(tmpdir, "glyph_a.png")
        glyph.to_png(png_path)
        assert os.path.exists(png_path)
        with open(png_path, "rb") as f:
            assert f.read().startswith(PNGCodec.PNG_SIGNATURE)

        rec_path = os.path.join(tmpdir, "recompose.png")
        bank.recompose_png("A", output_path=rec_path)
        assert os.path.exists(rec_path)
