"""
miorom.text.bilingual_bridge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Bilingual Translation Asset Bridge & Round-Trip Catalog Porter.
Standardizes bidirectional translation pipelines between raw binary tables
and localization formats (gettext PO, JSON). Automatically connects with
ControlTagSanitizer for syntax linting and SlotToHeapPointerizer for seamless
arbitrary text expansion.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import json
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.text.po_handler import PoHandler, PoEntry
from miorom.text.sanitizer import ControlTagSanitizer


@dataclass
class BridgeImportReport(MioRomResult):
    """Summary of translation import and binary repack."""
    total_strings: int
    translated_strings: int
    sanitization_warnings: List[str] = field(default_factory=list)
    heap_bytes_written: int = 0
    new_heap_end: int = 0


class BilingualAssetBridge:
    """
    Two-way bridge between binary tables and translation catalogs (PO / JSON).
    """

    @classmethod
    def export_to_po(
        cls,
        strings: Sequence[Union[str, Tuple[int, str]]],
        domain: str = "dialogue",
    ) -> PoHandler:
        """
        Exports a sequence of extracted strings into a standard gettext PO catalog.
        """
        po = PoHandler()
        po.entries = []

        for idx, item in enumerate(strings):
            if isinstance(item, tuple):
                entry_id, text = item
            else:
                entry_id, text = idx, item

            entry = PoEntry(
                msgid=text,
                msgstr="",
                msgctxt=f"{domain}:{entry_id:04d}",
                comments=[f"Entry ID: {entry_id}"],
            )
            po.entries.append(entry)

        return po

    @classmethod
    def export_to_json(
        cls,
        records: List[Dict[str, Any]],
        indent: int = 2,
    ) -> str:
        """
        Exports structured records (e.g. ID, name, description) to JSON.
        """
        return json.dumps(records, indent=indent, ensure_ascii=False)

    @classmethod
    def import_and_repack_table(
        cls,
        buffer: bytearray,
        po: PoHandler,
        table_offset: int,
        record_count: int,
        pointer_size: int = 4,
        heap_start_offset: int = 0,
        endian: str = "<",
        sanitize_tags: bool = True,
    ) -> Tuple[bytearray, BridgeImportReport]:
        """
        Imports translated strings from PO catalog, sanitizes tags, packs them into heap,
        and rewrites table pointers in buffer.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        cur_heap = heap_start_offset
        warnings: List[str] = []
        translated_cnt = 0

        for i in range(min(record_count, len(po.entries))):
            entry = po.entries[i]
            # Use msgstr if translated, otherwise keep original msgid
            raw_text = entry.msgstr if entry.msgstr else entry.msgid
            if entry.msgstr:
                translated_cnt += 1

            # Validate and sanitize tags
            text_to_write = raw_text
            if sanitize_tags:
                val_res = ControlTagSanitizer.validate_translation(entry.msgid, raw_text)
                if not val_res.is_valid:
                    warnings.append(
                        f"Entry {i} validation error: missing={val_res.missing_tags}, syntax={val_res.syntax_errors}"
                    )
                text_to_write = ControlTagSanitizer.sanitize(raw_text)

            payload = text_to_write.encode("utf-8") + b"\x00"

            # Write string to heap
            heap_need = cur_heap + len(payload)
            if heap_need > len(buffer):
                buffer.extend(b"\x00" * (heap_need - len(buffer)))

            buffer[cur_heap : cur_heap + len(payload)] = payload

            # Write pointer to table
            ptr_pos = table_offset + (i * pointer_size)
            struct.pack_into(fmt, buffer, ptr_pos, cur_heap)

            cur_heap += len(payload)

        report = BridgeImportReport(
            total_strings=record_count,
            translated_strings=translated_cnt,
            sanitization_warnings=warnings,
            heap_bytes_written=cur_heap - heap_start_offset,
            new_heap_end=cur_heap,
        )

        return buffer, report
