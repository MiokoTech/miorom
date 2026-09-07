import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class TableLevel:
    """
    Defines a single level in a cascading pointer table hierarchy.
    """
    level_index: int
    stride: int = 4  # 4 bytes for 32-bit pointers, 2 for 16-bit
    base_ram: int = 0
    endian: str = ">"
    count: Optional[int] = None


class MultiLevelPointerTable:
    """
    Multi-Level Pointer Table Dereference Tracker.
    Traverses and manipulates hierarchical cascading pointer tables
    (e.g., Chapter Table -> Event Table -> Message Table -> Dialogue String).
    """

    def __init__(self, root_offset: int, levels: List[TableLevel], ram_base: int = 0):
        self.root_offset = root_offset
        self.levels = levels
        self.ram_base = ram_base

    def resolve_path(self, data: bytes, indices: List[int]) -> int:
        """
        Follow an index path (e.g. [chapter_idx, event_idx, message_idx])
        down the cascading levels and return the final resolved leaf offset.
        """
        if len(indices) != len(self.levels):
            raise ValueError(
                f"Index path length {len(indices)} does not match table levels {len(self.levels)}"
            )

        cur_table_offset = self.root_offset

        for lvl_idx, (idx, lvl) in enumerate(zip(indices, self.levels)):
            fmt = f"{lvl.endian}{'I' if lvl.stride == 4 else 'H'}"
            entry_file_offset = cur_table_offset + idx * lvl.stride

            if entry_file_offset + lvl.stride > len(data):
                raise ValueError(
                    f"Level {lvl_idx} entry offset 0x{entry_file_offset:08X} is out of bounds."
                )

            pointer_val = struct.unpack_from(fmt, data, entry_file_offset)[0]

            # Convert pointer to file offset
            if lvl.base_ram != 0:
                cur_table_offset = pointer_val - lvl.base_ram
            elif self.ram_base != 0:
                cur_table_offset = pointer_val - self.ram_base
            else:
                cur_table_offset = pointer_val

        return cur_table_offset

    def read_leaf_string(
        self,
        data: bytes,
        indices: List[int],
        encoding: str = "ascii",
    ) -> str:
        """
        Dereference path down to leaf string and decode until null byte.
        """
        leaf_offset = self.resolve_path(data, indices)
        if leaf_offset >= len(data):
            return ""

        end = data.find(b"\x00", leaf_offset)
        if end == -1:
            end = len(data)
        raw_str = data[leaf_offset:end]
        return raw_str.decode(encoding, errors="replace")

    def update_leaf_pointer(
        self,
        data: bytearray,
        indices: List[int],
        new_target_offset: int,
    ):
        """
        Update the pointer at the final level for the given index path.
        """
        if len(indices) != len(self.levels):
            raise ValueError(f"Path length mismatch: {len(indices)} vs {len(self.levels)}")

        cur_table_offset = self.root_offset

        # Traverse down to parent of leaf
        for lvl_idx in range(len(indices) - 1):
            idx = indices[lvl_idx]
            lvl = self.levels[lvl_idx]
            fmt = f"{lvl.endian}{'I' if lvl.stride == 4 else 'H'}"
            entry_file_offset = cur_table_offset + idx * lvl.stride
            pointer_val = struct.unpack_from(fmt, data, entry_file_offset)[0]

            if lvl.base_ram != 0:
                cur_table_offset = pointer_val - lvl.base_ram
            elif self.ram_base != 0:
                cur_table_offset = pointer_val - self.ram_base
            else:
                cur_table_offset = pointer_val

        # Update leaf entry
        last_idx = indices[-1]
        last_lvl = self.levels[-1]
        fmt = f"{last_lvl.endian}{'I' if last_lvl.stride == 4 else 'H'}"
        target_entry_offset = cur_table_offset + last_idx * last_lvl.stride

        target_val = new_target_offset
        if last_lvl.base_ram != 0:
            target_val += last_lvl.base_ram
        elif self.ram_base != 0:
            target_val += self.ram_base

        struct.pack_into(fmt, data, target_entry_offset, target_val)
