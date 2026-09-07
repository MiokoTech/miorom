"""
miorom.patch.relocator
~~~~~~~~~~~~~~~~~~~~~~
Automated Text & Asset Relocation Engine with Overflow Spilling.
Manages non-destructive binary insertion: if new payload fits inside the original
boundary, overwrites in-place; if it overflows, carves new space from slack blocks
or expands EOF and rewrites all pointing references (PointerTables, literal pools,
and custom pointer arrays).
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import struct

from miorom.patch.slack import SlackSpaceManager, SlackBlock
from miorom.core.pointer import PointerTable, PointerEntry


@dataclass
class RelocatablePointer:
    """
    Defines a location in the buffer where a pointer value is stored.
    """
    pointer_offset: int             # Location in the buffer where the pointer bytes reside
    pointer_size: int = 4           # 2 or 4 bytes
    endian: str = "<"               # '<' or '>'
    base_address: int = 0           # Address subtracted/added (e.g. RAM base 0x02000000 or file base)
    shift: int = 0                  # Bit shift (e.g. 2 for Thumb word addresses)
    is_relative: bool = False       # If True, pointer value is relative to pointer_offset (or base_address)


@dataclass
class RelocationRecord:
    """Detailed result of a single item relocation."""
    item_id: Any
    old_offset: int
    old_size: int
    new_offset: int
    new_size: int
    overflowed: bool
    pointers_updated: List[int] = field(default_factory=list)


@dataclass
class RelocationSummary:
    """Summary of a batch relocation operation."""
    total_items: int
    in_place_count: int
    relocated_count: int
    bytes_expanded: int
    records: List[RelocationRecord] = field(default_factory=list)

    @property
    def total_overflowed(self) -> int:
        return self.relocated_count


class AutoRelocationManager:
    """
    Automates payload insertion and pointer updating with zero data corruption.
    Automatically decides whether to overwrite in-place or spill over to slack space.
    """

    def __init__(
        self,
        buffer: bytearray,
        slack_manager: Optional[SlackSpaceManager] = None,
        default_filler: int = 0x00,
        alignment: int = 4,
    ):
        self.buffer = buffer
        self.slack_manager = slack_manager or SlackSpaceManager(buffer)
        self.default_filler = default_filler
        self.alignment = alignment

    def read_pointer_value(self, ptr_def: RelocatablePointer) -> int:
        """Decodes raw pointer value from buffer according to its definition."""
        fmt = f"{ptr_def.endian}{'I' if ptr_def.pointer_size == 4 else 'H'}"
        raw_val = struct.unpack_from(fmt, self.buffer, ptr_def.pointer_offset)[0]
        if ptr_def.shift:
            raw_val <<= ptr_def.shift
        if ptr_def.is_relative:
            target_offset = ptr_def.base_address + raw_val
        else:
            target_offset = raw_val - ptr_def.base_address
        return target_offset

    def write_pointer_value(self, ptr_def: RelocatablePointer, new_target_offset: int) -> None:
        """Encodes and writes updated pointer value into the buffer."""
        if ptr_def.is_relative:
            val_to_write = new_target_offset - ptr_def.base_address
        else:
            val_to_write = new_target_offset + ptr_def.base_address
        if ptr_def.shift:
            val_to_write >>= ptr_def.shift

        fmt = f"{ptr_def.endian}{'I' if ptr_def.pointer_size == 4 else 'H'}"
        max_val = (1 << (ptr_def.pointer_size * 8)) - 1
        if not (0 <= val_to_write <= max_val):
            raise OverflowError(
                f"Pointer value 0x{val_to_write:X} exceeds capacity for {ptr_def.pointer_size}-byte pointer at 0x{ptr_def.pointer_offset:X}"
            )
        struct.pack_into(fmt, self.buffer, ptr_def.pointer_offset, val_to_write)

    def relocate_item(
        self,
        item_id: Any,
        old_offset: int,
        old_size: int,
        new_payload: bytes,
        pointers: Sequence[Union[RelocatablePointer, int]] = (),
        default_ptr_size: int = 4,
        default_endian: str = "<",
        default_base_address: int = 0,
        allow_eof_growth: bool = True,
    ) -> RelocationRecord:
        """
        Inserts new_payload for the given item.
        If len(new_payload) <= old_size:
            Overwrites in-place and pads unused remainder.
        If len(new_payload) > old_size:
            Allocates slack space, writes payload, and updates all pointers.
        """
        new_size = len(new_payload)
        pointers_updated: List[int] = []

        # Standardize pointers to RelocatablePointer objects
        resolved_pointers: List[RelocatablePointer] = []
        for p in pointers:
            if isinstance(p, int):
                resolved_pointers.append(
                    RelocatablePointer(
                        pointer_offset=p,
                        pointer_size=default_ptr_size,
                        endian=default_endian,
                        base_address=default_base_address,
                    )
                )
            elif isinstance(p, RelocatablePointer):
                resolved_pointers.append(p)

        if new_size <= old_size:
            # Fit in-place!
            self.buffer[old_offset : old_offset + new_size] = new_payload
            pad_len = old_size - new_size
            if pad_len > 0:
                self.buffer[old_offset + new_size : old_offset + old_size] = bytes([self.default_filler] * pad_len)
            new_offset = old_offset
            overflowed = False
        else:
            # OVERFLOW: Allocate from slack space or EOF
            overflowed = True
            # Reclaim old space by filling with filler byte before allocation
            if old_size > 0:
                self.buffer[old_offset : old_offset + old_size] = bytes([self.default_filler] * old_size)

            new_offset = self.slack_manager.allocate(
                size=new_size,
                alignment=self.alignment,
                allow_eof_growth=allow_eof_growth,
            )
            # Write new payload
            self.buffer[new_offset : new_offset + new_size] = new_payload

            # Update all pointers to the new offset
            for ptr in resolved_pointers:
                self.write_pointer_value(ptr, new_offset)
                pointers_updated.append(ptr.pointer_offset)

        return RelocationRecord(
            item_id=item_id,
            old_offset=old_offset,
            old_size=old_size,
            new_offset=new_offset,
            new_size=new_size,
            overflowed=overflowed,
            pointers_updated=pointers_updated,
        )

    def relocate_pointer_table(
        self,
        table_offset: int,
        entry_count: int,
        item_sizes: Sequence[int],
        new_payloads: Sequence[bytes],
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        is_relative: bool = False,
        allow_eof_growth: bool = True,
    ) -> RelocationSummary:
        """
        Batch-relocates an entire array of items governed by a contiguous pointer table.
        """
        records: List[RelocationRecord] = []
        in_place_count = 0
        relocated_count = 0
        orig_len = len(self.buffer)

        for i in range(entry_count):
            ptr_loc = table_offset + (i * pointer_size)
            ptr_def = RelocatablePointer(
                pointer_offset=ptr_loc,
                pointer_size=pointer_size,
                endian=endian,
                base_address=base_address,
                is_relative=is_relative,
            )
            old_target = self.read_pointer_value(ptr_def)
            old_sz = item_sizes[i] if i < len(item_sizes) else 0
            new_data = new_payloads[i] if i < len(new_payloads) else b""

            rec = self.relocate_item(
                item_id=i,
                old_offset=old_target,
                old_size=old_sz,
                new_payload=new_data,
                pointers=[ptr_def],
                allow_eof_growth=allow_eof_growth,
            )
            records.append(rec)
            if rec.overflowed:
                relocated_count += 1
            else:
                in_place_count += 1

        bytes_expanded = max(0, len(self.buffer) - orig_len)
        return RelocationSummary(
            total_items=entry_count,
            in_place_count=in_place_count,
            relocated_count=relocated_count,
            bytes_expanded=bytes_expanded,
            records=records,
        )
