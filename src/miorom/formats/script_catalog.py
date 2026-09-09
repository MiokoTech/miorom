"""
miorom.formats.script_catalog
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Dialogue Script Formatter & Hex Code Sanitizer.
Converts messy binary-extracted CSVs (full of pointers and <XX> control bytes)
into pristine human-readable translation script files with format:
    [id]
    Text line 1
    Text line 2

And compiles translated clean scripts back into CSV translation columns or
ROM payloads, preserving template tags.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.formats.csv_handler import CsvHandler, TranslationRow
from miorom.result import MioRomResult


class DialogueCleaner:
    """
    Cleans raw dialogue strings by stripping low-level pointer noise,
    arbitrary binary hex tags, and formatting newlines cleanly for translators.
    """

    # Matches hex tags like <1A>, <05>, <00>, etc.
    HEX_TAG_RE = re.compile(r"<[0-9a-fA-F]{2}>")

    # Common game-engine newline control codes represented as hex tags
    NEWLINE_TAGS = ("<01>", "<0A>", "<0D>", "<01><01>")

    @classmethod
    def clean(
        cls,
        raw_text: str,
        preserve_newlines: bool = True,
        strip_headers: bool = True,
    ) -> str:
        """
        Cleans raw dialogue text of hex tags, pointer junk, and formatting noise.
        """
        if not raw_text:
            return ""

        text = raw_text

        # Replace newline control codes with actual newlines
        if preserve_newlines:
            for n_tag in cls.NEWLINE_TAGS:
                text = text.replace(n_tag, "\n")

        # Strip remaining hex control tags <XX>
        text = cls.HEX_TAG_RE.sub("", text)

        # Clean multiple spaces or weird artifacts left behind
        lines = [line.strip() for line in text.split("\n")]
        # Remove empty leading/trailing lines
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()

        return "\n".join(lines)


class ScriptCatalog:
    """
    Manages reading and writing dialogue catalogs in plain `[id]\ntext` format.
    """

    ID_HEADER_RE = re.compile(r"^\s*\[(\d+)\]\s*$")

    @classmethod
    def parse_script(cls, script_content: str) -> Dict[int, str]:
        """
        Parses a text file with [id] blocks into a dictionary {id: text}.
        """
        entries: Dict[int, str] = {}
        current_id: Optional[int] = None
        current_lines: List[str] = []

        for line in script_content.splitlines():
            m = cls.ID_HEADER_RE.match(line)
            if m:
                if current_id is not None:
                    entries[current_id] = "\n".join(current_lines).strip()
                current_id = int(m.group(1))
                current_lines = []
            else:
                if current_id is not None:
                    current_lines.append(line)

        if current_id is not None:
            entries[current_id] = "\n".join(current_lines).strip()

        return entries

    @classmethod
    def load_script(cls, filepath: str, encoding: str = "utf-8") -> Dict[int, str]:
        """Reads a [id] script file from disk."""
        with open(filepath, "r", encoding=encoding) as f:
            return cls.parse_script(f.read())

    @classmethod
    def dump_script(
        cls,
        filepath: str,
        rows: List[TranslationRow],
        clean: bool = True,
        encoding: str = "utf-8",
    ):
        """
        Dumps a list of TranslationRow items into the clean [id] text script format.
        """
        parent = os.path.dirname(filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)

        lines: List[str] = []
        for r in rows:
            raw = r.translation if (r.translation and r.translation.strip()) else r.original
            text = DialogueCleaner.clean(raw) if clean else raw
            lines.append(f"[{r.index}]")
            if text:
                lines.append(text)
            lines.append("")  # Empty separator line

        with open(filepath, "w", encoding=encoding) as f:
            f.write("\n".join(lines).strip() + "\n")

    @classmethod
    def csv_to_script(
        cls,
        csv_path: str,
        output_script_path: str,
        clean: bool = True,
    ):
        """Converts an existing CSV file into a clean [id] script file."""
        rows = CsvHandler.import_csv(csv_path)
        cls.dump_script(output_script_path, rows, clean=clean)

    @classmethod
    def script_to_csv(
        cls,
        script_path: str,
        base_csv_path: str,
        output_csv_path: str,
    ):
        """
        Merges translated clean text from [id] script back into the Translation column of CSV.
        """
        script_dict = cls.load_script(script_path)
        rows = CsvHandler.import_csv(base_csv_path)

        for r in rows:
            if r.index in script_dict:
                r.translation = script_dict[r.index]

        CsvHandler.export_csv(output_csv_path, rows)
