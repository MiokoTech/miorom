"""
miorom.text.metrics_measurer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pixel Text Metrics, Word Wrap, and Dialogue Page Partitioner Primitives.
Pure functional building blocks for calculating pixel lengths, wrapping words,
and partitioning multi-line dialogue boxes without hardcoded assumptions.
"""

import re
from typing import Dict, List, Optional, Sequence, Union

from miorom.text.vwf import GlyphWidthTable


class PixelTextMeasurer:
    """
    Pure primitive to measure pixel width of strings excluding non-printable tags.
    """

    @classmethod
    def measure_string(
        cls,
        text: str,
        glyph_widths: Optional[Union[GlyphWidthTable, Dict[int, int]]] = None,
        default_width: int = 8,
        tag_pattern: str = r"\[[^\]]+\]",
    ) -> int:
        """
        Calculates pixel width of text excluding control tags.
        """
        stripped = re.sub(tag_pattern, "", text)
        if not stripped:
            return 0

        if isinstance(glyph_widths, GlyphWidthTable):
            return glyph_widths.measure_string(stripped)
        elif isinstance(glyph_widths, dict):
            total = 0
            for c in stripped:
                total += glyph_widths.get(ord(c), default_width)
            return total
        else:
            return len(stripped) * default_width


class WordWrapSplitter:
    """
    Pure primitive to wrap text by pixel width.
    """

    @classmethod
    def wrap_by_pixels(
        cls,
        text: str,
        max_px: int,
        glyph_widths: Optional[Union[GlyphWidthTable, Dict[int, int]]] = None,
        default_width: int = 8,
        space_width: int = 4,
        line_break: str = "\n",
        tag_pattern: str = r"\[[^\]]+\]",
    ) -> str:
        """
        Wraps paragraphs at word boundaries where line pixel width <= max_px.
        """
        paragraphs = text.replace("\r\n", "\n").split("\n")
        output_paragraphs: List[str] = []

        for para in paragraphs:
            words = para.split(" ")
            if not words:
                output_paragraphs.append("")
                continue

            lines: List[str] = []
            cur_line_words: List[str] = []
            cur_line_px = 0

            for word in words:
                word_px = PixelTextMeasurer.measure_string(
                    word, glyph_widths, default_width, tag_pattern
                )
                added_px = word_px if not cur_line_words else (space_width + word_px)

                if cur_line_words and (cur_line_px + added_px > max_px):
                    lines.append(" ".join(cur_line_words))
                    cur_line_words = [word]
                    cur_line_px = word_px
                else:
                    cur_line_words.append(word)
                    cur_line_px += added_px

            if cur_line_words:
                lines.append(" ".join(cur_line_words))

            output_paragraphs.append(line_break.join(lines))

        return line_break.join(output_paragraphs)


class DialoguePagePartitioner:
    """
    Pure primitive to partition wrapped lines into individual dialogue box pages.
    """

    @classmethod
    def partition_pages(
        cls,
        wrapped_text: str,
        max_lines_per_page: int = 3,
        line_break: str = "\n",
    ) -> List[List[str]]:
        """
        Partitions lines into batches of max_lines_per_page.
        Returns List of pages, where each page is a List of line strings.
        """
        lines = wrapped_text.split(line_break)
        pages: List[List[str]] = []
        cur_page: List[str] = []

        for line in lines:
            cur_page.append(line)
            if len(cur_page) >= max_lines_per_page:
                pages.append(cur_page)
                cur_page = []

        if cur_page:
            pages.append(cur_page)

        return pages

    @classmethod
    def partition_pages_text(
        cls,
        wrapped_text: str,
        max_lines_per_page: int = 3,
        line_break: str = "\n",
        page_break: str = "[PAGE]",
    ) -> str:
        """
        Returns single string with page_break inserted between pages.
        """
        pages = cls.partition_pages(wrapped_text, max_lines_per_page, line_break)
        page_strings = [line_break.join(p) for p in pages]
        return page_break.join(page_strings)
