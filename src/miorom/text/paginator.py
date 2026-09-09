"""
miorom.text.paginator
~~~~~~~~~~~~~~~~~~~~~
Smart Auto-Paginator and Pixel-Accurate Textbox Word Wrapper.
Enables translators to lengthen dialogues freely without visual overflow:
dynamically wraps words using Variable-Width Font (VWF) pixel metrics and
automatically splits overflowed paragraphs into multi-page dialogue boxes
with custom control tags ([PAGE], [WAIT], etc.).
"""

from miorom.result import MioRomResult
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.text.vwf import GlyphWidthTable
from miorom.text.po_handler import PoHandler, PoEntry


@dataclass
class PaginationConfig(MioRomResult):
    """Configuration for textbox geometry and pagination tags."""
    max_width_px: int = 200                  # Maximum pixel width per line
    max_lines_per_page: int = 3             # Number of lines before advancing page
    line_break_tag: str = "\n"              # Tag or character for newline
    page_break_tag: str = "[PAGE]"          # Tag inserted when dialogue box fills up
    default_char_width_px: int = 8          # Fallback width per character if no VWF table
    space_width_px: int = 4                 # Width of space character
    tag_regex: str = r"\[[^\]]+\]"          # Regex pattern for non-printable control tags


class SmartAutoPaginator:
    """
    Automated word wrapper and dialogue page divider.
    """

    def __init__(
        self,
        config: Optional[PaginationConfig] = None,
        glyph_table: Optional[GlyphWidthTable] = None,
    ):
        self.config = config or PaginationConfig()
        self.glyph_table = glyph_table
        self._tag_pattern = re.compile(self.config.tag_regex)

    def measure_word_width(self, word: str) -> int:
        """Calculates pixel width of a word, excluding non-printable control tags."""
        # Strip control tags like [COLOR:1] or [WAIT]
        stripped = self._tag_pattern.sub("", word)
        if not stripped:
            return 0

        if self.glyph_table is not None:
            return self.glyph_table.measure_string(stripped)
        return len(stripped) * self.config.default_char_width_px

    def paginate_text(self, text: str) -> str:
        """
        Wraps long paragraphs into pixel-bounded lines and pages.
        Inserts line breaks and page break tags automatically.
        """
        if not text:
            return text

        # Split into raw paragraphs or words
        # Preserve manual existing breaks if present
        raw_paragraphs = text.split(self.config.page_break_tag)
        paginated_pages: List[str] = []

        for para in raw_paragraphs:
            words = para.replace("\r\n", "\n").split()
            if not words:
                continue

            current_page_lines: List[str] = []
            current_line_words: List[str] = []
            current_line_px = 0

            for word in words:
                word_px = self.measure_word_width(word)
                space_px = self.config.space_width_px if current_line_words else 0

                if current_line_words and (current_line_px + space_px + word_px > self.config.max_width_px):
                    # Line full -> advance to next line
                    current_page_lines.append(" ".join(current_line_words))
                    current_line_words = [word]
                    current_line_px = word_px

                    # Check if page is full
                    if len(current_page_lines) >= self.config.max_lines_per_page:
                        paginated_pages.append(self.config.line_break_tag.join(current_page_lines))
                        current_page_lines = []
                else:
                    current_line_words.append(word)
                    current_line_px += space_px + word_px

            if current_line_words:
                current_page_lines.append(" ".join(current_line_words))

            if current_page_lines:
                paginated_pages.append(self.config.line_break_tag.join(current_page_lines))

        return self.config.page_break_tag.join(paginated_pages)

    def paginate_po(
        self,
        po_handler: PoHandler,
        in_place: bool = True,
    ) -> int:
        """
        Batch-paginates all translated strings (msgstr) in a PO catalog.
        Returns the number of entries processed and modified.
        """
        modified_count = 0
        for entry in po_handler.entries:
            target_text = entry.msgstr if entry.msgstr else entry.msgid
            if not target_text:
                continue

            new_text = self.paginate_text(target_text)
            if new_text != target_text:
                if in_place:
                    if entry.msgstr:
                        entry.msgstr = new_text
                    else:
                        entry.msgid = new_text
                modified_count += 1

        return modified_count
