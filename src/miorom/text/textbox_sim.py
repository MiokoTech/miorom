import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from miorom.text.font_builder import BitmapFont


@dataclass
class TextboxConfig:
    """Dimensions, typography, and constraints for a simulated game dialogue box."""
    box_width_pixels: int = 240      # Total width of the textbox (e.g. 240 for GBA, 256 for SNES)
    box_height_pixels: int = 64      # Total height of the textbox
    max_lines_per_page: int = 3      # Maximum visible dialogue lines before page advance
    line_spacing: int = 4            # Vertical pixel spacing between lines
    margin_left: int = 8             # Left margin padding
    margin_right: int = 8            # Right margin padding
    margin_top: int = 8              # Top margin padding
    margin_bottom: int = 8           # Bottom margin padding
    portrait_width: int = 0          # Left margin offset if a speaker portrait is displayed
    page_break_tag: str = "<PAGE>"   # Tag to indicate page advance
    line_break_tag: str = "<LINE>"   # Tag to indicate hard line break

    @property
    def usable_text_width(self) -> int:
        """Usable horizontal width in pixels for text wrapping."""
        return max(16, self.box_width_pixels - (self.margin_left + self.portrait_width + self.margin_right))


@dataclass
class DialoguePage:
    """Represents a single screen/page of dialogue within a textbox."""
    page_index: int
    lines: List[str]
    has_overflow: bool = False
    max_line_width: int = 0

    @property
    def line_count(self) -> int:
        return len(self.lines)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class AutoPaginator:
    """
    Automated Dialogue Paginator and Textbox Formatter.
    Measures proportional text using BitmapFont or custom width callbacks,
    wraps words without breaking mid-word, and cleanly paginates long paragraphs
    into separate dialogue box screens with <PAGE> tags.
    """

    def __init__(self, config: Optional[TextboxConfig] = None):
        self.config = config or TextboxConfig()

    def paginate(
        self,
        text: str,
        font_or_measurer: Optional[Any] = None,
    ) -> List[DialoguePage]:
        """
        Split dialogue text into a list of DialoguePage objects.
        font_or_measurer can be a BitmapFont instance or a callable: (str) -> int.
        """
        cfg = self.config
        usable_width = cfg.usable_text_width

        # Width measurement function
        if callable(font_or_measurer):
            measure_func = font_or_measurer
        elif isinstance(font_or_measurer, BitmapFont):
            measure_func = font_or_measurer.measure_string
        else:
            # Default fallback: 8 pixels per monospace character
            measure_func = lambda s: len(s) * 8

        # Normalize line breaks and explicit page break tags
        # Replace <PAGE> with special marker
        normalized = text.replace(cfg.page_break_tag, "\x0c")
        # Replace <LINE> with standard newline
        normalized = normalized.replace(cfg.line_break_tag, "\n")

        # Split on explicit page breaks first
        explicit_pages = normalized.split("\x0c")
        pages: List[DialoguePage] = []
        page_idx = 0

        for raw_page in explicit_pages:
            raw_lines = raw_page.split("\n")
            wrapped_lines: List[str] = []

            for raw_line in raw_lines:
                words = raw_line.split(" ")
                cur_line_words: List[str] = []

                for word in words:
                    if not word and cur_line_words:
                        continue

                    # Test adding word to current line
                    test_line = " ".join(cur_line_words + [word]) if cur_line_words else word
                    w = measure_func(test_line)

                    if w <= usable_width or not cur_line_words:
                        cur_line_words.append(word)
                    else:
                        # Wrap to new line
                        wrapped_lines.append(" ".join(cur_line_words))
                        cur_line_words = [word]

                if cur_line_words:
                    wrapped_lines.append(" ".join(cur_line_words))

            # Group wrapped lines into pages of max_lines_per_page
            for i in range(0, max(1, len(wrapped_lines)), cfg.max_lines_per_page):
                page_slice = wrapped_lines[i:i + cfg.max_lines_per_page]
                if not page_slice and pages:
                    continue

                max_w = max((measure_func(l) for l in page_slice), default=0)
                overflow = max_w > usable_width or len(page_slice) > cfg.max_lines_per_page

                pages.append(
                    DialoguePage(
                        page_index=page_idx,
                        lines=page_slice,
                        has_overflow=overflow,
                        max_line_width=max_w,
                    )
                )
                page_idx += 1

        return pages

    def format_with_tags(
        self,
        text: str,
        font_or_measurer: Optional[Any] = None,
    ) -> str:
        """
        Format dialogue text by injecting <LINE> and <PAGE> tags where appropriate.
        """
        pages = self.paginate(text, font_or_measurer)
        page_texts = []
        for p in pages:
            page_texts.append(self.config.line_break_tag.join(p.lines))
        return self.config.page_break_tag.join(page_texts)


class TextboxSimulator:
    """
    Simulates visual retro console dialogue boxes and exports PNG preview images
    for in-editor translation quality assurance (QA).
    """

    def __init__(self, config: Optional[TextboxConfig] = None):
        self.config = config or TextboxConfig()
        self.paginator = AutoPaginator(self.config)

    def render_page(
        self,
        page: DialoguePage,
        font: Optional[BitmapFont] = None,
        bg_color: Tuple[int, int, int, int] = (24, 32, 48, 240),
        border_color: Tuple[int, int, int, int] = (220, 220, 240, 255),
        text_color: Tuple[int, int, int, int] = (255, 255, 255, 255),
    ) -> Any:
        """
        Render a DialoguePage into a Pillow Image.
        Returns PIL Image object.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for visual TextboxSimulator rendering.")

        cfg = self.config
        img = Image.new("RGBA", (cfg.box_width_pixels, cfg.box_height_pixels), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 1. Draw box background and double border
        draw.rectangle([0, 0, cfg.box_width_pixels - 1, cfg.box_height_pixels - 1], fill=bg_color, outline=border_color, width=2)

        # 2. Draw portrait placeholder if specified
        if cfg.portrait_width > 0:
            p_box = [
                cfg.margin_left,
                cfg.margin_top,
                cfg.margin_left + cfg.portrait_width - 4,
                cfg.box_height_pixels - cfg.margin_bottom,
            ]
            draw.rectangle(p_box, fill=(40, 50, 70, 255), outline=border_color, width=1)

        # 3. Draw text lines
        start_x = cfg.margin_left + cfg.portrait_width
        start_y = cfg.margin_top

        line_height = font.default_height if font else 12

        for row_idx, line in enumerate(page.lines):
            y = start_y + row_idx * (line_height + cfg.line_spacing)
            cur_x = start_x

            if font:
                for ch in line:
                    g = font.get_glyph(ch)
                    if g:
                        for gy in range(g.height):
                            for gx in range(g.width):
                                px_val = g.get_pixel(gx, gy)
                                if px_val > 128:
                                    target_x = cur_x + gx
                                    target_y = y + gy
                                    if 0 <= target_x < cfg.box_width_pixels and 0 <= target_y < cfg.box_height_pixels:
                                        img.putpixel((target_x, target_y), text_color)
                        cur_x += g.advance
                    else:
                        cur_x += font.default_advance
            else:
                # Monospace fallback drawing
                draw.text((start_x, y), line, fill=text_color)

        return img
