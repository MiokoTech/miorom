"""
miorom.text.pixel_wrapper
~~~~~~~~~~~~~~~~~~~~~~~~~
Pixel-Accurate Typography and Variable Width Font (VWF) Word-Wrapper.
Measures true on-screen pixel dimensions rather than character counts,
preventing dialogue overflow in proportional fonts.
"""

import re
from typing import Dict, List, Optional, Tuple


class FontMetrics:
    """
    Holds per-character pixel width metrics for proportional/VWF game fonts.
    """

    # Proportional standard Latin font width heuristics (relative scale)
    DEFAULT_WIDTHS = {
        "i": 4, "l": 4, "j": 5, "f": 5, "t": 5, "r": 6, "1": 6, "!": 4, ".": 4, ",": 4, ":": 4,
        "m": 12, "w": 12, "M": 14, "W": 14, "@": 14, "%": 12,
        "A": 9, "B": 9, "C": 9, "D": 9, "E": 8, "F": 8, "G": 10, "H": 9, "I": 4, "J": 7,
        "K": 9, "L": 8, "N": 9, "O": 10, "P": 9, "Q": 10, "R": 9, "S": 8, "T": 8, "U": 9,
        "V": 9, "X": 9, "Y": 9, "Z": 8, " ": 5,
    }

    def __init__(self, widths: Optional[Dict[str, int]] = None, default_width: int = 8):
        self.widths: Dict[str, int] = dict(self.DEFAULT_WIDTHS)
        if widths:
            self.widths.update(widths)
        self.default_width = default_width
        self._tag_regex = re.compile(r"<[^>]+>|\[0x[0-9a-fA-F]+\]")

    def measure_char(self, ch: str) -> int:
        return self.widths.get(ch, self.default_width)

    def measure_text(self, text: str) -> int:
        """Measure total pixel width of a string, ignoring formatting/control tags."""
        clean = self._tag_regex.sub("", text)
        return sum(self.measure_char(ch) for ch in clean)


class PixelWordWrapper:
    """
    Word-wrapper that wraps text lines based on pixel width constraints.

    Example:
        metrics = FontMetrics()
        wrapper = PixelWordWrapper(metrics, max_pixel_width=180, max_lines=3)
        wrapped = wrapper.wrap("Halo petualang! Apakah kamu sudah siap menjelajah?")
    """

    def __init__(
        self,
        metrics: Optional[FontMetrics] = None,
        max_pixel_width: int = 240,
        max_lines: int = 3,
    ):
        self.metrics = metrics or FontMetrics()
        self.max_pixel_width = max_pixel_width
        self.max_lines = max_lines

    def wrap(
        self,
        text: str,
        max_pixel_width: Optional[int] = None,
        newline: str = "\n",
        strip_lines: bool = True,
    ) -> str:
        """
        Wrap words so each line fits within max_pixel_width.

        Keyword Args:
            max_pixel_width: Override default maximum pixel width.
            newline: Line separator string (default: '\\n').
            strip_lines: Strip whitespace on each wrapped line (default: True).
        """
        target_width = max_pixel_width if max_pixel_width is not None else self.max_pixel_width
        paragraphs = text.split("\n")
        wrapped_paragraphs = []

        for p in paragraphs:
            words = p.split(" ")
            lines: List[str] = []
            cur_line = []

            for w in words:
                candidate = " ".join(cur_line + [w]) if cur_line else w
                if self.metrics.measure_text(candidate) <= target_width:
                    cur_line.append(w)
                else:
                    if cur_line:
                        line_str = " ".join(cur_line)
                        lines.append(line_str.strip() if strip_lines else line_str)
                        cur_line = [w]
                    else:
                        # Single word exceeds max pixel width
                        lines.append(w.strip() if strip_lines else w)
                        cur_line = []

            if cur_line:
                line_str = " ".join(cur_line)
                lines.append(line_str.strip() if strip_lines else line_str)

            wrapped_paragraphs.append(newline.join(lines))

        return newline.join(wrapped_paragraphs)

    def validate(
        self,
        text: str,
        max_pixel_width: Optional[int] = None,
        max_lines: Optional[int] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Validate if text exceeds max_pixel_width on any line or exceeds max_lines.

        Keyword Args:
            max_pixel_width: Override default maximum pixel width boundary.
            max_lines: Override default maximum line limit.
        """
        target_width = max_pixel_width if max_pixel_width is not None else self.max_pixel_width
        target_lines = max_lines if max_lines is not None else self.max_lines

        warnings: List[str] = []
        lines = text.split("\n")

        if len(lines) > target_lines:
            warnings.append(f"Line count ({len(lines)}) exceeds maximum lines ({target_lines})")

        for idx, line in enumerate(lines, start=1):
            px_w = self.metrics.measure_text(line)
            if px_w > target_width:
                warnings.append(
                    f"Line {idx} pixel width ({px_w}px) exceeds boundary ({target_width}px): '{line[:40]}...'"
                )

        return (len(warnings) == 0, warnings)
