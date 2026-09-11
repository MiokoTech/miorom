"""
miorom.script.extractor
~~~~~~~~~~~~~~~~~~~~~~~
Universal script string extractor and reinserter for ROM hacking workflows.
"""

import csv
import io
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.result import MioRomResult
from miorom.text.charmap import CharMap


@dataclass
class ExtractedEntry(MioRomResult):
    """A single extracted script string with metadata."""
    index: int
    offset: int
    raw_bytes: bytes
    decoded_text: str
    control_codes: List[str]


@dataclass
class ExtractionResult(MioRomResult):
    """Aggregate result of a multi-offset extraction pass."""
    entries: List[ExtractedEntry]
    total_bytes: int
    charmap_name: str


@dataclass
class InsertionReport(MioRomResult):
    """Report produced after inserting translations back into a ROM buffer."""
    total_entries: int
    inserted: int
    skipped: int
    overflow_warnings: List[str]


class ScriptExtractor:
    """
    Extracts null-terminated (or custom-terminated) strings from ROM data
    using a CharMap, and reinserts translated strings back at the same offsets.
    """

    def __init__(
        self,
        charmap: CharMap,
        end_token: bytes = b"\x00",
        control_codes: Optional[Dict[bytes, str]] = None,
    ) -> None:
        self._charmap = charmap
        self._end_token = end_token
        self._control_codes: Dict[bytes, str] = control_codes or {}
        self._cc_max_len: int = max((len(k) for k in self._control_codes), default=0)

    def _read_raw(self, rom: Union[bytes, bytearray], offset: int) -> bytes:
        """Read bytes from offset until end_token is found."""
        end = self._end_token
        elen = len(end)
        pos = offset
        buf_len = len(rom)
        while pos < buf_len:
            if rom[pos:pos + elen] == end:
                break
            pos += 1
        return bytes(rom[offset:pos])

    def _tag_control_codes(self, raw: bytes) -> List[str]:
        """Return list of control code tags found in raw bytes."""
        found: List[str] = []
        i = 0
        while i < len(raw):
            matched = False
            for length in range(min(self._cc_max_len, len(raw) - i), 0, -1):
                chunk = raw[i:i + length]
                if chunk in self._control_codes:
                    found.append(self._control_codes[chunk])
                    i += length
                    matched = True
                    break
            if not matched:
                i += 1
        return found

    def extract(
        self,
        rom: Union[bytes, bytearray],
        offsets: List[int],
    ) -> ExtractionResult:
        """Read a string at each offset and return an ExtractionResult."""
        entries: List[ExtractedEntry] = []
        total_bytes = 0

        for idx, offset in enumerate(offsets):
            raw = self._read_raw(rom, offset)
            text = self._charmap.decode(raw)
            codes = self._tag_control_codes(raw)
            entries.append(
                ExtractedEntry(
                    index=idx,
                    offset=offset,
                    raw_bytes=raw,
                    decoded_text=text,
                    control_codes=codes,
                )
            )
            total_bytes += len(raw)

        return ExtractionResult(
            entries=entries,
            total_bytes=total_bytes,
            charmap_name=type(self._charmap).__name__,
        )

    def to_txt(self, result: ExtractionResult) -> str:
        """
        Render ExtractionResult as a human-editable text block.

        Format per entry:
            [NNNN] Offset=0xXXXX
            <decoded text>
            ---
        """
        lines: List[str] = []
        for entry in result.entries:
            lines.append(f"[{entry.index:04d}] Offset=0x{entry.offset:04X}")
            lines.append(entry.decoded_text)
            lines.append("---")
        return "\n".join(lines) + ("\n" if lines else "")

    def to_csv(self, result: ExtractionResult) -> str:
        """Render ExtractionResult as a CSV with columns: index,offset,source,translation."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["index", "offset", "source", "translation"])
        for entry in result.entries:
            writer.writerow([entry.index, entry.offset, entry.decoded_text, ""])
        return buf.getvalue()

    def from_txt(self, txt: str) -> List[Tuple[int, str]]:
        """
        Parse a to_txt()-formatted string back into (index, text) pairs.

        Lines between a [NNNN] header and the next '---' separator form the text.
        """
        results: List[Tuple[int, str]] = []
        pattern = re.compile(r"^\[(\d+)\]\s+Offset=0x[0-9A-Fa-f]+$")

        current_index: Optional[int] = None
        text_lines: List[str] = []

        for line in txt.splitlines():
            m = pattern.match(line)
            if m:
                if current_index is not None:
                    results.append((current_index, "\n".join(text_lines)))
                current_index = int(m.group(1))
                text_lines = []
            elif line == "---":
                if current_index is not None:
                    results.append((current_index, "\n".join(text_lines)))
                    current_index = None
                    text_lines = []
            else:
                if current_index is not None:
                    text_lines.append(line)

        if current_index is not None:
            results.append((current_index, "\n".join(text_lines)))

        return results

    def insert(
        self,
        rom: Union[bytes, bytearray],
        offsets: List[int],
        translations: List[str],
        dry_run: bool = False,
    ) -> Tuple[bytearray, InsertionReport]:
        """
        Encode each translation and write it into the ROM at the corresponding offset.

        The insertion slot length is determined by the original string length (including
        end_token). Translations longer than the original slot trigger an overflow warning.
        dry_run=True returns a report without modifying the buffer.
        """
        buf = bytearray(rom)
        inserted = 0
        skipped = 0
        warnings: List[str] = []
        elen = len(self._end_token)

        for idx, (offset, text) in enumerate(zip(offsets, translations)):
            raw_original = self._read_raw(buf, offset)
            slot_len = len(raw_original)

            encoded = self._charmap.encode(text)

            if len(encoded) > slot_len:
                warnings.append(
                    f"Entry {idx} at 0x{offset:04X}: encoded length {len(encoded)} "
                    f"exceeds slot {slot_len} (overflow by {len(encoded) - slot_len})"
                )

            if not dry_run:
                write_len = min(len(encoded), slot_len)
                buf[offset:offset + write_len] = encoded[:write_len]
                buf[offset + write_len:offset + slot_len + elen] = self._end_token + bytes(
                    max(0, slot_len - write_len)
                )

            inserted += 1

        return buf, InsertionReport(
            total_entries=len(offsets),
            inserted=inserted,
            skipped=skipped,
            overflow_warnings=warnings,
        )
