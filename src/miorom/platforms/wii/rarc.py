"""
miorom.platforms.wii.rarc
~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo RARC Archive (.arc, .rarc) Parser and Builder.
Standard resource archive container used extensively in Nintendo GameCube and Wii games
(e.g., The Legend of Zelda: The Wind Waker, Super Mario Sunshine, Twilight Princess).
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import struct
from typing import Dict, List, Optional, Tuple

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.result import MioRomResult
from miorom.security import sanitize_extract_path


def rarc_hash(name: str) -> int:
    """Computes Nintendo RARC 16-bit filename hash."""
    h = 0
    for char in name:
        h = ((h * 3) + ord(char)) & 0xFFFF
    return h


@dataclass
class RARCEntry(MioRomResult):
    """An individual file or directory entry inside a RARC archive."""
    name: str
    path: str
    is_dir: bool = False
    data: bytes = b""


class RARCHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)  # b"RARC"
    file_size = U32()
    header_size = U32()  # 0x0020
    data_offset = U32()  # Relative to file start
    data_size = U32()
    mram_size = U32()
    aram_size = U32()
    dvd_size = U32()


class RARCDirInfoStruct(BinaryStruct):
    _endian = ">"
    node_count = U32()
    node_offset = U32()  # 0x0020 relative to dir info
    entry_count = U32()
    entry_offset = U32()
    string_table_size = U32()
    string_table_offset = U32()
    file_entry_count = U16()
    _pad = U16()
    _reserved = U32()


class RARCArchive:
    """
    Nintendo RARC archive reader and builder.
    Hierarchical file container supporting nested directories and 32-byte data alignment.
    """

    MAGIC = b"RARC"

    def __init__(self, entries: Optional[List[RARCEntry]] = None):
        self.entries = list(entries or [])

    @classmethod
    def is_rarc(cls, data: bytes) -> bool:
        return len(data) >= 4 and data[:4] == cls.MAGIC

    @classmethod
    def from_bytes(cls, data: bytes) -> "RARCArchive":
        if len(data) < 0x40:
            raise ParseError("Data too small for RARC header.")

        if data[:4] != cls.MAGIC:
            raise ParseError(f"Invalid RARC magic: {data[:4]!r}")

        header = RARCHeaderStruct.from_bytes(data, offset=0)
        dir_info_offset = header.header_size
        dir_info = RARCDirInfoStruct.from_bytes(data, offset=dir_info_offset)

        node_base = dir_info_offset + dir_info.node_offset
        entry_base = dir_info_offset + dir_info.entry_offset
        str_base = dir_info_offset + dir_info.string_table_offset
        file_data_base = header.data_offset

        # Helper to read null-terminated string from string table
        def read_str(offset: int) -> str:
            pos = str_base + offset
            end = data.find(b"\x00", pos)
            if end == -1:
                end = len(data)
            return data[pos:end].decode("ascii", errors="replace")

        # Read nodes
        nodes = []
        reader = BinaryReader(data, endian=">")
        for i in range(dir_info.node_count):
            pos = node_base + i * 16
            reader.seek(pos)
            n_type = reader.read_bytes(4)
            name_off = reader.read_u32()
            name_h = reader.read_u16()
            e_cnt = reader.read_u16()
            first_idx = reader.read_u32()
            name = read_str(name_off)
            nodes.append({
                "type": n_type,
                "name": name,
                "entry_count": e_cnt,
                "first_index": first_idx,
            })

        # Read entries
        entries: List[RARCEntry] = []

        def traverse_node(node_idx: int, parent_path: str):
            if node_idx >= len(nodes):
                return
            node = nodes[node_idx]
            first_idx = node["first_index"]
            count = node["entry_count"]

            for e_i in range(count):
                idx = first_idx + e_i
                e_pos = entry_base + idx * 20
                if e_pos + 20 > len(data):
                    break
                reader.seek(e_pos)
                _id = reader.read_u16()
                _hash = reader.read_u16()
                e_type = reader.read_u16()
                e_name_off = reader.read_u16()
                d_offset = reader.read_u32()
                d_size = reader.read_u32()
                _res = reader.read_u32()

                entry_name = read_str(e_name_off)
                if entry_name in (".", ".."):
                    continue

                full_path = f"{parent_path}/{entry_name}" if parent_path else entry_name
                is_dir = bool(e_type & 0x0200)

                if is_dir:
                    subnode_idx = d_offset
                    entries.append(RARCEntry(name=entry_name, path=full_path, is_dir=True, data=b""))
                    traverse_node(subnode_idx, full_path)
                else:
                    abs_data_off = file_data_base + d_offset
                    file_bytes = data[abs_data_off : abs_data_off + d_size]
                    entries.append(RARCEntry(name=entry_name, path=full_path, is_dir=False, data=file_bytes))

        traverse_node(0, "")
        return cls(entries=entries)

    def get_file(self, path: str) -> Optional[bytes]:
        norm = path.strip("/").replace("\\", "/")
        for e in self.entries:
            if not e.is_dir and e.path.strip("/").replace("\\", "/") == norm:
                return e.data
        return None

    def add_file(self, path: str, data: bytes):
        norm = path.strip("/").replace("\\", "/")
        name = os.path.basename(norm)
        for i, e in enumerate(self.entries):
            if not e.is_dir and e.path.strip("/").replace("\\", "/") == norm:
                self.entries[i] = RARCEntry(name=name, path=norm, is_dir=False, data=data)
                return
        self.entries.append(RARCEntry(name=name, path=norm, is_dir=False, data=data))

    @classmethod
    def extract_all(cls, archive_path: str, output_dir: str) -> List[str]:
        """Extracts all files in a RARC archive to output_dir with path traversal protection."""
        with open(archive_path, "rb") as f:
            rarc = cls.from_bytes(f.read())

        extracted: List[str] = []
        for entry in rarc.entries:
            safe_target = sanitize_extract_path(output_dir, entry.path)
            if entry.is_dir:
                os.makedirs(safe_target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(safe_target), exist_ok=True)
                with open(safe_target, "wb") as out_f:
                    out_f.write(entry.data)
                extracted.append(safe_target)
        return extracted

    def to_bytes(self) -> bytes:
        """Serializes entries into a standards-compliant Nintendo RARC binary archive."""
        # Simple flat/hierarchical layout builder with 32-byte alignment
        files = [e for e in self.entries if not e.is_dir]

        # String table
        str_table = bytearray(b".\x00..\x00ROOT\x00")
        name_offsets: Dict[str, int] = {".": 0, "..": 2, "ROOT": 5}

        for f in files:
            if f.name not in name_offsets:
                name_offsets[f.name] = len(str_table)
                str_table.extend(f.name.encode("ascii", errors="replace") + b"\x00")

        # Pad string table to 4 bytes
        pad_str = (4 - (len(str_table) % 4)) % 4
        if pad_str:
            str_table.extend(b"\x00" * pad_str)

        # File data pool (32-byte aligned)
        data_pool = bytearray()
        file_offsets: List[Tuple[int, int]] = []
        for f in files:
            align = (32 - (len(data_pool) % 32)) % 32
            if align:
                data_pool.extend(b"\x00" * align)
            cur_off = len(data_pool)
            data_pool.extend(f.data)
            file_offsets.append((cur_off, len(f.data)))

        # Node table (1 root node)
        node_count = 1
        entry_count = 2 + len(files)  # . and .. plus all files
        first_entry_index = 0

        node_bytes = bytearray()
        node_bytes.extend(b"ROOT")
        node_bytes.extend(struct.pack(">IHH I", name_offsets["ROOT"], rarc_hash("ROOT"), entry_count, 0))

        # Entries table
        # 0: . (directory)
        # 1: .. (directory)
        entries_bytes = bytearray()
        # Entry 0: .
        entries_bytes.extend(struct.pack(">HH HHI II", 0, rarc_hash("."), 0x0200, name_offsets["."], 0, 16, 0))
        # Entry 1: ..
        entries_bytes.extend(struct.pack(">HH HHI II", 1, rarc_hash(".."), 0x0200, name_offsets[".."], 0xFFFFFFFF, 16, 0))

        # File entries
        for i, f in enumerate(files):
            d_off, d_len = file_offsets[i]
            n_off = name_offsets[f.name]
            entries_bytes.extend(
                struct.pack(">HH HHI II", 2 + i, rarc_hash(f.name), 0x1100, n_off, d_off, d_len, 0)
            )

        # Build Directory Information
        dir_info_size = 0x20
        node_table_offset = dir_info_size
        entry_table_offset = node_table_offset + len(node_bytes)
        string_table_offset = entry_table_offset + len(entries_bytes)

        dir_info_header = bytearray()
        dir_info_header.extend(
            struct.pack(
                ">IIII II HHI",
                node_count,
                node_table_offset,
                entry_count,
                entry_table_offset,
                len(str_table),
                string_table_offset,
                len(files),
                0,  # pad
                0,  # reserved
            )
        )

        dir_info_full = bytearray()
        dir_info_full.extend(dir_info_header)
        dir_info_full.extend(node_bytes)
        dir_info_full.extend(entries_bytes)
        dir_info_full.extend(str_table)

        header_size = 0x20
        total_meta_size = header_size + len(dir_info_full)
        data_align_pad = (32 - (total_meta_size % 32)) % 32
        data_offset = total_meta_size + data_align_pad
        total_file_size = data_offset + len(data_pool)

        # RARC Main Header
        header = bytearray(self.MAGIC)
        header.extend(
            struct.pack(
                ">IIII III",
                total_file_size,
                header_size,
                data_offset,
                len(data_pool),
                0,  # mram
                0,  # aram
                0,  # dvd
            )
        )

        out = bytearray()
        out.extend(header)
        out.extend(dir_info_full)
        if data_align_pad:
            out.extend(b"\x00" * data_align_pad)
        out.extend(data_pool)

        return bytes(out)
