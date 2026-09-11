from typing import Any, List, Optional, Tuple, Union
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile
from miorom.graphics.tilemap import Tilemap, TileReducer

from miorom.errors import ParseError
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class ImageBridge:
    """
    Bridges between MioROM's Tile/Palette engine and standard image files (PNG, BMP) via Pillow.
    Provides automated color quantization, nearest-palette matching, and tile slicing.
    """

    @classmethod
    def to_image(
        cls,
        tiles: List[Tile],
        palette: Palette,
        width_in_tiles: int,
        transparency_mode: str = "opaque",
    ) -> "Image.Image":
        """
        Renders a list of 8x8 tiles into a PIL RGBA Image.

        Args:
            tiles: List of 8x8 Tile objects.
            palette: Palette containing colors.
            width_in_tiles: Horizontal dimension in tiles.
            transparency_mode: "opaque", "transparent", or "auto" (detects color-key).
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for ImageBridge. Install with 'pip install Pillow'.")

        if not tiles:
            return Image.new("RGBA", (0, 0))

        height_in_tiles = (len(tiles) + width_in_tiles - 1) // width_in_tiles
        width = width_in_tiles * 8
        height = height_in_tiles * 8

        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        pixels = img.load()

        is_trans_zero = False
        if transparency_mode == "transparent":
            is_trans_zero = True
        elif transparency_mode == "auto" and len(palette) > 0:
            c0 = palette[0]
            if (c0.r, c0.g, c0.b) in [(255, 0, 255), (0, 255, 255), (0, 255, 0)]:
                is_trans_zero = True

        for t_idx, tile in enumerate(tiles):
            tile_x = (t_idx % width_in_tiles) * 8
            tile_y = (t_idx // width_in_tiles) * 8

            for y in range(8):
                for x in range(8):
                    pal_idx = tile.get_pixel(x, y)
                    if is_trans_zero and pal_idx == 0:
                        continue
                    if pal_idx < len(palette):
                        col = palette[pal_idx]
                        pixels[tile_x + x, tile_y + y] = (col.r, col.g, col.b, col.a)

        return img

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, "Image.Image"],
        bpp: int = 4,
        target_palette: Optional[Palette] = None,
        deduplicate: bool = False,
    ) -> Tuple[List[Tile], Palette, Optional[Tilemap]]:
        """
        Converts a PIL Image or image file into 8x8 tiles and a palette.
        If target_palette is None, builds an adaptive palette from unique image colors.
        If deduplicate is True, returns unique tiles and the corresponding Tilemap.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for ImageBridge. Install with 'pip install Pillow'.")

        if isinstance(image_or_path, str):
            img = Image.open(image_or_path)
        else:
            img = image_or_path

        img = img.convert("RGBA")
        width, height = img.size

        if width % 8 != 0 or height % 8 != 0:
            raise ParseError(f"Image dimensions ({width}x{height}) must be multiples of 8.")

        # Build or use palette
        max_colors = {1: 2, 2: 4, 4: 16, 8: 256}.get(bpp, 16)

        if target_palette is None:
            # Extract unique colors
            unique_colors: List[Color] = []
            seen = set()
            for y in range(height):
                for x in range(width):
                    r, g, b, a = img.getpixel((x, y))
                    c = Color(r, g, b, a)
                    if c not in seen and len(unique_colors) < max_colors:
                        seen.add(c)
                        unique_colors.append(c)
            # Pad palette to minimum size
            while len(unique_colors) < max_colors:
                unique_colors.append(Color(0, 0, 0, 255))
            palette = Palette(unique_colors)
        else:
            palette = target_palette

        # Extract 8x8 tiles
        raw_tiles: List[Tile] = []
        tiles_x = width // 8
        tiles_y = height // 8

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                tile = Tile()
                for y in range(8):
                    for x in range(8):
                        px_col = Color(*img.getpixel((tx * 8 + x, ty * 8 + y)))
                        pal_idx = palette.match_color(px_col)
                        tile.set_pixel(x, y, pal_idx)
                raw_tiles.append(tile)

        if deduplicate:
            unique_tiles, entries = TileReducer.reduce(raw_tiles, allow_flip=True)
            tilemap = Tilemap(width=tiles_x, height=tiles_y, entries=entries)
            return unique_tiles, palette, tilemap

        return raw_tiles, palette, None

    @classmethod
    def to_tim(
        cls,
        image_or_path: Union[str, "Image.Image"],
        bpp: int = 4,
        target_palette: Optional[Palette] = None,
        img_dx: int = 0,
        img_dy: int = 0,
        clut_dx: int = 0,
        clut_dy: int = 0,
    ):
        """
        Converts a PIL Image or image file path into a PlayStation 1 TIMImage.
        """
        from miorom.platforms.psx.tim import TIMImage

        return TIMImage.from_image(
            image_or_path=image_or_path,
            bpp=bpp,
            target_palette=target_palette,
            img_dx=img_dx,
            img_dy=img_dy,
            clut_dx=clut_dx,
            clut_dy=clut_dy,
        )

    @classmethod
    def from_tim(
        cls,
        tim_or_bytes: Union[bytes, Any],
        palette_index: int = 0,
    ) -> "Image.Image":
        """
        Renders a TIMImage or TIM binary bytes into a PIL RGBA Image.
        """
        from miorom.platforms.psx.tim import TIMImage

        if isinstance(tim_or_bytes, (bytes, bytearray)):
            tim = TIMImage(bytes(tim_or_bytes))
        else:
            tim = tim_or_bytes
        return tim.to_image(palette_index=palette_index)
