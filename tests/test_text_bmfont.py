import pytest
from miorom.text.bmfont import BMFont, BMFontChar, PNGCodec
from miorom.text.font_builder import BitmapFont


def test_pure_python_png_codec():
    # Test grayscale PNG encoding and decoding
    width = 4
    height = 4
    pixels = bytes([
        0, 50, 100, 150,
        200, 255, 128, 64,
        32, 16, 8, 4,
        2, 1, 0, 255,
    ])
    png_bytes = PNGCodec.encode_grayscale(width, height, pixels)
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    dec_w, dec_h, dec_pixels, color_type = PNGCodec.decode(png_bytes)
    assert dec_w == width
    assert dec_h == height
    assert dec_pixels == pixels
    assert color_type == 0


def test_pure_python_png_rgba():
    width = 2
    height = 2
    rgba_pixels = bytes([
        255, 0, 0, 255,    # Red
        0, 255, 0, 255,    # Green
        0, 0, 255, 255,    # Blue
        255, 255, 255, 128 # Translucent white
    ])
    png_bytes = PNGCodec.encode_rgba(width, height, rgba_pixels)
    dec_w, dec_h, dec_pixels, color_type = PNGCodec.decode(png_bytes)
    assert dec_w == width
    assert dec_h == height
    assert dec_pixels == rgba_pixels
    assert color_type == 6


def test_bmfont_text_roundtrip():
    sample_text = (
        'info face="TestFont" size=16 bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=1 aa=1 padding=1,1,1,1 spacing=1,1 outline=0\n'
        'common lineHeight=16 base=12 scaleW=128 scaleH=128 pages=1 packed=0 alphaChnl=0 redChnl=0 greenChnl=0 blueChnl=0\n'
        'page id=0 file="test_0.png"\n'
        'chars count=2\n'
        'char id=65   x=0     y=0     width=8    height=12   xoffset=0    yoffset=2    xadvance=8    page=0  chnl=15 letter="A"\n'
        'char id=66   x=10    y=0     width=8    height=12   xoffset=0    yoffset=2    xadvance=8    page=0  chnl=15 letter="B"\n'
        'kernings count=1\n'
        'kerning first=65   second=86   amount=-1\n'
    )

    bm = BMFont.from_text(sample_text)
    assert bm.info.face == "TestFont"
    assert bm.info.size == 16
    assert bm.common.line_height == 16
    assert len(bm.chars) == 2
    assert 65 in bm.chars
    assert bm.chars[65].letter == "A"
    assert len(bm.kernings) == 1
    assert bm.kernings[0].amount == -1

    out_text = bm.to_text()
    assert 'face="TestFont"' in out_text
    assert 'char id=65' in out_text


def test_bmfont_xml_roundtrip():
    sample_xml = (
        '<font>'
        '<info face="SysFont" size="14" bold="0" italic="0" charset="" unicode="1" stretchH="100" smooth="1" aa="1" padding="0,0,0,0" spacing="0,0" outline="0"/>'
        '<common lineHeight="14" base="11" scaleW="256" scaleH="256" pages="1" packed="0"/>'
        '<pages><page id="0" file="font.png"/></pages>'
        '<chars count="1"><char id="88" x="4" y="4" width="8" height="10" xoffset="0" yoffset="1" xadvance="8" page="0" chnl="15" letter="X"/></chars>'
        '</font>'
    )

    bm = BMFont.from_xml(sample_xml)
    assert bm.info.face == "SysFont"
    assert bm.common.line_height == 14
    assert 88 in bm.chars
    assert bm.chars[88].width == 8

    out_xml = bm.to_xml()
    assert 'face="SysFont"' in out_xml
    assert 'id="88"' in out_xml


def test_bmfont_bitmap_font_atlas_roundtrip():
    # Create BitmapFont
    bf = BitmapFont(default_height=8, default_advance=6)
    # Add glyph 'A' (4x6)
    bf.add_glyph_from_ascii_art(
        "A",
        """
        .##.
        #..#
        ####
        #..#
        #..#
        """,
        advance=5,
    )
    # Add glyph 'B' (4x6)
    bf.add_glyph_from_ascii_art(
        "B",
        """
        ###.
        #..#
        ###.
        #..#
        ###.
        """,
        advance=5,
    )

    bm, raw_atlas, png_bytes = BMFont.from_bitmap_font(
        bf,
        page_file="test_font.png",
        texture_width=64,
        texture_height=64,
        padding=1,
    )

    assert len(bm.chars) == 2
    assert ord("A") in bm.chars
    assert ord("B") in bm.chars
    assert len(png_bytes) > 0
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # Decode png_bytes back using pure Python PNGCodec
    w, h, decoded_raw, ctype = PNGCodec.decode(png_bytes)
    assert w == 64 and h == 64
    assert decoded_raw == raw_atlas

    # Reconstruct BitmapFont from BMFont + decoded atlas
    reconstructed_bf = bm.to_bitmap_font(decoded_raw, atlas_width=64)
    g_a = reconstructed_bf.get_glyph("A")
    assert g_a is not None
    assert g_a.advance == 5
    # Pixel verification: top left of 'A' art was '.', so pixel should be 0
    assert g_a.get_pixel(0, 0) == 0
    # Top center was '#', so pixel should be 255
    assert g_a.get_pixel(1, 0) == 255
