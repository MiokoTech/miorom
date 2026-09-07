import struct
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from miorom.graphics.tiles import Tile, encode_tile
from miorom.platforms.nds.nftr import NFTRFont, NFTRGlyph
from miorom.text.font_builder import BitmapFont, Glyph


class TTFCompiler:
    """
    TrueType / OpenType Vector Font Compiler for Retro Consoles.
    Renders vector fonts (.ttf / .otf) into console bitmap tiles (1bpp, 2bpp, 4bpp),
    computes proportional Variable-Width Font (VWF) advance metrics,
    and exports directly into Nintendo DS NFTR, BitmapFont, or raw tile streams.
    """

    def __init__(self, font_path: Optional[str] = None, font_size: int = 12):
        self.font_size = font_size
        self.font_path = font_path

        if font_path:
            self.font = ImageFont.truetype(font_path, size=font_size)
        else:
            try:
                self.font = ImageFont.load_default(size=font_size)
            except TypeError:
                self.font = ImageFont.load_default()

    def render_glyph_bitmap(
        self,
        char: str,
        width: int = 8,
        height: int = 12,
    ) -> Tuple[List[int], int]:
        """
        Rasterize a single character into a row-major list of grayscale pixels (0..255)
        and compute its proportional advance width.
        """
        img = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(img)
        draw.text((0, 0), char, font=self.font, fill=255)

        try:
            bbox = self.font.getbbox(char)
            advance = max(1, min(width, bbox[2])) if bbox else max(1, width // 2)
        except Exception:
            advance = max(1, width // 2)

        return list(img.getdata()), advance

    def render_glyph(
        self,
        char: str,
        bpp: int = 2,
    ) -> Tuple[Tile, int]:
        """
        Rasterize a single character into an 8x8 console Tile and compute its advance width.
        """
        raw_pixels, advance = self.render_glyph_bitmap(char, width=8, height=8)

        # Quantize grayscale (0..255) to bpp pixel values
        pixels = []
        max_val = (1 << bpp) - 1

        for p in raw_pixels:
            if bpp == 1:
                val = 1 if p >= 128 else 0
            else:
                val = (p * max_val + 127) // 255
            pixels.append(val)

        tile = Tile(pixels=pixels)
        return tile, advance

    def compile_glyphs(
        self,
        chars: str,
        bpp: int = 2,
    ) -> Dict[int, Tuple[Tile, int]]:
        """
        Compile all specified characters into a dictionary of {codepoint: (Tile, advance_width)}.
        """
        result = {}
        for ch in chars:
            code = ord(ch)
            if code not in result:
                tile, adv = self.render_glyph(ch, bpp=bpp)
                result[code] = (tile, adv)
        return result

    def to_nftr(
        self,
        chars: str,
        bpp: int = 2,
    ) -> NFTRFont:
        """
        Compile vector glyphs directly into a Nintendo DS NFTRFont object.
        Call .to_bytes() on the returned font to produce a valid .nftr binary!
        """
        # NDS NFTR standard tile is 8x8
        nftr = NFTRFont(height=8, cell_width=8, bpp=bpp)
        compiled = self.compile_glyphs(chars, bpp=bpp)

        for code, (tile, advance) in compiled.items():
            nftr.glyphs[code] = NFTRGlyph(code=code, tile=tile, advance=advance)

        return nftr

    def to_bitmap_font(
        self,
        chars: str,
        width: int = 8,
        height: int = 12,
    ) -> BitmapFont:
        """
        Compile vector glyphs into a BitmapFont object with proportional VWF measurement.
        """
        bf = BitmapFont(default_height=height, default_advance=width // 2)

        for ch in chars:
            if ch not in bf.glyphs:
                raw_pixels, advance = self.render_glyph_bitmap(ch, width=width, height=height)
                bf.add_glyph(
                    char=ch,
                    width=width,
                    height=height,
                    advance=advance,
                    bitmap=raw_pixels,
                )

        return bf

    def to_raw_tiles(
        self,
        chars: str,
        bpp: int = 2,
        tile_format: str = "chunky",
    ) -> Tuple[bytes, Dict[int, int]]:
        """
        Compile vector glyphs into a raw console 8x8 tile stream and character width table.
        Used for GBA, SNES, PS1, and Sega Genesis custom font replacement.
        Returns:
            (raw_tile_bytes, {codepoint: advance_width})
        """
        compiled = self.compile_glyphs(chars, bpp=bpp)
        tile_stream = bytearray()
        width_table = {}

        for code in sorted(compiled.keys()):
            tile, advance = compiled[code]
            tile_bytes = encode_tile(tile, bpp=bpp, planar=(tile_format == "planar"))
            tile_stream.extend(tile_bytes)
            width_table[code] = advance

        return bytes(tile_stream), width_table
