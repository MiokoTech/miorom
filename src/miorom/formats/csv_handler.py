from miorom.result import MioRomResult
import csv
import os
from typing import List, Dict, Optional, Any, Union
from dataclasses import dataclass


@dataclass
class TranslationRow(MioRomResult):
    index: int
    offset: int
    original: str
    translation: str = ""
    context: str = ""

    @property
    def offset_hex(self) -> str:
        return hex(self.offset)


class CsvHandler:
    """
    Handles importing and exporting translation entries in RFC 4180 CSV / TSV formats.
    Fully compatible with Microsoft Excel, Google Sheets, LibreOffice, and CAT tools.
    """

    DEFAULT_HEADERS = ["Index", "Offset", "Original", "Translation", "Context"]

    @classmethod
    def export_csv(
        cls,
        filepath: str,
        rows: List[TranslationRow],
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        include_context: bool = True,
        headers: Optional[List[str]] = None,
    ):
        """
        Export rows to a CSV file (uses utf-8-sig by default so Excel opens it with proper encoding).

        Keyword Args:
            delimiter: Column separator (default: ',').
            encoding: Output file encoding (default: 'utf-8-sig').
            include_context: Whether to write the Context column (default: True).
            headers: Custom header row list (overrides default headers).
        """
        out_headers = headers if headers is not None else (
            cls.DEFAULT_HEADERS if include_context else cls.DEFAULT_HEADERS[:4]
        )
        parent_dir = os.path.dirname(filepath)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(filepath, "w", encoding=encoding, newline="") as f:
            writer = csv.writer(f, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(out_headers)
            for r in rows:
                row_data = [r.index, r.offset_hex, r.original, r.translation]
                if include_context:
                    row_data.append(r.context)
                writer.writerow(row_data)

    @classmethod
    def import_csv(
        cls,
        filepath: str,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
        filter_empty: bool = False,
        fallback_to_original: bool = False,
        strip_whitespace: bool = False,
        as_dict: bool = False,
    ) -> Union[List[TranslationRow], Dict[int, str]]:
        """
        Read translation rows from a CSV file.

        Keyword Args:
            delimiter: Column separator (default: ',').
            encoding: Input file encoding (default: 'utf-8-sig').
            filter_empty: Skip entries where translation is empty (default: False).
            fallback_to_original: Use original text if translation cell is blank (default: False).
            strip_whitespace: Strip leading/trailing whitespace from texts (default: False).
            as_dict: Return a Dict[int, str] mapping index to translation instead of List[TranslationRow].
        """
        rows: List[TranslationRow] = []
        dict_result: Dict[int, str] = {}

        with open(filepath, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            for idx, item in enumerate(reader):
                # Flexible header lookup (case-insensitive)
                lower_map = {k.lower().strip(): v for k, v in item.items() if k}
                
                # Offset parsing
                off_val = lower_map.get("offset", "0")
                if isinstance(off_val, str) and off_val.startswith("0x"):
                    offset_int = int(off_val, 16)
                else:
                    offset_int = int(off_val) if off_val else 0

                id_raw = lower_map.get("id", lower_map.get("index", idx))
                try:
                    index_int = int(id_raw)
                except (ValueError, TypeError):
                    index_int = idx

                if "text" in lower_map:
                    original = lower_map["text"]
                    translation = lower_map["text"]
                else:
                    original = lower_map.get("original", "")
                    translation = lower_map.get("translation", "")
                context = lower_map.get("context", "")

                if strip_whitespace:
                    original = original.strip()
                    translation = translation.strip()

                if not translation and fallback_to_original:
                    translation = original

                if filter_empty and not translation and not original:
                    continue

                if as_dict:
                    dict_result[index_int] = translation
                else:
                    rows.append(TranslationRow(
                        index=index_int,
                        offset=offset_int,
                        original=original,
                        translation=translation,
                        context=context
                    ))

        return dict_result if as_dict else rows

    @classmethod
    def export_clean_csv(
        cls,
        filepath: str,
        items: List[Any],
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
    ):
        """Export clean 2-column CSV (ID, Text) without offsets or technical headers."""
        parent_dir = os.path.dirname(filepath)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        with open(filepath, "w", encoding=encoding, newline="") as f:
            writer = csv.writer(f, delimiter=delimiter, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(["ID", "Text"])
            for item in items:
                if isinstance(item, (list, tuple)):
                    writer.writerow([item[0], item[1]])
                elif hasattr(item, "index") and hasattr(item, "original"):
                    text = item.translation if (item.translation and item.translation.strip()) else item.original
                    writer.writerow([item.index, text])

    @classmethod
    def to_id_dict(
        cls,
        filepath: str,
        delimiter: str = ",",
        encoding: str = "utf-8-sig",
    ) -> Dict[int, str]:
        """
        Loads CSV and returns a dictionary of {id: text}.
        Directly supports clean 2-column CSV (ID, Text) where user edits Text in-place.
        """
        rows = cls.import_csv(filepath, delimiter=delimiter, encoding=encoding)
        result = {}
        for r in rows:
            val = r.translation if (r.translation and r.translation.strip()) else r.original
            result[r.index] = val
        return result

    @classmethod
    def to_offset_dict(
        cls,
        filepath: str,
        fallback_to_original: bool = True,
        delimiter: str = ",",
        encoding: str = "utf-8-sig"
    ) -> Dict[int, str]:
        """
        Loads CSV and returns a dictionary of {offset: text_to_use}.
        If translation is empty and fallback_to_original is True, returns original text.
        """
        rows = cls.import_csv(filepath, delimiter=delimiter, encoding=encoding)
        result = {}
        for r in rows:
            if r.translation and r.translation.strip():
                result[r.offset] = r.translation
            elif fallback_to_original:
                result[r.offset] = r.original
            else:
                result[r.offset] = ""
        return result
