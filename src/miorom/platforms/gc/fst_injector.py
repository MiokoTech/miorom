"""
miorom.platforms.gc.fst_injector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Native GameCube / Wii File System Table (FST) Parser and Injector.
Enables reading, extracting, and repacking files directly inside disc images
without relying on external tools (like wit / gcit / Wiimms).
"""

import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class FstNode:
    index: int
    is_dir: bool
    name: str
    offset: int  # For files: byte offset or sector*4
    size: int    # For files: byte size; For dirs: next dir index


class FstInjector:
    """
    Parser and modifier for Nintendo GameCube / Wii File System Tables (FST).
    """

    ENTRY_SIZE = 12

    def __init__(self, fst_data: bytearray, fst_offset: int = 0):
        self.fst_data = fst_data
        self.fst_offset = fst_offset
        self.nodes: List[FstNode] = self._parse()

    def _parse(self) -> List[FstNode]:
        nodes: List[FstNode] = []
        if len(self.fst_data) < self.ENTRY_SIZE:
            return nodes

        # Root entry
        num_entries = struct.unpack_from(">I", self.fst_data, 8)[0]
        string_table_start = num_entries * self.ENTRY_SIZE

        for i in range(num_entries):
            e_off = i * self.ENTRY_SIZE
            type_and_name = struct.unpack_from(">I", self.fst_data, e_off)[0]
            is_dir = (type_and_name >> 24) != 0
            name_off = type_and_name & 0x00FFFFFF

            # Read name from string table
            name = ""
            if i > 0 and string_table_start + name_off < len(self.fst_data):
                p = string_table_start + name_off
                end = self.fst_data.find(b"\x00", p)
                if end != -1:
                    name = self.fst_data[p:end].decode("ascii", errors="replace")

            offset = struct.unpack_from(">I", self.fst_data, e_off + 4)[0]
            size = struct.unpack_from(">I", self.fst_data, e_off + 8)[0]

            nodes.append(FstNode(index=i, is_dir=is_dir, name=name, offset=offset, size=size))

        return nodes

    def find_by_name(self, filename: str) -> Optional[FstNode]:
        """Find a file entry by its exact filename."""
        for node in self.nodes:
            if not node.is_dir and node.name.lower() == filename.lower():
                return node
        return None

    def update_entry(self, index: int, new_offset: int, new_size: int) -> None:
        """Update the offset and size of a file entry in the FST."""
        if index < 0 or index >= len(self.nodes):
            raise IndexError(f"FST index {index} out of range.")
        node = self.nodes[index]
        node.offset = new_offset
        node.size = new_size

        e_off = index * self.ENTRY_SIZE
        struct.pack_into(">II", self.fst_data, e_off + 4, new_offset, new_size)

    def to_bytes(self) -> bytes:
        return bytes(self.fst_data)
