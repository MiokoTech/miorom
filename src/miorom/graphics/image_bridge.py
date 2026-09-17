from typing import Any, List, Optional, Tuple, Union

from miorom.errors import ParseError
from miorom.graphics.palette import Color, Palette
from miorom.graphics.png_codec import PNGCodec  # noqa: F401
from miorom.graphics.tilemap import Tilemap, TileReducer
from miorom.graphics.tiles import Tile

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
    ):
        """
        Renders a list of 8x8 tiles into an RGBA image.

        Returns a ``PIL.Image.Image`` when Pillow is installed, or a
        :class:`~miorom.graphics.png_codec.PNGImage` (zero-dependency fallback) otherwise.

        Args:
            tiles: List of 8x8 Tile objects.
            palette: Palette containing colors.
            width_in_tiles: Horizontal dimension in tiles.
            transparency_mode: "opaque", "transparent", or "auto" (detects color-key).
        """
        from miorom.graphics.png_codec import PNGColorType, PNGImage

        if not tiles:
            if HAS_PIL:
                return Image.new("RGBA", (0, 0))
            return PNGImage(width=0, height=0, color_type=PNGColorType.RGBA, bit_depth=8, pixels=b"")

        height_in_tiles = (len(tiles) + width_in_tiles - 1) // width_in_tiles
        width = width_in_tiles * 8
        height = height_in_tiles * 8

        raw_rgba = bytearray(width * height * 4)

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
                        offset = ((tile_y + y) * width + (tile_x + x)) * 4
                        raw_rgba[offset] = col.r
                        raw_rgba[offset + 1] = col.g
                        raw_rgba[offset + 2] = col.b
                        raw_rgba[offset + 3] = col.a

        if HAS_PIL:
            return Image.frombytes("RGBA", (width, height), bytes(raw_rgba))
        return PNGImage(
            width=width,
            height=height,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=bytes(raw_rgba),
        )

    @classmethod
    def to_png(
        cls,
        tiles: List[Tile],
        palette: Palette,
        width_in_tiles: int,
        output_path: str,
        transparency_mode: str = "opaque",
    ) -> str:
        """
        Renders tiles and saves as a PNG file. Fully zero-dependency (works without Pillow).
        """
        img = cls.to_image(tiles, palette, width_in_tiles, transparency_mode=transparency_mode)
        if hasattr(img, "save"):
            img.save(output_path, format="PNG")
        else:
            png_bytes = PNGCodec.encode_rgba(img.width, img.height, img.to_rgba_bytes())
            with open(output_path, "wb") as f:
                f.write(png_bytes)
        return output_path

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, Any],
        bpp: int = 4,
        target_palette: Optional[Palette] = None,
        deduplicate: bool = False,
    ) -> Tuple[List[Tile], Palette, Optional[Tilemap]]:
        """
        Converts an image (PIL Image, PNGImage, or file path) into 8x8 tiles and a palette.
        If target_palette is None, builds an adaptive palette from unique image colors.
        If deduplicate is True, returns unique tiles and the corresponding Tilemap.
        """
        if isinstance(image_or_path, str):
            if HAS_PIL:
                img = Image.open(image_or_path).convert("RGBA")
            else:
                from miorom.graphics.png_codec import PNGCodec as _PC
                raw = open(image_or_path, "rb").read()
                _w, _h, rgba = _PC.png_to_rgba(raw)
                class _FakeImg:
                    size = (_w, _h)
                    def convert(self, mode): return self
                    def getpixel(self, xy): return tuple(rgba[(xy[1]*_w+xy[0])*4:(xy[1]*_w+xy[0])*4+4])
                img = _FakeImg()
        elif HAS_PIL and isinstance(image_or_path, Image.Image):
            img = image_or_path.convert("RGBA")
        else:
            from miorom.graphics.png_codec import PNGImage
            if isinstance(image_or_path, PNGImage):
                _w, _h = image_or_path.width, image_or_path.height
                rgba = image_or_path.to_rgba_bytes()
                class _FakeImg2:
                    size = (_w, _h)
                    def convert(self, mode): return self
                    def getpixel(self, xy): return tuple(rgba[(xy[1]*_w+xy[0])*4:(xy[1]*_w+xy[0])*4+4])
                img = _FakeImg2()
            elif hasattr(image_or_path, "convert"):
                img = image_or_path.convert("RGBA")
            else:
                raise TypeError(f"Expected file path, PIL Image, or PNGImage, got {type(image_or_path)}")

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
                        if px_col.a < 128:
                            pal_idx = 0
                        else:
                            start_idx = 1 if len(palette) > 1 and (palette[0].r, palette[0].g, palette[0].b) in [(255, 0, 255), (0, 255, 255), (0, 255, 0)] else 0
                            pal_idx = palette.match_color(px_col, start_index=start_idx)
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
