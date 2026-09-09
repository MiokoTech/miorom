from miorom.result import MioRomResult
from dataclasses import dataclass
from typing import List, Optional, Union
import struct


@dataclass
class PointerEntry(MioRomResult):
    index: int
    table_offset: int
    target_offset: int
    flags: Optional[int] = None
    base_offset: int = 0

    @property
    def absolute_target(self) -> int:
        return self.base_offset + self.target_offset

    @property
    def relative_target(self) -> int:
        return self.target_offset


class PointerTable:
    """
    Manages ROM / binary pointer tables, supporting absolute, relative,
    flagged (e.g. offset + flags), and segmented pointer tables.
    """

    def __init__(
        self,
        entries: Optional[List[PointerEntry]] = None,
        base_offset: int = 0,
        stride: int = 4,
        has_flags: bool = False,
        endian: str = ">"
    ):
        self.entries: List[PointerEntry] = entries or []
        self.base_offset = base_offset
        self.stride = stride
        self.has_flags = has_flags
        self.endian = endian

    @classmethod
    def read_from(
        cls,
        data: bytes,
        table_offset: int,
        count: int,
        base_offset: int = 0,
        stride: int = 4,
        has_flags: bool = False,
        endian: str = ">"
    ) -> "PointerTable":
        """Read count pointer entries from binary buffer."""
        entries = []
        pos = table_offset
        for i in range(count):
            if has_flags and stride == 8:
                target_off = struct.unpack_from(f"{endian}I", data, pos)[0]
                flag = struct.unpack_from(f"{endian}I", data, pos + 4)[0]
                entries.append(PointerEntry(
                    index=i,
                    table_offset=pos,
                    target_offset=target_off,
                    flags=flag,
                    base_offset=base_offset
                ))
            elif stride == 4:
                target_off = struct.unpack_from(f"{endian}I", data, pos)[0]
                entries.append(PointerEntry(
                    index=i,
                    table_offset=pos,
                    target_offset=target_off,
                    base_offset=base_offset
                ))
            elif stride == 2:
                target_off = struct.unpack_from(f"{endian}H", data, pos)[0]
                entries.append(PointerEntry(
                    index=i,
                    table_offset=pos,
                    target_offset=target_off,
                    base_offset=base_offset
                ))
            pos += stride

        return cls(
            entries=entries,
            base_offset=base_offset,
            stride=stride,
            has_flags=has_flags,
            endian=endian
        )

    def relocate(self, offset_map: dict) -> "PointerTable":
        """
        Relocate target offsets according to an offset_map {old_abs_offset: new_abs_offset}.
        """
        for entry in self.entries:
            old_abs = entry.absolute_target
            if old_abs in offset_map:
                new_abs = offset_map[old_abs]
                entry.target_offset = new_abs - entry.base_offset
        return self

    def build_bytes(self) -> bytes:
        """Serialize pointer table back to bytes."""
        out = bytearray()
        for entry in self.entries:
            if self.has_flags and self.stride == 8:
                flag = entry.flags if entry.flags is not None else 0
                out.extend(struct.pack(f"{self.endian}II", entry.target_offset, flag))
            elif self.stride == 4:
                out.extend(struct.pack(f"{self.endian}I", entry.target_offset))
            elif self.stride == 2:
                out.extend(struct.pack(f"{self.endian}H", entry.target_offset))
        return bytes(out)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __getitem__(self, index: int) -> PointerEntry:
        return self.entries[index]


class SegmentTable:
    """
    Registry of virtual segment base addresses (0x00 to 0x0F in N64, KSEG0 in PS1,
    or SNES LoROM/HiROM bank bases).
    """

    def __init__(self, segments: Optional[dict[int, int]] = None):
        self.segments: dict[int, int] = dict(segments or {})

    def set_segment(self, segment_id: int, base_address: int) -> None:
        self.segments[segment_id] = base_address

    def get_segment(self, segment_id: int) -> int:
        return self.segments.get(segment_id, 0)


class SegmentedAddressResolver:
    """
    Two-way resolver between segmented virtual addresses (e.g. 0x07001234)
    and physical / file offsets.
    """

    def __init__(self, segment_table: Optional[SegmentTable] = None):
        self.segment_table = segment_table or SegmentTable()

    def to_physical(self, segmented_addr: int) -> int:
        segment_id = (segmented_addr >> 24) & 0xFF
        offset = segmented_addr & 0x00FFFFFF
        base = self.segment_table.get_segment(segment_id)
        return base + offset

    def to_segmented(self, physical_addr: int, segment_id: int) -> int:
        base = self.segment_table.get_segment(segment_id)
        offset = physical_addr - base
        return ((segment_id & 0xFF) << 24) | (offset & 0x00FFFFFF)
