"""
miorom.patch.pointer_remapper
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Relative Pointer Table & Multi-Pointer Remapper Primitive.
Solves relative offset arithmetic (offsets relative to header or end-of-table)
and handles 1-to-many pointer references when text is relocated into new heaps.
"""
from miorom.errors import RelocationError

from dataclasses import dataclass
import struct
from typing import Dict, List, Optional, Sequence, Tuple, Union


class RelativePointerTable:
    """
    Reader and writer for relative pointer tables.
    Stored value = target_offset - base_offset.
    """

    @classmethod
    def read(
        cls,
        data: bytes,
        table_offset: int,
        count: int,
        base_offset: int,
        pointer_size: int = 4,
        endian: str = "<",
    ) -> List[int]:
        """
        Reads relative pointers and resolves them to absolute offsets within data.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        absolute_targets: List[int] = []

        for i in range(count):
            pos = table_offset + (i * pointer_size)
            rel_val = struct.unpack_from(fmt, data, pos)[0]
            absolute_targets.append(base_offset + rel_val)

        return absolute_targets

    @classmethod
    def write(
        cls,
        buffer: bytearray,
        table_offset: int,
        targets: Sequence[int],
        base_offset: int,
        pointer_size: int = 4,
        endian: str = "<",
    ) -> None:
        """
        Writes absolute targets as relative offsets (target - base_offset) into buffer.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"

        for i, target in enumerate(targets):
            pos = table_offset + (i * pointer_size)
            rel_val = target - base_offset
            if rel_val < 0:
                raise RelocationError(f"Relative pointer cannot be negative: {target} < {base_offset}")
            struct.pack_into(fmt, buffer, pos, rel_val)


class MultiPointerRemapper:
    """
    Maps and rewrites 1-to-many pointer references across binary ROM structures.
    """

    @classmethod
    def scan_references(
        cls,
        buffer: bytes,
        pointer_locations: Sequence[int],
        pointer_size: int = 4,
        endian: str = "<",
    ) -> Dict[int, List[int]]:
        """
        Scans given pointer locations in buffer and builds a map:
        target_offset -> list of pointer_locations that point to it.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        target_map: Dict[int, List[int]] = {}

        for loc in pointer_locations:
            if loc + pointer_size <= len(buffer):
                target = struct.unpack_from(fmt, buffer, loc)[0]
                if target not in target_map:
                    target_map[target] = []
                target_map[target].append(loc)

        return target_map

    @classmethod
    def remap(
        cls,
        buffer: bytearray,
        old_to_new: Dict[int, int],
        ref_map: Dict[int, List[int]],
        pointer_size: int = 4,
        endian: str = "<",
    ) -> int:
        """
        Updates all pointer locations in buffer whose target matches an old_to_new key.
        Returns total number of pointers successfully updated.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        updated_count = 0

        for old_target, new_target in old_to_new.items():
            locations = ref_map.get(old_target, [])
            for loc in locations:
                struct.pack_into(fmt, buffer, loc, new_target)
                updated_count += 1

        return updated_count
