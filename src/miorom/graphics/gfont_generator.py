"""
miorom.graphics.gfont_generator
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated GFontC (Banner/Menu Title) Generator for Rune Factory: Frontier and GX Platforms.
Converts arbitrary text strings directly into pixel-perfect textures and TPL files matching
the authentic retail game artwork (100% color gradients, borders, and drop shadows).
Powered by MioROM. Zero external binary dependencies.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import io
import os
from typing import Dict, List, Optional, Tuple, Union

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from miorom.graphics.glyph_bank import Glyph, GlyphBank
from miorom.platforms.wii.tpl import TPLFile


# Pre-harvested, cleaned master glyph atlas metadata (char -> (x0, y0, x1, y1))
MASTER_ATLAS_META: Dict[str, Tuple[int, int, int, int]] = {'1': (0, 0, 12, 20), '2': (12, 0, 25, 20), 'A': (25, 0, 38, 20), 'B': (38, 0, 50, 20), 'C': (50, 0, 61, 20), 'E': (61, 0, 73, 20), 'F': (73, 0, 84, 20), 'G': (84, 0, 97, 20), 'H': (97, 0, 110, 20), 'I': (110, 0, 114, 20), 'J': (114, 0, 125, 20), 'K': (125, 0, 138, 20), 'L': (138, 0, 149, 20), 'M': (150, 0, 166, 20), 'N': (166, 0, 178, 20), 'O': (178, 0, 191, 20), 'P': (191, 0, 203, 20), 'R': (203, 0, 215, 20), 'S': (215, 0, 227, 20), 'T': (227, 0, 241, 20), 'U': (241, 0, 254, 20), 'V': (254, 0, 267, 20), 'W': (267, 0, 283, 20), 'Y': (283, 0, 293, 20)}

# 291x20 RGBA PNG master atlas of retail glyphs (base64 compressed)
MASTER_ATLAS_PNG_B64: str = """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"""



SILVER_PALETTE_CI4: List[Tuple[int, int, int, int]] = [
    (51, 34, 0, 0),
    (51, 34, 0, 36),
    (51, 34, 0, 72),
    (51, 34, 0, 109),
    (51, 34, 0, 182),
    (51, 34, 0, 218),
    (57, 32, 8, 255),
    (74, 57, 32, 255),
    (98, 82, 57, 255),
    (123, 106, 90, 255),
    (148, 131, 115, 255),
    (164, 156, 148, 255),
    (189, 180, 172, 255),
    (213, 205, 197, 255),
    (238, 238, 238, 255),
    (255, 255, 255, 255),
]

GOLD_PALETTE_CI4: List[Tuple[int, int, int, int]] = [
    (51, 34, 0, 0),
    (51, 34, 0, 36),
    (51, 34, 0, 72),
    (51, 34, 0, 145),
    (51, 34, 0, 218),
    (49, 32, 0, 255),
    (51, 34, 0, 218),
    (49, 32, 0, 255),
    (90, 74, 41, 255),
    (115, 98, 65, 255),
    (156, 131, 98, 255),
    (187, 170, 136, 255),
    (222, 205, 172, 255),
    (246, 230, 197, 255),
    (255, 246, 213, 255),
    (255, 255, 255, 255),
]


class GFontCGenerator:
    """
    Automated high-precision bitmap font generator for Rune Factory: Frontier gfontC textures.
    Recomposes arbitrary text strings using clean authentic retail glyphs.
    """

    FORMAT_MAP = {
        "I4": 0,
        "I8": 1,
        "IA4": 2,
        "IA8": 3,
        "RGB565": 4,
        "RGB5A3": 5,
        "RGBA8": 6,
        "CI4": 8,
        "CI8": 9,
    }

    def __init__(
        self,
        atlas_image: Optional["Image.Image"] = None,
        atlas_meta: Optional[Dict[str, Tuple[int, int, int, int]]] = None,
    ):
        if not HAS_PIL:
            raise ImportError("Pillow is required for GFontCGenerator.")

        if atlas_image is None:
            png_bytes = base64.b64decode(MASTER_ATLAS_PNG_B64)
            self.atlas_image = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
        else:
            self.atlas_image = atlas_image.convert("RGBA")

        self.atlas_meta = atlas_meta if atlas_meta is not None else MASTER_ATLAS_META
        self.bank = GlyphBank()

        # Populate GlyphBank from atlas
        for char, (x0, y0, x1, y1) in self.atlas_meta.items():
            glyph_crop = self.atlas_image.crop((x0, y0, x1, y1))
            self.bank.add_glyph(char, glyph_crop)

    @property
    def available_characters(self) -> List[str]:
        """Returns sorted list of registered characters in the master bank."""
        return sorted(list(self.bank.glyphs.keys()))

    def add_glyph(self, char: str, image_or_path: Union[str, "Image.Image"]) -> "GFontCGenerator":
        """Adds or overrides a specific glyph in the generator's bank."""
        self.bank.add_glyph(char.upper(), image_or_path)
        return self

    def calculate_text_width(self, text: str, tracking: int = 1, border_overlap: int = 1) -> int:
        """Calculates total pixel width of text when composited."""
        total_w = 0
        text_up = text.upper()
        for i, ch in enumerate(text_up):
            if ch == " ":
                total_w += 4
            elif ch in self.bank.glyphs:
                gw = self.bank.glyphs[ch].width
                if i == len(text_up) - 1:
                    total_w += gw
                else:
                    total_w += max(1, gw - border_overlap + tracking)
            else:
                raise KeyError(f"Character '{ch}' not available in GFontCGenerator bank (available: {self.available_characters}).")
        return total_w

    def render_image(
        self,
        text: str,
        width: int = 80,
        height: int = 20,
        align: str = "center",
        tracking: int = 1,
        border_overlap: int = 1,
        start_x: Optional[int] = None,
        auto_scale: bool = True,
    ) -> "Image.Image":
        """
        Renders the given text into an RGBA PIL Image.

        Args:
            text: Text to render (automatically uppercased).
            width: Canvas width in pixels (e.g. 80, 64, 40, 96).
            height: Canvas height in pixels (standard 20).
            align: Alignment ('center', 'left', 'right'). Ignored if start_x is specified.
            tracking: Extra spacing between characters (standard 1).
            border_overlap: Number of overlapping border pixels (standard 1).
            start_x: Explicit starting horizontal offset.
            auto_scale: Whether to scale horizontally if text exceeds canvas width.
        """
        text_up = text.upper()
        text_w = self.calculate_text_width(text_up, tracking=tracking, border_overlap=border_overlap)
        max_allowed_w = width - 2

        if auto_scale and text_w > max_allowed_w and start_x is None:
            raw_img = self.bank.recompose(
                text_up,
                target_width=text_w,
                target_height=height,
                start_x=0,
                tracking=tracking,
                border_overlap=border_overlap,
            )
            scaled_w = max_allowed_w
            scaled_img = raw_img.resize((scaled_w, height), Image.Resampling.BILINEAR)
            out_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            paste_x = max(0, (width - scaled_w) // 2)
            out_img.paste(scaled_img, (paste_x, 0))
            return out_img

        if start_x is None:
            if align == "center":
                start_x = max(0, (width - text_w) // 2)
            elif align == "right":
                start_x = max(0, width - text_w - 2)
            else:  # left
                start_x = 2

        return self.bank.recompose(
            text_up,
            target_width=width,
            target_height=height,
            start_x=start_x,
            tracking=tracking,
            border_overlap=border_overlap,
        )

    def render_tpl(
        self,
        text: str,
        width: int = 80,
        height: int = 20,
        format: Union[str, int] = "RGB5A3",
        align: str = "center",
        tracking: int = 1,
        border_overlap: int = 1,
        start_x: Optional[int] = None,
        auto_scale: bool = True,
        palette: Optional[Union[str, List[Tuple[int, int, int, int]]]] = None,
    ) -> TPLFile:
        """
        Renders the text directly to a Nintendo GX TPLFile.
        Default format: 'RGB5A3' (format ID 5) or 'CI4' (format ID 8).
        """
        im = self.render_image(
            text=text,
            width=width,
            height=height,
            align=align,
            tracking=tracking,
            border_overlap=border_overlap,
            start_x=start_x,
            auto_scale=auto_scale,
        )

        fmt_id: int
        if isinstance(format, int):
            fmt_id = format
        else:
            fmt_id = self.FORMAT_MAP.get(format.upper(), 5)

        pal = None
        if fmt_id in (8, 9):
            if palette is None or palette == "silver":
                pal = SILVER_PALETTE_CI4
            elif palette == "gold":
                pal = GOLD_PALETTE_CI4
            elif isinstance(palette, list):
                pal = palette

        return TPLFile.from_image(im, format_id=fmt_id, palette=pal)

    def render_ascii(
        self,
        text: str,
        width: int = 80,
        height: int = 20,
        align: str = "center",
        tracking: int = 1,
        border_overlap: int = 1,
        start_x: Optional[int] = None,
        alpha_threshold: int = 30,
        auto_scale: bool = True,
    ) -> str:
        """Renders text and returns terminal ASCII art string."""
        im = self.render_image(
            text=text,
            width=width,
            height=height,
            align=align,
            tracking=tracking,
            border_overlap=border_overlap,
            start_x=start_x,
            auto_scale=auto_scale,
        )

        ascii_chars = " .:-=+*#%@"
        lines: List[str] = []
        w, h = im.size
        for y in range(h):
            row_chars: List[str] = []
            for x in range(w):
                r, g, b, a = im.getpixel((x, y))
                if a < alpha_threshold:
                    row_chars.append(" ")
                else:
                    idx = int(r * (len(ascii_chars) - 1) // 255)
                    row_chars.append(ascii_chars[idx])
            lines.append("".join(row_chars))
        return "\n".join(lines)

    def generate_and_save(
        self,
        text: str,
        out_png: Optional[str] = None,
        out_tpl: Optional[str] = None,
        width: int = 80,
        height: int = 20,
        format: Union[str, int] = "RGB5A3",
        align: str = "center",
        tracking: int = 1,
        border_overlap: int = 1,
        start_x: Optional[int] = None,
        auto_scale: bool = True,
        palette: Optional[Union[str, List[Tuple[int, int, int, int]]]] = None,
    ) -> Tuple["Image.Image", Optional[TPLFile]]:
        """Renders text and saves PNG and/or TPL to disk."""
        im = self.render_image(
            text=text,
            width=width,
            height=height,
            align=align,
            tracking=tracking,
            border_overlap=border_overlap,
            start_x=start_x,
            auto_scale=auto_scale,
        )

        tpl: Optional[TPLFile] = None
        if out_tpl:
            fmt_id = format if isinstance(format, int) else self.FORMAT_MAP.get(format.upper(), 5)
            pal = None
            if fmt_id in (8, 9):
                if palette is None or palette == "silver":
                    pal = SILVER_PALETTE_CI4
                elif palette == "gold":
                    pal = GOLD_PALETTE_CI4
                elif isinstance(palette, list):
                    pal = palette
            tpl = TPLFile.from_image(im, format_id=fmt_id, palette=pal)
            os.makedirs(os.path.dirname(os.path.abspath(out_tpl)), exist_ok=True)
            with open(out_tpl, "wb") as f:
                f.write(tpl.to_bytes())

        if out_png:
            os.makedirs(os.path.dirname(os.path.abspath(out_png)), exist_ok=True)
            im.save(out_png, format="PNG")

        return im, tpl


def main():
    parser = argparse.ArgumentParser(description="MioROM GFontC Texture Generator")
    parser.add_argument("text", type=str, help="Text to render (e.g. 'KAYU')")
    parser.add_argument("-w", "--width", type=int, default=80, help="Canvas width (default: 80)")
    parser.add_argument("-H", "--height", type=int, default=20, help="Canvas height (default: 20)")
    parser.add_argument("-f", "--format", type=str, default="RGB5A3", help="GX Format (default: RGB5A3)")
    parser.add_argument("-a", "--align", type=str, default="center", choices=["center", "left", "right"])
    parser.add_argument("--tracking", type=int, default=1, help="Letter tracking/spacing (default: 1)")
    parser.add_argument("--overlap", type=int, default=1, help="Border overlap (default: 1)")
    parser.add_argument("--start-x", type=int, default=None, help="Explicit start x coordinate")
    parser.add_argument("--png", type=str, default=None, help="Output PNG path")
    parser.add_argument("--tpl", type=str, default=None, help="Output TPL path")
    parser.add_argument("--ascii", action="store_true", help="Print ASCII representation to stdout")

    args = parser.parse_args()
    gen = GFontCGenerator()
    im, tpl = gen.generate_and_save(
        text=args.text,
        out_png=args.png,
        out_tpl=args.tpl,
        width=args.width,
        height=args.height,
        format=args.format,
        align=args.align,
        tracking=args.tracking,
        border_overlap=args.overlap,
        start_x=args.start_x,
    )

    if args.ascii or (not args.png and not args.tpl):
        print(gen.render_ascii(
            text=args.text,
            width=args.width,
            height=args.height,
            align=args.align,
            tracking=args.tracking,
            border_overlap=args.overlap,
            start_x=args.start_x,
        ))

    if args.png:
        print(f"Saved PNG: {args.png}")
    if args.tpl:
        print(f"Saved TPL: {args.tpl} ({len(tpl.to_bytes())} bytes, format={args.format})")


if __name__ == "__main__":
    main()
