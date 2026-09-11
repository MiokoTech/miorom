from miorom.result import MioRomResult
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from miorom.graphics.tiles import Tile


@dataclass
class Glyph(MioRomResult):
    char: str
    width: int
    height: int
    advance: int
    bitmap: List[int] = field(default_factory=list)  # Row-major pixel values (0-255)

    def get_pixel(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.bitmap[y * self.width + x]
        return 0

    def to_tile(self, tile_width: int = 8, tile_height: int = 8, threshold: int = 128) -> Tile:
        """Pads/crops glyph into an 8x8 Tile for console graphics."""
        pixels = [0] * 64
        for y in range(min(8, self.height)):
            for x in range(min(8, self.width)):
                val = self.get_pixel(x, y)
                pixels[y * 8 + x] = 1 if val >= threshold else 0
        return Tile(pixels)


class BitmapFont:
    """
    Console Bitmap Font generator and text measurer.
    Facilitates custom glyph insertion (e.g. accented characters, button icons)
    and pixel-accurate line width calculations for VWF (Variable-Width Font) games.
    """

    def __init__(self, default_height: int = 12, default_advance: int = 8):
        self.default_height = default_height
        self.default_advance = default_advance
        self.glyphs: Dict[str, Glyph] = {}

    def add_glyph(
        self,
        char: str,
        width: int,
        height: int,
        advance: int,
        bitmap: List[int],
    ) -> Glyph:
        glyph = Glyph(char=char, width=width, height=height, advance=advance, bitmap=bitmap)
        self.glyphs[char] = glyph
        return glyph

    def add_glyph_from_ascii_art(
        self,
        char: str,
        art: str,
        advance: Optional[int] = None,
        on_char: str = "#",
    ) -> Glyph:
        """
        Creates a glyph from clean ASCII art string.
        Example:
            art = '''
             .#.
            .###.
            #...#
            '''
        """
        import textwrap
        dedented = textwrap.dedent(art).strip("\n")
        lines = [line for line in dedented.split("\n")]
        # Remove common indentation
        if not lines:
            return self.add_glyph(char, 0, 0, advance or self.default_advance, [])

        height = len(lines)
        width = max(len(line) for line in lines)
        bitmap: List[int] = []

        for line in lines:
            padded_line = line.ljust(width, " ")
            for ch in padded_line:
                bitmap.append(255 if ch == on_char else 0)

        adv = advance if advance is not None else (width + 1)
        return self.add_glyph(char=char, width=width, height=height, advance=adv, bitmap=bitmap)

    def get_glyph(self, char: str) -> Optional[Glyph]:
        return self.glyphs.get(char)

    def measure_string(self, text: str) -> int:
        """Calculates exact total pixel width for a text string using glyph advances."""
        total_width = 0
        for ch in text:
            g = self.glyphs.get(ch)
            if g is not None:
                total_width += g.advance
            else:
                total_width += self.default_advance
        return total_width

    def render_line(self, text: str) -> Tuple[int, int, List[List[int]]]:
        """
        Renders a single line of text into a 2D pixel grid.
        Returns (width, height, 2D grid of 0-255 pixel values).
        """
        line_width = self.measure_string(text)
        line_height = self.default_height

        grid = [[0 for _ in range(line_width)] for _ in range(line_height)]
        cur_x = 0

        for ch in text:
            g = self.glyphs.get(ch)
            if g is not None:
                for gy in range(min(g.height, line_height)):
                    for gx in range(g.width):
                        target_x = cur_x + gx
                        if target_x < line_width:
                            grid[gy][target_x] = max(grid[gy][target_x], g.get_pixel(gx, gy))
                cur_x += g.advance
            else:
                cur_x += self.default_advance

        return line_width, line_height, grid
