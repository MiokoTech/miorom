"""
miorom.text.pipeline
~~~~~~~~~~~~~~~~~~~~
End-to-End String Table Extraction & Auto-Injection Pipeline.
Orchestrates PointerTable dumping, translation file generation (PO/JSON/CSV),
and safe, overflow-aware re-injection with automatic slack relocation and
ROM integrity checksum fixing.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import json
import struct

from miorom.core.pointer import PointerTable, PointerEntry
from miorom.core.integrity import RomIntegrityManager, IntegrityReport
from miorom.text.po_handler import PoHandler, PoEntry
from miorom.patch.relocator import AutoRelocationManager, RelocationSummary, RelocatablePointer
from miorom.text.charmap import CharMap
from miorom.text.dte_miner import DTEMiner


@dataclass
class ExtractedString(MioRomResult):
    """Represents a text string extracted from a binary table."""
    index: int
    offset: int
    raw_bytes: bytes
    decoded_text: str
    length: int


class StringTablePipeline:
    """
    One-stop localization pipeline:
    Dump text from ROM pointer tables -> Translate -> Inject with auto-slack & checksums.
    """

    @classmethod
    def extract_strings(
        cls,
        buffer: bytes,
        table_offset: int,
        entry_count: int,
        charmap: Optional[CharMap] = None,
        encoding: str = "utf-8",
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        is_relative: bool = False,
        stop_byte: bytes = b"\x00",
    ) -> List[ExtractedString]:
        """
        Traverses a pointer table and extracts all referenced strings.
        """
        extracted: List[ExtractedString] = []
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"

        for i in range(entry_count):
            ptr_loc = table_offset + (i * pointer_size)
            if ptr_loc + pointer_size > len(buffer):
                break
            raw_ptr = struct.unpack_from(fmt, buffer, ptr_loc)[0]
            target_off = (base_address + raw_ptr) if is_relative else (raw_ptr - base_address)

            if not (0 <= target_off < len(buffer)):
                continue

            end_pos = buffer.find(stop_byte, target_off)
            if end_pos != -1:
                str_bytes = buffer[target_off:end_pos]
            else:
                str_bytes = buffer[target_off : target_off + 100]

            if charmap is not None:
                text = charmap.decode(str_bytes)
            else:
                text = str_bytes.decode(encoding, errors="replace")

            extracted.append(
                ExtractedString(
                    index=i,
                    offset=target_off,
                    raw_bytes=str_bytes,
                    decoded_text=text,
                    length=len(str_bytes),
                )
            )

        return extracted

    @classmethod
    def dump_to_po(
        cls,
        buffer: bytes,
        table_offset: int,
        entry_count: int,
        output_path: Optional[str] = None,
        charmap: Optional[CharMap] = None,
        encoding: str = "utf-8",
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        is_relative: bool = False,
        stop_byte: bytes = b"\x00",
    ) -> PoHandler:
        """
        Dumps strings into GNU gettext PO format with offset & max length metadata.
        """
        strings = cls.extract_strings(
            buffer=buffer,
            table_offset=table_offset,
            entry_count=entry_count,
            charmap=charmap,
            encoding=encoding,
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            is_relative=is_relative,
            stop_byte=stop_byte,
        )

        handler = PoHandler()
        for item in strings:
            handler.add_entry(
                msgid=item.decoded_text,
                msgstr="",
                msgctxt=f"entry_{item.index:04d}",
                comment=f"Offset: 0x{item.offset:08X}, OrigLen: {item.length}",
            )

        if output_path:
            handler.save(output_path)

        return handler

    @classmethod
    def inject_from_po(
        cls,
        buffer: bytearray,
        po_source: Union[PoHandler, str],
        table_offset: int,
        charmap: Optional[CharMap] = None,
        dte_dict: Optional[Dict[bytes, str]] = None,
        encoding: str = "utf-8",
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        is_relative: bool = False,
        stop_byte: bytes = b"\x00",
        auto_relocate: bool = True,
        auto_fix_integrity: bool = True,
        platform: Optional[str] = None,
    ) -> RelocationSummary:
        """
        Injects translated text from a PO file back into the binary ROM buffer.
        Uses AutoRelocationManager to automatically handle text expansions and
        rewrites pointers. Auto-fixes ROM checksums upon completion.
        """
        if isinstance(po_source, str):
            po_handler = PoHandler.from_file(po_source)
        else:
            po_handler = po_source

        # First inspect existing items
        extracted = cls.extract_strings(
            buffer=buffer,
            table_offset=table_offset,
            entry_count=len(po_handler.entries),
            charmap=charmap,
            encoding=encoding,
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            is_relative=is_relative,
            stop_byte=stop_byte,
        )

        item_sizes = [item.length + len(stop_byte) for item in extracted]
        new_payloads: List[bytes] = []

        for idx, entry in enumerate(po_handler.entries):
            # If translated (msgstr non-empty), use msgstr; else fall back to msgid
            text = entry.msgstr if entry.msgstr else entry.msgid

            # Encode
            if dte_dict:
                encoded = DTEMiner.compress_text(text, dte_dict, base_charmap=charmap)
            elif charmap is not None:
                encoded = charmap.encode(text)
            else:
                encoded = text.encode(encoding)

            new_payloads.append(encoded + stop_byte)

        # Relocate and inject
        relocator = AutoRelocationManager(buffer)
        summary = relocator.relocate_pointer_table(
            table_offset=table_offset,
            entry_count=len(new_payloads),
            item_sizes=item_sizes,
            new_payloads=new_payloads,
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            is_relative=is_relative,
            allow_eof_growth=True,
        )

        # Auto-fix integrity checksums
        if auto_fix_integrity:
            fixed_data, report = RomIntegrityManager.fix(bytes(buffer), platform=platform)
            buffer[:len(fixed_data)] = fixed_data

        return summary
