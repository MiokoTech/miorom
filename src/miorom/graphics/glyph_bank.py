"""
miorom.graphics.glyph_bank
~~~~~~~~~~~~~~~~~~~~~~~~~~
Bitmap Glyph Harvester and Font Recomposer.
Extracts individual glyphs from game textures and recomposes localized text
while preserving 100% of original aesthetics (bevels, borders, anti-aliased shadows, and palettes).
"""

from __future__ import annotations

from dataclasses import dataclass
import io
import os
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


@dataclass
class Glyph:
    """Represents a single extracted bitmap glyph."""
    char: str
    width: int
    height: int
    rgba: bytes
    advance_x: int = 0

    def __post_init__(self):
        if not self.advance_x:
            self.advance_x = self.width

    def to_image(self) -> "Image.Image":
        if not HAS_PIL:
            raise ImportError("Pillow is required to convert Glyph to Image.")
        return Image.frombytes("RGBA", (self.width, self.height), self.rgba)


def find_luminance_valleys(
    rgba_bytes: bytes,
    width: int,
    height: int,
    core_threshold: int = 140,
    alpha_threshold: int = 30,
) -> List[Tuple[int, int]]:
    """
    Scans vertical columns of an RGBA buffer to locate contiguous character blocks
    based on core luminance peaks, cleanly separating characters whose drop shadows
    or outer borders connect horizontally.
    Returns a list of (start_x, end_x) column ranges.
    """
    active_cols = []
    for x in range(width):
        has_core = False
        for y in range(height):
            idx = (y * width + x) * 4
            r = rgba_bytes[idx]
            g = rgba_bytes[idx + 1]
            b = rgba_bytes[idx + 2]
            a = rgba_bytes[idx + 3]
            if a > alpha_threshold:
                lum = (r * 299 + g * 587 + b * 114) // 1000
                if lum >= core_threshold:
                    has_core = True
                    break
        active_cols.append(has_core)

    blocks: List[Tuple[int, int]] = []
    in_block = False
    start = 0
    for x, active in enumerate(active_cols):
        if active and not in_block:
            in_block = True
            start = x
        elif not active and in_block:
            in_block = False
            blocks.append((start, x))
    if in_block:
        blocks.append((start, width))

    return blocks


class GlyphBank:

    """
    Manages a collection of extracted bitmap glyphs and recomposes translated phrases.
    """

    def __init__(self, glyphs: Optional[Dict[str, Glyph]] = None):
        self.glyphs: Dict[str, Glyph] = glyphs or {}

    def add_glyph(
        self,
        char: str,
        image_or_rgba: Union["Image.Image", bytes],
        width: Optional[int] = None,
        height: Optional[int] = None,
        advance_x: Optional[int] = None,
    ) -> Glyph:
        """Adds a glyph directly to the bank."""
        if HAS_PIL and isinstance(image_or_rgba, Image.Image):
            pil_img = image_or_rgba.convert("RGBA")
            w, h = pil_img.size
            rgba = pil_img.tobytes()
        elif isinstance(image_or_rgba, (bytes, bytearray)):
            if width is None or height is None:
                raise ValueError("width and height must be specified when passing raw bytes.")
            w, h = width, height
            rgba = bytes(image_or_rgba)
        else:
            raise TypeError("Expected PIL Image or bytes.")

        glyph = Glyph(
            char=char,
            width=w,
            height=h,
            rgba=rgba,
            advance_x=advance_x or w,
        )
        self.glyphs[char] = glyph
        return glyph

    @classmethod
    def _to_rgba_image(cls, target: Union[str, bytes, "Image.Image"]) -> "Image.Image":
        if not HAS_PIL:
            raise ImportError("Pillow is required for GlyphBank image harvesting.")
        if isinstance(target, Image.Image):
            return target.convert("RGBA")
        if isinstance(target, str):
            return Image.open(target).convert("RGBA")
        if isinstance(target, (bytes, bytearray)):
            return Image.open(io.BytesIO(target)).convert("RGBA")
        raise TypeError(f"Unsupported image target: {type(target)}")

    def harvest_boxes(
        self,
        image: Union[str, bytes, "Image.Image"],
        mapping: Dict[str, Tuple[int, int, int, int]],
    ) -> "GlyphBank":
        """
        Harvests glyphs from explicit bounding boxes: {char: (x, y, width, height)}.
        """
        img = self._to_rgba_image(image)
        for char, (x, y, w, h) in mapping.items():
            cropped = img.crop((x, y, x + w, y + h))
            self.add_glyph(char, cropped)
        return self

    def harvest_widths(
        self,
        image: Union[str, bytes, "Image.Image"],
        chars: str,
        widths: List[int],
        height: int,
        start_x: int = 0,
        start_y: int = 0,
    ) -> "GlyphBank":
        """
        Harvests a horizontal sequence of glyphs with varying character widths.
        """
        if len(chars) != len(widths):
            raise ValueError(f"Length of chars ({len(chars)}) must match widths ({len(widths)}).")

        img = self._to_rgba_image(image)
        cur_x = start_x
        for char, w in zip(chars, widths):
            cropped = img.crop((cur_x, start_y, cur_x + w, start_y + height))
            self.add_glyph(char, cropped)
            cur_x += w
        return self

    def harvest_grid(
        self,
        image: Union[str, bytes, "Image.Image"],
        chars: str,
        cell_w: int,
        cell_h: int,
        start_x: int = 0,
        start_y: int = 0,
        trim: bool = False,
    ) -> "GlyphBank":
        """
        Harvests glyphs arranged in a regular row-column grid.
        """
        img = self._to_rgba_image(image)
        img_w, img_h = img.size
        cols = (img_w - start_x) // cell_w

        for i, char in enumerate(chars):
            col = i % cols
            row = i // cols
            x = start_x + col * cell_w
            y = start_y + row * cell_h
            if y + cell_h > img_h:
                break

            cropped = img.crop((x, y, x + cell_w, y + cell_h))
            if trim:
                # Trim transparent columns on left and right
                pix = cropped.load()
                cw, ch = cropped.size
                left, right = 0, cw - 1
                while left < cw and all(pix[left, py][3] == 0 for py in range(ch)):
                    left += 1
                while right >= left and all(pix[right, py][3] == 0 for py in range(ch)):
                    right -= 1
                if left <= right:
                    cropped = cropped.crop((left, 0, right + 1, ch))
            self.add_glyph(char, cropped)
        return self

    def auto_dissect(
        self,
        image: Union[str, bytes, "Image.Image"],
        chars: str,
        min_gap: int = 1,

        alpha_threshold: int = 30,
        use_valleys: bool = False,
        core_threshold: int = 140,
        border_padding: int = 1,
    ) -> "GlyphBank":
        """
        Automatically identifies horizontal glyph blocks separated by empty columns
        and assigns them sequentially to non-space characters in `chars`.
        If use_valleys is True, separates glyphs using core luminance peaks even when
        drop shadows or borders connect horizontally.
        """
        img = self._to_rgba_image(image)
        w, h = img.size
        pix = img.load()

        if use_valleys:
            raw_ranges = find_luminance_valleys(
                img.tobytes(),
                w,
                h,
                core_threshold=core_threshold,
                alpha_threshold=alpha_threshold,
            )
            ranges: List[Tuple[int, int]] = [
                (max(0, rx0 - border_padding), min(w, rx1 + border_padding))
                for rx0, rx1 in raw_ranges
            ]
        else:
            # Find active columns
            active_cols = [any(pix[x, y][3] > alpha_threshold for y in range(h)) for x in range(w)]

            # Group contiguous active columns into glyph ranges
            ranges = []
            in_glyph = False
            start_col = 0

            for x, active in enumerate(active_cols):
                if active and not in_glyph:
                    in_glyph = True
                    start_col = x
                elif not active and in_glyph:
                    in_glyph = False
                    ranges.append((start_col, x))
            if in_glyph:
                ranges.append((start_col, w))

        non_space_chars = [c for c in chars if c != " "]
        if len(ranges) != len(non_space_chars):
            raise ValueError(
                f"Auto-segmentation detected {len(ranges)} glyph blocks, "
                f"but {len(non_space_chars)} non-space characters were provided: '{non_space_chars}'."
            )

        for char, (gx0, gx1) in zip(non_space_chars, ranges):
            gw = gx1 - gx0
            cropped = img.crop((gx0, 0, gx1, h))
            self.add_glyph(char, cropped)

        return self


    def recompose_rgba(
        self,
        text: str,
        tracking: int = 0,
        border_overlap: int = 0,
        space_width: int = 4,
    ) -> Tuple[bytes, int, int]:
        """
        Composites the text string using pure-Python RGBA primitives.
        Returns (rgba_bytes, canvas_width, canvas_height).
        """
        # 1. Compute cursor positions and canvas dimensions
        cur_x = 0
        glyph_placements: List[Tuple[Optional[Glyph], int]] = []
        max_h = 1

        for i, c in enumerate(text):
            if c == " ":
                glyph_placements.append((None, cur_x))
                cur_x += space_width
            else:
                if c not in self.glyphs:
                    raise KeyError(f"Glyph '{c}' not found in GlyphBank (registered: {list(self.glyphs.keys())}).")
                g = self.glyphs[c]
                glyph_placements.append((g, cur_x))
                if g.height > max_h:
                    max_h = g.height
                if i == len(text) - 1:
                    cur_x += g.width
                else:
                    cur_x += max(1, g.width - border_overlap + tracking)

        canvas_w = max(1, cur_x)
        canvas_h = max_h
        canvas = bytearray(canvas_w * canvas_h * 4)

        # 2. Source-over alpha compositing loop
        for g, gx in glyph_placements:
            if g is None:
                continue

            gw, gh = g.width, g.height
            for py in range(gh):
                for px in range(gw):
                    dx = gx + px
                    dy = py
                    if 0 <= dx < canvas_w and 0 <= dy < canvas_h:
                        src_idx = (py * gw + px) * 4
                        dst_idx = (dy * canvas_w + dx) * 4

                        sr = g.rgba[src_idx]
                        sg = g.rgba[src_idx + 1]
                        sb = g.rgba[src_idx + 2]
                        sa = g.rgba[src_idx + 3]

                        if sa == 0:
                            continue

                        dr = canvas[dst_idx]
                        dg = canvas[dst_idx + 1]
                        db = canvas[dst_idx + 2]
                        da = canvas[dst_idx + 3]

                        if da == 0 or sa == 255:
                            canvas[dst_idx] = sr
                            canvas[dst_idx + 1] = sg
                            canvas[dst_idx + 2] = sb
                            canvas[dst_idx + 3] = sa
                        else:
                            # Standard alpha composite
                            out_a = sa + da * (255 - sa) // 255
                            out_r = (sr * sa + dr * da * (255 - sa) // 255) // max(1, out_a)
                            out_g = (sg * sa + dg * da * (255 - sa) // 255) // max(1, out_a)
                            out_b = (sb * sa + db * da * (255 - sa) // 255) // max(1, out_a)
                            canvas[dst_idx] = min(255, out_r)
                            canvas[dst_idx + 1] = min(255, out_g)
                            canvas[dst_idx + 2] = min(255, out_b)
                            canvas[dst_idx + 3] = min(255, out_a)

        return bytes(canvas), canvas_w, canvas_h

    def recompose(
        self,
        text: str,
        tracking: int = 0,
        border_overlap: int = 0,
        space_width: int = 4,
        target_width: Optional[int] = None,
        target_height: Optional[int] = None,
        align: str = "left",
        start_x: Optional[int] = None,
        start_y: Optional[int] = None,
    ) -> "Image.Image":
        """
        Composites the text string into a PIL RGBA Image.
        Optionally centers, pads, or positions within target_width and target_height.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for GlyphBank.recompose().")

        rgba_bytes, w, h = self.recompose_rgba(
            text=text,
            tracking=tracking,
            border_overlap=border_overlap,
            space_width=space_width,
        )
        rendered = Image.frombytes("RGBA", (w, h), rgba_bytes)

        if target_width is None and target_height is None:
            return rendered

        tw = target_width or w
        th = target_height or h
        canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))

        # Horizontal alignment offset
        if start_x is not None:
            off_x = start_x
        elif align == "center":
            off_x = max(0, (tw - w) // 2)
        elif align == "right":
            off_x = max(0, tw - w)
        else:
            off_x = 0

        if start_y is not None:
            off_y = start_y
        else:
            off_y = max(0, (th - h) // 2)

        canvas.paste(rendered, (off_x, off_y), rendered)
        return canvas

