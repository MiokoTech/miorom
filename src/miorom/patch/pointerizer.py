"""
miorom.patch.pointerizer
~~~~~~~~~~~~~~~~~~~~~~~~
Fixed-Slot to Dynamic Heap Pointerizer & Pascal String Manager.
Eliminates character limits on fixed-width item names, menus, and spell tables
by converting inline fixed slots into dynamic heap pointers, allowing arbitrary
text expansion without corrupting adjacent record attributes.
"""
from miorom.result import MioRomResult
from miorom.errors import PatchError

from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.patch.relocator import AutoRelocationManager
from miorom.patch.slack import SlackSpaceManager
from miorom.text.charmap import CharMap


@dataclass
class PointerizedSlot(MioRomResult):
    """Represents a converted record slot."""
    record_index: int
    slot_offset: int
    original_text: str
    translated_text: str
    new_heap_address: int


@dataclass
class SlotConversionReport(MioRomResult):
    """Report on fixed-slot to heap pointer conversion."""
    total_records: int
    slot_size: int
    heap_start_offset: int
    heap_total_bytes: int
    slots: List[PointerizedSlot] = field(default_factory=list)


class SlotToHeapPointerizer:
    """
    Transforms fixed-width tables (char[N]) into flexible indirect pointer tables.
    """

    @classmethod
    def extract_fixed_slots(
        cls,
        buffer: bytes,
        table_offset: int,
        record_count: int,
        record_stride: int,
        slot_offset_in_record: int,
        slot_size: int,
        encoding: str = "utf-8",
        charmap: Optional[CharMap] = None,
        stop_byte: bytes = b"\x00",
    ) -> List[Tuple[int, str]]:
        """
        Extracts strings from fixed-width slots within a structured table.
        Returns list of (record_index, text).
        """
        results: List[Tuple[int, str]] = []
        for i in range(record_count):
            off = table_offset + (i * record_stride) + slot_offset_in_record
            raw = buffer[off : off + slot_size]
            stop_idx = raw.find(stop_byte)
            valid_bytes = raw[:stop_idx] if stop_idx != -1 else raw

            if charmap is not None:
                text = charmap.decode(valid_bytes)
            else:
                text = valid_bytes.decode(encoding, errors="replace")

            results.append((i, text))
        return results

    @classmethod
    def pointerize_table(
        cls,
        buffer: bytearray,
        table_offset: int,
        record_count: int,
        record_stride: int,
        slot_offset_in_record: int,
        slot_size: int,
        translations: Dict[int, str],
        heap_offset: Optional[int] = None,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        encoding: str = "utf-8",
        charmap: Optional[CharMap] = None,
        stop_byte: bytes = b"\x00",
    ) -> SlotConversionReport:
        """
        Writes expanded translations to the heap, and rewrites the fixed slots
        to contain pointers to the new heap addresses.
        """
        # Determine heap start (default: append to end of buffer)
        cur_heap = heap_offset if heap_offset is not None else len(buffer)
        slots: List[PointerizedSlot] = []

        ptr_fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        heap_start = cur_heap

        for i in range(record_count):
            slot_off = table_offset + (i * record_stride) + slot_offset_in_record
            # Read original text for reporting
            raw_orig = buffer[slot_off : slot_off + slot_size]
            s_idx = raw_orig.find(stop_byte)
            orig_text = raw_orig[:s_idx].decode(encoding, errors="replace") if s_idx != -1 else ""

            trans_text = translations.get(i, orig_text)

            # Encode translated string
            if charmap is not None:
                encoded = charmap.encode(trans_text) + stop_byte
            else:
                encoded = trans_text.encode(encoding) + stop_byte

            # Ensure buffer has enough space for heap
            target_heap_addr = cur_heap
            if cur_heap + len(encoded) > len(buffer):
                buffer.extend(b"\x00" * (cur_heap + len(encoded) - len(buffer)))

            # Write string to heap
            buffer[cur_heap : cur_heap + len(encoded)] = encoded

            # Write pointer into record slot
            calc_ptr = (base_address + target_heap_addr)
            struct.pack_into(ptr_fmt, buffer, slot_off, calc_ptr)

            # Zero-pad remaining slot bytes
            if slot_size > pointer_size:
                buffer[slot_off + pointer_size : slot_off + slot_size] = b"\x00" * (slot_size - pointer_size)

            slots.append(
                PointerizedSlot(
                    record_index=i,
                    slot_offset=slot_off,
                    original_text=orig_text,
                    translated_text=trans_text,
                    new_heap_address=target_heap_addr,
                )
            )

            cur_heap += len(encoded)

        return SlotConversionReport(
            total_records=record_count,
            slot_size=slot_size,
            heap_start_offset=heap_start,
            heap_total_bytes=cur_heap - heap_start,
            slots=slots,
        )


class PascalStringManager:
    """
    Manages length-prefixed strings ([uint8/uint16 length] [data]).
    Automatically updates the length prefix byte when strings are lengthened.
    """

    @classmethod
    def read_pascal_string(
        cls,
        buffer: bytes,
        offset: int,
        length_size: int = 1,
        endian: str = "<",
        encoding: str = "utf-8",
    ) -> Tuple[str, int]:
        """Reads a length-prefixed string. Returns (text, total_bytes_consumed)."""
        if length_size == 1:
            length = buffer[offset]
        else:
            length = struct.unpack_from(f"{endian}H", buffer, offset)[0]

        data = buffer[offset + length_size : offset + length_size + length]
        return data.decode(encoding, errors="replace"), length_size + length

    @classmethod
    def write_pascal_string(
        cls,
        buffer: bytearray,
        offset: int,
        text: str,
        length_size: int = 1,
        endian: str = "<",
        encoding: str = "utf-8",
    ) -> int:
        """Writes length prefix and string payload. Returns total bytes written."""
        encoded = text.encode(encoding)
        str_len = len(encoded)

        if length_size == 1:
            if str_len > 255:
                raise PatchError(f"String exceeds 1-byte Pascal length limit ({str_len} > 255)")
            buffer[offset] = str_len
        else:
            struct.pack_into(f"{endian}H", buffer, offset, str_len)

        buffer[offset + length_size : offset + length_size + str_len] = encoded
        return length_size + str_len
