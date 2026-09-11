import pytest
from miorom.graphics.palette import Color, Palette
from miorom.errors import ParseError


def test_genesis_vdp_color_conversion():
    # Genesis 9-bit RGB333: (B << 9) | (G << 5) | (R << 1)
    pure_red = Color(255, 0, 0)
    md_red = pure_red.to_md_color()
    assert md_red == (7 << 1)  # 0x000E
    decoded_red = Color.from_md_color(md_red)
    assert decoded_red.r == 255
    assert decoded_red.g == 0
    assert decoded_red.b == 0

    pure_white = Color(255, 255, 255)
    md_white = pure_white.to_md_color()
    assert md_white == (7 << 9) | (7 << 5) | (7 << 1)  # 0x0EEE
    decoded_white = Color.from_md_color(md_white)
    assert decoded_white.r == 255 and decoded_white.g == 255 and decoded_white.b == 255


def test_genesis_cram_binary_roundtrip():
    pal = Palette([
        Color(0, 0, 0),
        Color(255, 0, 0),
        Color(0, 255, 0),
        Color(0, 0, 255),
    ])

    cram_bytes = pal.to_md_bytes(endian=">")
    assert len(cram_bytes) == 8

    pal_decoded = Palette.from_md_bytes(cram_bytes, endian=">")
    assert len(pal_decoded) == 4
    assert pal_decoded[0].r == 0
    assert pal_decoded[1].r == 255
    assert pal_decoded[2].g == 255
    assert pal_decoded[3].b == 255


def test_adobe_color_table_act_roundtrip():
    colors = [Color(i, i * 2, 255 - i) for i in range(16)]
    pal = Palette(colors)

    act_bytes = pal.to_act()
    assert len(act_bytes) == 772

    pal_from_act = Palette.from_act(act_bytes)
    assert len(pal_from_act) == 16
    assert pal_from_act[0] == colors[0]
    assert pal_from_act[15] == colors[15]


def test_jasc_pal_text_roundtrip():
    colors = [
        Color(10, 20, 30),
        Color(100, 150, 200),
        Color(255, 255, 255),
    ]
    pal = Palette(colors)

    jasc_text = pal.to_jasc_pal()
    assert jasc_text.startswith("JASC-PAL\n0100\n3\n")

    pal_from_jasc = Palette.from_jasc_pal(jasc_text)
    assert len(pal_from_jasc) == 3
    assert pal_from_jasc[0] == colors[0]
    assert pal_from_jasc[1] == colors[1]
    assert pal_from_jasc[2] == colors[2]


def test_jasc_pal_invalid_format():
    with pytest.raises(ParseError):
        Palette.from_jasc_pal("INVALID_HEADER\n")
