"""
miorom.core.heap_builder
~~~~~~~~~~~~~~~~~~~~~~~~
Modular String Heap & Buffer Allocator Primitive.
Packs sequences or dictionaries of strings/bytes into an aligned binary heap,
calculating individual offsets, padding, and null-termination cleanly for ROM insertion.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


@dataclass
class HeapBuildResult:
    """Result of binary heap compilation."""
    data: bytes
    offsets: List[int]
    offset_map: Dict[Any, int]
    total_size: int
    padding_bytes: int


class StringHeapBuilder:
    """
    Pure modular primitive to compile string collections into aligned binary heaps.
    """

    @classmethod
    def align_up(cls, value: int, alignment: int) -> int:
        if alignment <= 1:
            return value
        rem = value % alignment
        return value if rem == 0 else value + (alignment - rem)

    @classmethod
    def build(
        cls,
        items: Union[Sequence[Union[str, bytes]], Dict[Any, Union[str, bytes]]],
        encoding: str = "utf-8",
        alignment: int = 4,
        null_terminated: bool = True,
        start_offset: int = 0,
    ) -> HeapBuildResult:
        """
        Packs strings or raw bytes into a contiguous binary heap.
        Returns the compiled bytes, list of offsets, and key-to-offset map.
        """
        buf = bytearray()
        offsets: List[int] = []
        offset_map: Dict[Any, int] = {}
        cur_offset = start_offset
        padding_total = 0

        # Normalize items into a list of (key, value)
        if isinstance(items, dict):
            entries = list(items.items())
        else:
            entries = [(idx, val) for idx, val in enumerate(items)]

        for key, val in entries:
            # Align offset
            aligned_off = cls.align_up(cur_offset, alignment)
            pad_len = aligned_off - cur_offset
            if pad_len > 0:
                buf.extend(b"\x00" * pad_len)
                padding_total += pad_len
                cur_offset = aligned_off

            offsets.append(cur_offset)
            offset_map[key] = cur_offset

            # Encode payload
            if isinstance(val, str):
                payload = val.encode(encoding)
            else:
                payload = bytes(val)

            buf.extend(payload)
            cur_offset += len(payload)

            if null_terminated:
                # Add appropriate null terminator: 2 bytes for utf-16, 1 byte otherwise
                term = b"\x00\x00" if "16" in encoding.lower() else b"\x00"
                buf.extend(term)
                cur_offset += len(term)

        return HeapBuildResult(
            data=bytes(buf),
            offsets=offsets,
            offset_map=offset_map,
            total_size=len(buf),
            padding_bytes=padding_total,
        )
