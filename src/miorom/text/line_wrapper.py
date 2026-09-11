"""
miorom.text.line_wrapper
~~~~~~~~~~~~~~~~~~~~~~~~
Variable-Width Font (VWF) Smart Text Formatter and Pixel-Accurate Line Wrapper.
Provides pixel-accurate word wrapping, dialogue pagination, control code preservation,
and overflow diagnostics for game localization.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Pattern, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class TextBoxPage(MioRomResult):
    """Represents a single dialogue page within a paginated text box."""
    page_number: int
    lines: List[str]
    pixel_widths: List[int]
    max_line_width: int

    @property
    def line_count(self) -> int:
        return len(self.lines)


@dataclass
class LineWrapResult(MioRomResult):
    """Contains formatted text, pagination structure, and validation diagnostics."""
    fits: bool
    text: str
    pages: List[TextBoxPage] = field(default_factory=list)
    total_lines: int = 0
    warnings: List[str] = field(default_factory=list)


class VwfLineWrapper:
    """
    Pixel-accurate word-wrapper and paginator for Variable-Width Fonts (VWF).

    Supports width tables, FontGlyphInjector, callable measurers, embedded control code
    preservation, emergency hyphenation/splitting, and multi-page dialogue layout.
    """

    DEFAULT_CONTROL_PATTERN = re.compile(
        r"\[[A-Za-z0-9_:\-/#]+\]|\{[A-Za-z0-9_:\-/#]+\}|<[^>]+>|\\(?:x[0-9a-fA-F]{2}|[nrfteva\\])"
    )

    DEFAULT_WIDTHS: Dict[str, int] = {
        "i": 4, "l": 4, "j": 5, "f": 5, "t": 5, "r": 6, "1": 6, "!": 4, ".": 4, ",": 4, ":": 4,
        ";": 4, "'": 3, '"': 5, "`": 3, "|": 3,
        "m": 12, "w": 12, "M": 14, "W": 14, "@": 14, "%": 12,
        "A": 9, "B": 9, "C": 9, "D": 9, "E": 8, "F": 8, "G": 10, "H": 9, "I": 4, "J": 7,
        "K": 9, "L": 8, "N": 9, "O": 10, "P": 9, "Q": 10, "R": 9, "S": 8, "T": 8, "U": 9,
        "V": 9, "X": 9, "Y": 9, "Z": 8,
        "a": 8, "b": 8, "c": 7, "d": 8, "e": 8, "g": 8, "h": 8, "k": 8, "n": 8, "o": 8,
        "p": 8, "q": 8, "s": 7, "u": 8, "v": 8, "x": 8, "y": 8, "z": 7,
        "0": 8, "2": 8, "3": 8, "4": 8, "5": 8, "6": 8, "7": 8, "8": 8, "9": 8,
        " ": 5, "-": 5, "_": 8, "+": 8, "=": 8, "?": 7, "/": 6, "\\": 6,
    }

    def __init__(
        self,
        width_source: Union[
            Dict[str, int],
            bytes,
            bytearray,
            Callable[[str], int],
            Any,
            None,
        ] = None,
        default_char_width: int = 8,
        space_width: Optional[int] = None,
        control_pattern: Optional[Union[str, Pattern]] = None,
        tab_width: int = 32,
        hyphenate_overflow: bool = False,
        max_pixel_width: Optional[int] = None,
    ):
        self.default_char_width = default_char_width
        self.space_width = space_width if space_width is not None else self.DEFAULT_WIDTHS.get(" ", 5)
        self.tab_width = tab_width
        self.hyphenate_overflow = hyphenate_overflow
        self.max_pixel_width = max_pixel_width

        if isinstance(control_pattern, str):
            self.control_pattern = re.compile(control_pattern)
        elif control_pattern is not None:
            self.control_pattern = control_pattern
        else:
            self.control_pattern = self.DEFAULT_CONTROL_PATTERN

        self._width_map: Dict[str, int] = {}
        self._custom_callable: Optional[Callable[[str], int]] = None
        self._vwf_table_bytes: Optional[bytes] = None

        if width_source is None:
            self._width_map = dict(self.DEFAULT_WIDTHS)
        else:
            self._init_width_source(width_source)

    def _init_width_source(self, width_source: Any) -> None:
        if isinstance(width_source, dict):
            self._width_map = dict(width_source)
        elif isinstance(width_source, (bytes, bytearray)):
            self._vwf_table_bytes = bytes(width_source)
        elif callable(width_source):
            self._custom_callable = width_source
        elif hasattr(width_source, "calculate_glyph_width"):
            self._custom_callable = lambda ch: getattr(width_source, "calculate_glyph_width")(ch)
        elif hasattr(width_source, "measure_char"):
            self._custom_callable = lambda ch: getattr(width_source, "measure_char")(ch)
        elif hasattr(width_source, "widths") and isinstance(getattr(width_source, "widths"), dict):
            self._width_map = dict(getattr(width_source, "widths"))
        else:
            self._width_map = dict(self.DEFAULT_WIDTHS)

    def measure_char(self, ch: str) -> int:
        """Measure pixel width of a single character."""
        if ch == " ":
            return self.space_width
        if ch == "\t":
            return self.tab_width
        if self._custom_callable:
            return self._custom_callable(ch)
        if self._vwf_table_bytes is not None:
            code = ord(ch)
            if len(self._vwf_table_bytes) >= 256:
                if 0 <= code < len(self._vwf_table_bytes):
                    return self._vwf_table_bytes[code]
            else:
                if 0x20 <= code <= 0x7E:
                    ascii_offset = code - 0x20
                    if 0 <= ascii_offset < len(self._vwf_table_bytes):
                        return self._vwf_table_bytes[ascii_offset]
                if 0 <= code < len(self._vwf_table_bytes):
                    return self._vwf_table_bytes[code]
            return self.default_char_width
        return self._width_map.get(ch, self.default_char_width)

    def measure_text(self, text: str) -> int:
        """Measure total pixel width of text, stripping non-rendering control codes."""
        clean = self.control_pattern.sub("", text)
        return sum(self.measure_char(ch) for ch in clean)

    def split_tokens(self, text: str) -> List[Tuple[str, bool]]:
        """Split text into a sequence of (token, is_control_code) pairs."""
        tokens: List[Tuple[str, bool]] = []
        last_end = 0

        for match in self.control_pattern.finditer(text):
            start, end = match.span()
            if start > last_end:
                tokens.append((text[last_end:start], False))
            tokens.append((match.group(0), True))
            last_end = end

        if last_end < len(text):
            tokens.append((text[last_end:], False))

        return tokens

    def _break_long_word(self, word: str, max_pixel_width: int) -> List[str]:
        """Break a single word exceeding max_pixel_width into fitting chunks."""
        chunks: List[str] = []
        cur_chunk = ""
        cur_px = 0
        hyphen_px = self.measure_char("-") if self.hyphenate_overflow else 0

        for ch in word:
            ch_px = self.measure_char(ch)
            limit = max_pixel_width - hyphen_px if self.hyphenate_overflow else max_pixel_width
            if cur_px + ch_px > limit and cur_chunk:
                chunk_str = cur_chunk + ("-" if self.hyphenate_overflow else "")
                chunks.append(chunk_str)
                cur_chunk = ch
                cur_px = ch_px
            else:
                cur_chunk += ch
                cur_px += ch_px

        if cur_chunk:
            chunks.append(cur_chunk)

        return chunks

    def wrap_line(self, text: str, max_pixel_width: int) -> List[str]:
        """
        Wrap a single paragraph into lines that do not exceed max_pixel_width.
        Preserves embedded control tags without attributing display width to them.
        """
        tokens = self.split_tokens(text)

        words_with_tags: List[str] = []
        current_word = ""

        for content, is_tag in tokens:
            if is_tag:
                current_word += content
            else:
                parts = content.split(" ")
                for idx, p in enumerate(parts):
                    if idx == 0:
                        current_word += p
                    else:
                        words_with_tags.append(current_word)
                        current_word = p

        if current_word:
            words_with_tags.append(current_word)

        lines: List[str] = []
        current_line: List[str] = []
        current_line_px = 0

        for word in words_with_tags:
            word_px = self.measure_text(word)

            if word_px > max_pixel_width:
                broken_chunks = self._break_long_word(word, max_pixel_width)
                for chunk in broken_chunks:
                    chunk_px = self.measure_text(chunk)
                    space_px = self.space_width if current_line else 0
                    if current_line and (current_line_px + space_px + chunk_px > max_pixel_width):
                        lines.append(" ".join(current_line))
                        current_line = [chunk]
                        current_line_px = chunk_px
                    else:
                        current_line.append(chunk)
                        current_line_px += space_px + chunk_px
                continue

            space_px = self.space_width if current_line else 0
            if current_line and (current_line_px + space_px + word_px > max_pixel_width):
                lines.append(" ".join(current_line))
                current_line = [word]
                current_line_px = word_px
            else:
                current_line.append(word)
                current_line_px += space_px + word_px

        if current_line:
            lines.append(" ".join(current_line))

        return lines

    def wrap(
        self,
        text: str,
        max_pixel_width: Optional[int] = None,
        line_break: str = "\n",
        newline: Optional[str] = None,
        strip_lines: bool = False,
    ) -> str:
        """Wrap entire text across paragraphs to conform with max_pixel_width."""
        limit = max_pixel_width if max_pixel_width is not None else self.max_pixel_width
        if limit is None:
            raise ValueError("max_pixel_width must be specified in wrap() or __init__().")

        sep = newline if newline is not None else line_break
        paragraphs = text.split("\n")
        all_lines: List[str] = []

        for p in paragraphs:
            wrapped_para = self.wrap_line(p, limit)
            if strip_lines:
                wrapped_para = [line.strip() for line in wrapped_para]
            all_lines.extend(wrapped_para)

        return sep.join(all_lines)

    def paginate(
        self,
        text: str,
        max_pixel_width: int,
        max_lines_per_page: int = 3,
        page_break: str = "[page]\n",
        line_break: str = "\n",
    ) -> str:
        """
        Wrap text and split into pages delimited by page_break.
        """
        wrapped_str = self.wrap(text, max_pixel_width, line_break=line_break)
        lines = wrapped_str.split(line_break)

        pages: List[str] = []
        for i in range(0, len(lines), max_lines_per_page):
            chunk = lines[i : i + max_lines_per_page]
            pages.append(line_break.join(chunk))

        return page_break.join(pages)

    def analyze(
        self,
        text: str,
        max_pixel_width: int,
        max_lines_per_page: int = 3,
        page_break_tag: str = "[page]",
    ) -> LineWrapResult:
        """
        Wrap text and analyze dialogue box boundary constraints.
        Returns a structured LineWrapResult containing pages, line widths, and warnings.
        """
        wrapped_str = self.wrap(text, max_pixel_width, line_break="\n")
        raw_lines = wrapped_str.split("\n")

        pages: List[TextBoxPage] = []
        warnings: List[str] = []
        total_lines = len(raw_lines)

        for page_idx, i in enumerate(range(0, total_lines, max_lines_per_page)):
            chunk = raw_lines[i : i + max_lines_per_page]
            widths = [self.measure_text(line) for line in chunk]
            max_w = max(widths) if widths else 0

            for line_idx, (line, w) in enumerate(zip(chunk, widths), start=1):
                if w > max_pixel_width:
                    warnings.append(
                        f"Page {page_idx + 1}, line {line_idx} width ({w}px) exceeds box ({max_pixel_width}px): '{line[:30]}...'"
                    )

            pages.append(
                TextBoxPage(
                    page_number=page_idx + 1,
                    lines=chunk,
                    pixel_widths=widths,
                    max_line_width=max_w,
                )
            )

        fits = len(warnings) == 0 and (total_lines <= max_lines_per_page)

        paginated_text = (page_break_tag + "\n").join("\n".join(page.lines) for page in pages)

        return LineWrapResult(
            fits=fits,
            text=paginated_text,
            pages=pages,
            total_lines=total_lines,
            warnings=warnings,
        )
