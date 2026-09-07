"""
miorom.text.vwf
~~~~~~~~~~~~~~~
Variable Width Font (VWF) metrics engine and glyph width table manager.
Handles pixel-precise text measurement, proportional line wrapping, and
in-place width table editing for ROM hacking translations.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.text.charmap import CharMap


@dataclass
class VWFMetrics:
    """Configurable metrics for variable width rendering."""
    space_width: int = 4
    tracking: int = 1  # Inter-character spacing in pixels
    line_spacing: int = 16
    default_glyph_width: int = 8


class GlyphWidthTable:
    """
    Linear glyph width table (1-byte or 2-byte per character).
    Commonly found in SNES, GBA, PS1, and NDS executables and font containers.
    """

    def __init__(
        self,
        widths: List[int],
        charmap: Optional[CharMap] = None,
        base_index: int = 0,
        metrics: Optional[VWFMetrics] = None,
    ):
        self.widths = list(widths)
        self.charmap = charmap
        self.base_index = base_index
        self.metrics = metrics or VWFMetrics()

    @classmethod
    def from_binary(
        cls,
        data: bytes,
        count: int,
        entry_size: int = 1,
        offset: int = 0,
        charmap: Optional[CharMap] = None,
        base_index: int = 0,
    ) -> "GlyphWidthTable":
        """Reads width table from binary bytes."""
        widths: List[int] = []
        for i in range(count):
            pos = offset + (i * entry_size)
            if entry_size == 1:
                w = data[pos]
            elif entry_size == 2:
                w = data[pos] | (data[pos + 1] << 8)
            else:
                raise ValueError("Entry size must be 1 or 2 bytes.")
            widths.append(w)
        return cls(widths, charmap=charmap, base_index=base_index)

    def to_binary(self, entry_size: int = 1) -> bytes:
        """Serializes width table into binary."""
        out = bytearray()
        for w in self.widths:
            if entry_size == 1:
                out.append(min(255, max(0, w)))
            elif entry_size == 2:
                out.extend(min(65535, max(0, w)).to_bytes(2, "little"))
        return bytes(out)

    def get_width(self, char: str) -> int:
        """Returns pixel width of a single character."""
        if char == " ":
            return self.metrics.space_width

        if self.charmap:
            encoded = self.charmap.encode(char)
            if len(encoded) == 1:
                idx = encoded[0] - self.base_index
            elif len(encoded) == 2:
                idx = int.from_bytes(encoded, "big") - self.base_index
            else:
                idx = ord(char) - self.base_index
        else:
            idx = ord(char) - self.base_index

        if 0 <= idx < len(self.widths):
            return self.widths[idx]
        return self.metrics.default_glyph_width

    def set_width(self, char: str, width: int) -> None:
        """Sets pixel width for a character."""
        if self.charmap:
            encoded = self.charmap.encode(char)
            idx = (
                encoded[0] - self.base_index
                if len(encoded) == 1
                else int.from_bytes(encoded, "big") - self.base_index
            )
        else:
            idx = ord(char) - self.base_index

        if 0 <= idx < len(self.widths):
            self.widths[idx] = width

    def measure_text(self, text: str) -> int:
        """Calculates exact rendered width of a text string in pixels."""
        if not text:
            return 0

        total = 0
        tracking = self.metrics.tracking
        for i, char in enumerate(text):
            if char in ("\n", "\r"):
                continue
            w = self.get_width(char)
            total += w
            if i < len(text) - 1 and text[i + 1] not in ("\n", "\r"):
                total += tracking
        return total

    def wrap_text(self, text: str, max_pixel_width: int) -> List[str]:
        """
        Splits text into lines fitting within max_pixel_width using exact proportional font metrics.
        """
        lines: List[str] = []
        raw_paragraphs = text.split("\n")

        for paragraph in raw_paragraphs:
            words = paragraph.split(" ")
            current_line: List[str] = []

            for word in words:
                candidate = " ".join(current_line + [word]) if current_line else word
                cand_width = self.measure_text(candidate)

                if cand_width <= max_pixel_width or not current_line:
                    current_line.append(word)
                else:
                    lines.append(" ".join(current_line))
                    current_line = [word]

            if current_line:
                lines.append(" ".join(current_line))

        return lines

    def patch_buffer(self, buffer: bytearray, offset: int, entry_size: int = 1) -> None:
        """Patches the width table directly into a binary ROM buffer in-place."""
        raw = self.to_binary(entry_size=entry_size)
        buffer[offset : offset + len(raw)] = raw
