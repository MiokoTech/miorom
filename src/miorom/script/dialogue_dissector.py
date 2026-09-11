"""
miorom.script.dialogue_dissector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated dialogue script and pointer table dissector for fan translation reverse engineering.
Automatically discovers pointer tables, resolves console base address mappings, extracts dialogue
into industry-standard GNU gettext (.po) and bilingual JSON formats, and seamlessly reinjects
expanded translations with automated free-space relocation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from miorom.errors import ParseError, RelocationError
from miorom.result import MioRomResult
from miorom.scanner.table_detector import HeuristicTableDetector, TableCandidate
from miorom.script.boundary_detector import detect_delimiters
from miorom.text.charmap import CharMap
from miorom.text.po_handler import PoEntry, PoHandler
from miorom.text.pointer_relinker import PointerRelinker


@dataclass
class DialogueEntry(MioRomResult):
    """
    A single extracted dialogue unit with binary location and decoded text.
    """
    index: int
    pointer_offset: int
    target_offset: int
    length: int
    raw_bytes: bytes
    text: str
    control_codes: List[str] = field(default_factory=list)


@dataclass
class DialogueBlock(MioRomResult):
    """
    A cluster of dialogue strings indexed by a common pointer table.
    """
    block_id: str
    table_offset: int
    pointer_count: int
    pointer_size: int
    endian: str
    base_address: int
    terminator: bytes
    entries: List[DialogueEntry] = field(default_factory=list)

    def to_po(self) -> str:
        """
        Exports this dialogue block to GNU gettext PO format.
        """
        po = PoHandler()
        po.headers["Project-Id-Version"] = f"MioROM Dialogue Dissector - {self.block_id}"
        for entry in self.entries:
            po.add_entry(
                msgid=entry.text,
                msgstr="",
                msgctxt=f"{self.block_id}:{entry.index}",
                comment=f"Entry Index: #{entry.index} | Target: 0x{entry.target_offset:08X} | Pointer: 0x{entry.pointer_offset:08X} | Bytes: {entry.length}",
            )
        return po.to_string()

    def to_json(self, indent: int = 2) -> str:
        """
        Exports this dialogue block to structured JSON format.
        """
        data = {
            "block_id": self.block_id,
            "table_offset": f"0x{self.table_offset:08X}",
            "pointer_count": self.pointer_count,
            "pointer_size": self.pointer_size,
            "endian": self.endian,
            "base_address": f"0x{self.base_address:08X}",
            "terminator_hex": self.terminator.hex().upper(),
            "entries": [
                {
                    "index": e.index,
                    "pointer_offset": f"0x{e.pointer_offset:08X}",
                    "target_offset": f"0x{e.target_offset:08X}",
                    "length": e.length,
                    "text": e.text,
                    "raw_hex": e.raw_bytes.hex(),
                }
                for e in self.entries
            ],
        }
        return json.dumps(data, indent=indent, ensure_ascii=False)


@dataclass
class DissectionPatchReport(MioRomResult):
    """
    Summary report produced after injecting translated dialogue into ROM.
    """
    total_entries: int
    modified_entries: int
    relocated_entries: int
    bytes_relocated: int
    pointer_updates: List[Tuple[int, int, int]] = field(default_factory=list)  # (ptr_off, old_target, new_target)
    warnings: List[str] = field(default_factory=list)


class DialogueDissector:
    """
    Automated binary dialogue dissector and translation reinjection engine.
    """

    DEFAULT_BASE_ADDRESSES = (
        0,           # Flat file / relative offsets
        0x08000000,  # Game Boy Advance ROM bus
        0x80000000,  # Sony PlayStation 1 KSEG0
        0x80010000,  # Sony PlayStation 1 Main Executable base
    )

    @classmethod
    def auto_discover(
        cls,
        data: bytes,
        encoding: str = "shift_jis",
        charmap: Optional[CharMap] = None,
        min_entries: int = 4,
        pointer_sizes: Sequence[int] = (2, 4),
        endians: Sequence[str] = ("<", ">"),
        base_addresses: Optional[Sequence[int]] = None,
    ) -> List[DialogueBlock]:
        """
        Scans a ROM or binary blob for pointer tables and extracts all discovered dialogue blocks.
        """
        bases = base_addresses or cls.DEFAULT_BASE_ADDRESSES
        discovered_blocks: List[DialogueBlock] = []
        visited_tables: Set[int] = set()

        for ptr_size in pointer_sizes:
            for endian in endians:
                for base in bases:
                    candidates = HeuristicTableDetector.detect_pointer_tables(
                        data=data,
                        min_entries=min_entries,
                        pointer_size=ptr_size,
                        endian=endian,
                        base_address=base,
                        encoding=encoding if charmap is None else None,
                    )

                    for cand in candidates:
                        # Deduplicate nearby or identical tables
                        if any(abs(cand.offset - v) < (min_entries * ptr_size) for v in visited_tables):
                            continue
                        visited_tables.add(cand.offset)

                        block = cls.extract_from_table(
                            data=data,
                            table_offset=cand.offset,
                            pointer_count=cand.count,
                            pointer_size=ptr_size,
                            endian=endian,
                            base_address=base,
                            encoding=encoding,
                            charmap=charmap,
                            block_id=f"table_{cand.offset:06X}",
                        )
                        if len(block.entries) >= min_entries:
                            discovered_blocks.append(block)

        return discovered_blocks

    @classmethod
    def extract_from_table(
        cls,
        data: bytes,
        table_offset: int,
        pointer_count: int,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        terminator: Optional[bytes] = None,
        encoding: str = "shift_jis",
        charmap: Optional[CharMap] = None,
        block_id: str = "block_0",
        control_codes: Optional[Dict[bytes, str]] = None,
    ) -> DialogueBlock:
        """
        Extracts a dialogue block from a specific known pointer table location.
        """
        if pointer_size not in (2, 3, 4):
            raise ValueError(f"Unsupported pointer_size: {pointer_size}")
        endian_flag = "little" if endian == "<" else "big"
        relinker = PointerRelinker(pointer_size=pointer_size, endian=endian_flag, base_address=base_address)

        raw_targets: List[int] = []
        entries: List[DialogueEntry] = []
        data_len = len(data)

        # 1. Read pointers and determine target offsets
        for i in range(pointer_count):
            p_off = table_offset + i * pointer_size
            if p_off + pointer_size > data_len:
                break
            ptr_val = relinker.read_pointer(data, p_off)
            t_off = ptr_val - base_address
            if 0 <= t_off < data_len:
                raw_targets.append(t_off)
            else:
                raw_targets.append(-1)

        valid_targets = [t for t in raw_targets if t != -1]
        if not valid_targets:
            return DialogueBlock(
                block_id=block_id,
                table_offset=table_offset,
                pointer_count=pointer_count,
                pointer_size=pointer_size,
                endian=endian,
                base_address=base_address,
                terminator=terminator or b"\x00",
                entries=[],
            )

        # 2. Determine terminator delimiter if not specified
        primary_term = terminator
        if primary_term is None:
            delims = detect_delimiters(data, valid_targets, max_delimiter_len=2)
            primary_term = delims[0].byte_sequence if delims else b"\x00"

        term_len = len(primary_term)

        # 3. Read strings from target offsets
        for i, t_off in enumerate(raw_targets):
            p_off = table_offset + i * pointer_size
            if t_off == -1:
                continue

            # Read until terminator or EOF or next pointer
            curr = t_off
            while curr + term_len <= data_len:
                if data[curr : curr + term_len] == primary_term:
                    curr += term_len
                    break
                curr += 1

            raw_chunk = data[t_off:curr]
            text_bytes = raw_chunk[:-term_len] if raw_chunk.endswith(primary_term) else raw_chunk

            # Decode text
            if charmap is not None:
                decoded_text = charmap.decode(text_bytes)
            else:
                decoded_text = text_bytes.decode(encoding, errors="replace")

            # Detect control codes if provided
            found_cc: List[str] = []
            if control_codes:
                for code_bytes, tag in control_codes.items():
                    if code_bytes in text_bytes:
                        found_cc.append(tag)

            entries.append(
                DialogueEntry(
                    index=i,
                    pointer_offset=p_off,
                    target_offset=t_off,
                    length=len(raw_chunk),
                    raw_bytes=raw_chunk,
                    text=decoded_text,
                    control_codes=found_cc,
                )
            )

        return DialogueBlock(
            block_id=block_id,
            table_offset=table_offset,
            pointer_count=len(entries),
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            terminator=primary_term,
            entries=entries,
        )

    @classmethod
    def inject_translations(
        cls,
        data: bytearray,
        block: DialogueBlock,
        translations: Union[Dict[int, str], PoFile, str],
        charmap: Optional[CharMap] = None,
        encoding: str = "shift_jis",
        free_space_ranges: Optional[List[Tuple[int, int]]] = None,
    ) -> DissectionPatchReport:
        """
        Injects translated dialogue into the ROM buffer.
        Performs in-place replacement when possible; automatically relocates overflow strings
        and updates pointer table entries if free_space_ranges is supplied.
        """
        # Normalize translation map {index: translated_text}
        trans_map: Dict[int, str] = {}
        if isinstance(translations, dict):
            trans_map = translations
        elif isinstance(translations, PoHandler):
            for entry in translations.entries:
                if entry.msgstr and entry.msgctxt:
                    # Expect msgctxt "block_id:index"
                    parts = entry.msgctxt.split(":")
                    if len(parts) >= 2 and parts[-1].isdigit():
                        trans_map[int(parts[-1])] = entry.msgstr
        elif isinstance(translations, str):
            po = PoHandler.from_string(translations)
            for entry in po.entries:
                if entry.msgstr and entry.msgctxt:
                    parts = entry.msgctxt.split(":")
                    if len(parts) >= 2 and parts[-1].isdigit():
                        trans_map[int(parts[-1])] = entry.msgstr

        endian_flag = "little" if block.endian == "<" else "big"
        relinker = PointerRelinker(
            pointer_size=block.pointer_size,
            endian=endian_flag,
            base_address=block.base_address,
        )

        free_pools = [list(r) for r in (free_space_ranges or [])]
        modified_count = 0
        relocated_count = 0
        bytes_relocated = 0
        pointer_updates: List[Tuple[int, int, int]] = []
        warnings: List[str] = []

        for entry in block.entries:
            if entry.index not in trans_map:
                continue

            new_text = trans_map[entry.index]
            # Encode string
            if charmap is not None:
                encoded_body = charmap.encode(new_text)
            else:
                encoded_body = new_text.encode(encoding, errors="replace")

            new_raw = encoded_body + block.terminator
            new_len = len(new_raw)

            if new_len <= entry.length:
                # In-place overwrite
                data[entry.target_offset : entry.target_offset + new_len] = new_raw
                # Zero-pad remaining space if smaller
                if new_len < entry.length:
                    data[entry.target_offset + new_len : entry.target_offset + entry.length] = (
                        b"\x00" * (entry.length - new_len)
                    )
                modified_count += 1
            else:
                # Overflow: Requires relocation
                allocated_off = None
                for pool in free_pools:
                    p_start, p_end = pool[0], pool[1]
                    avail = p_end - p_start
                    if avail >= new_len:
                        allocated_off = p_start
                        pool[0] += new_len
                        break

                if allocated_off is None:
                    warnings.append(
                        f"Entry #{entry.index} overflow ({new_len} > {entry.length} bytes) and no free space available."
                    )
                    continue

                # Write to free space
                data[allocated_off : allocated_off + new_len] = new_raw

                # Update pointer table
                new_ptr_val = allocated_off + block.base_address
                relinker.write_pointer(data, entry.pointer_offset, new_ptr_val)

                pointer_updates.append((entry.pointer_offset, entry.target_offset, allocated_off))
                modified_count += 1
                relocated_count += 1
                bytes_relocated += new_len

        return DissectionPatchReport(
            total_entries=len(block.entries),
            modified_entries=modified_count,
            relocated_entries=relocated_count,
            bytes_relocated=bytes_relocated,
            pointer_updates=pointer_updates,
            warnings=warnings,
        )
