import struct
from miorom.graphics import MdecDecoder


def test_mdec_decoder_basic():
    decoder = MdecDecoder()

    # Construct a minimal bitstream for one 16x16 macroblock:
    # 6 blocks: Cr, Cb, Y1, Y2, Y3, Y4
    # Each block has DC coefficient followed by 0xFE00 (EOB)
    words = []
    # Cr: DC=0, EOB
    words.extend([0, 0xFE00])
    # Cb: DC=0, EOB
    words.extend([0, 0xFE00])
    # Y1..Y4: DC=100 (which scales with quant), EOB
    for _ in range(4):
        words.extend([100, 0xFE00])

    bs_data = struct.pack(f"<{len(words)}H", *words)

    # Decode 16x16 image
    rgb = decoder.decode_stream(bs_data, width=16, height=16)
    assert len(rgb) == 16 * 16 * 3

    # Verify pixels are valid RGB bytes [0, 255]
    for b in rgb:
        assert 0 <= b <= 255

    # Test Pillow image output
    img = decoder.to_image(bs_data, width=16, height=16)
    if hasattr(img, "size"):
        assert img.size == (16, 16)
