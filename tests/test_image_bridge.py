import pytest
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile
from miorom.graphics.image_bridge import ImageBridge, HAS_PIL


@pytest.mark.skipif(not HAS_PIL, reason="Pillow not installed")
def test_image_bridge_to_and_from_image():
    from PIL import Image

    # 1. Create a 16x8 image (2 tiles wide, 1 tile high)
    pal = Palette([
        Color(0, 0, 0, 255),       # 0
        Color(255, 0, 0, 255),     # 1: Red
        Color(0, 255, 0, 255),     # 2: Green
        Color(0, 0, 255, 255),     # 3: Blue
    ])

    t1 = Tile([1] * 64) # All Red
    t2 = Tile([2] * 64) # All Green

    tiles = [t1, t2]
    img = ImageBridge.to_image(tiles, pal, width_in_tiles=2)

    assert img.size == (16, 8)
    assert img.getpixel((0, 0)) == (255, 0, 0, 255)
    assert img.getpixel((8, 0)) == (0, 255, 0, 255)

    # 2. Convert back from image
    extracted_tiles, extracted_pal, _ = ImageBridge.from_image(img, bpp=2, target_palette=pal)
    assert len(extracted_tiles) == 2
    assert extracted_tiles[0] == t1
    assert extracted_tiles[1] == t2
