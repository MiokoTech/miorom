from miorom.result import MioRomResult
import os
from miorom.errors import ParseError
from dataclasses import dataclass
from miorom.core.schema import BinaryStruct, RawBytes, U32, U8, U16
from typing import List, Dict, Optional, Tuple

from miorom.compression import decompress
from miorom.security import sanitize_extract_path


class Yaz0HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)
    uncompressed_size = U32()


@dataclass
class U8Entry(MioRomResult):
    index: int
    name: str
    path: str
    is_dir: bool
    data_offset: int
    size: int
    parent_index: int = 0

class U8HeaderStruct(BinaryStruct):
    _endian = ">"
    magic = RawBytes(4)
    root_node_offset = U32()
    header_size = U32()
    data_offset = U32()
    _reserved_0x10 = RawBytes(16)

class U8NodeStruct(BinaryStruct):
    _endian = ">"
    kind = U8()
    name_high = U8()
    name_low = U16()
    value1 = U32()
    value2 = U32()


class U8Archive:
    """
    Nintendo U8 Archive (.arc / .szs) extractor and packer.
    Standard archive container for Nintendo Wii and GameCube games.
    """

    MAGIC = 0x55AA382D  # b"U\xAA8-"

    @classmethod
    def is_u8(cls, data: bytes) -> bool:
        if len(data) < 4:
            return False
        return data[:4] == b"\x55\xAA\x38\x2D"

    @classmethod
    def extract_all(cls, archive_path: str, output_dir: str) -> List[str]:
        """
        Extracts all files from a U8 archive file to the destination directory.
        Automatically handles LZ11 or Yaz0 compressed archives if encountered.
        """
        with open(archive_path, "rb") as f:
            data = f.read()

        # Handle compression if present
        if not cls.is_u8(data):
            # Check for LZ11 (0x11)
            if data[0] == 0x11:
                data = decompress(data)
            elif data[:4] == b"Yaz0":
                # Basic Yaz0 decompressor
                data = cls._decompress_yaz0(data)

        if not cls.is_u8(data):
            raise ParseError(f"File '{archive_path}' is not a valid Nintendo U8 archive.")

        entries, file_data_map = cls._parse_archive(data)
        os.makedirs(output_dir, exist_ok=True)
        extracted_paths: List[str] = []

        # Create directories first
        for entry in entries:
            dest_path = sanitize_extract_path(output_dir, entry.path)
            if entry.is_dir:
                os.makedirs(dest_path, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                file_bytes = file_data_map.get(entry.index, b"")
                with open(dest_path, "wb") as f_out:
                    f_out.write(file_bytes)
                extracted_paths.append(dest_path)

        return extracted_paths

    @classmethod
    def list_files(cls, archive_path: str) -> List[U8Entry]:
        """Lists all entries contained inside a U8 archive."""
        with open(archive_path, "rb") as f:
            data = f.read()

        if not cls.is_u8(data) and data[0] == 0x11:
            data = decompress(data)

        if not cls.is_u8(data):
            raise ParseError(f"File '{archive_path}' is not a valid Nintendo U8 archive.")

        entries, _ = cls._parse_archive(data, read_data=False)
        return entries

    @classmethod
    def _parse_archive(cls, data: bytes, read_data: bool = True) -> Tuple[List[U8Entry], Dict[int, bytes]]:
        archive_header = U8HeaderStruct.from_bytes(data, offset=0)
        root_node_offset = archive_header.root_node_offset
        header_size = archive_header.header_size
        data_offset = archive_header.data_offset

        root_node = U8NodeStruct.from_bytes(data, offset=root_node_offset)
        total_nodes = root_node.value2
        root_total_nodes = total_nodes

        string_pool_offset = root_node_offset + (root_total_nodes * 12)

        def get_string(name_offset: int) -> str:
            pos = string_pool_offset + name_offset
            null_pos = data.find(b"\x00", pos)
            if null_pos == -1:
                null_pos = len(data)
            return data[pos:null_pos].decode("latin1", errors="replace")

        entries: List[U8Entry] = []
        dir_stack: List[Tuple[int, str, int]] = [(0, "", root_total_nodes)]  # (index, path, end_node)
        file_data_map: Dict[int, bytes] = {}

        for i in range(root_total_nodes):
            node_offset = root_node_offset + (i * 12)
            node = U8NodeStruct.from_bytes(data, offset=node_offset)
            type_byte = node.kind
            name_hi = node.name_high
            name_lo = node.name_low
            val1 = node.value1
            val2 = node.value2

            is_dir = (type_byte == 1)
            name_offset = (name_hi << 16) | name_lo
            name = get_string(name_offset) if i > 0 else ""

            # Pop directories from stack if we moved past their scope
            while dir_stack and i >= dir_stack[-1][2]:
                dir_stack.pop()

            parent_path = dir_stack[-1][1] if dir_stack else ""
            curr_path = os.path.join(parent_path, name) if parent_path and name else name

            if is_dir:
                parent_idx = val1
                end_node = val2
                dir_stack.append((i, curr_path, end_node))
                if i > 0:
                    entries.append(U8Entry(
                        index=i,
                        name=name,
                        path=curr_path,
                        is_dir=True,
                        data_offset=0,
                        size=0,
                        parent_index=parent_idx
                    ))
            else:
                f_offset = val1
                f_size = val2
                entries.append(U8Entry(
                    index=i,
                    name=name,
                    path=curr_path,
                    is_dir=False,
                    data_offset=f_offset,
                    size=f_size,
                    parent_index=dir_stack[-1][0] if dir_stack else 0
                ))
                if read_data:
                    file_data_map[i] = data[f_offset:f_offset + f_size]

        return entries, file_data_map

    @classmethod
    def pack(cls, input_dir: str, output_archive_path: str) -> None:
        """
        Packs a folder into a standard Nintendo U8 archive (.arc).
        Ensures 32-byte data alignment according to Nintendo Wii SDK standards.
        """
        if not os.path.isdir(input_dir):
            raise ParseError(f"Input path '{input_dir}' is not a directory.")

        # Build node tree via preorder traversal
        nodes_info = []  # dict of entry attributes
        string_pool = bytearray(b"\x00")  # root name is empty string at 0

        # Collect files and directory structure
        # Helper recursive builder
        node_index_counter = 0

        def build_dir_nodes(current_dir: str, parent_index: int):
            nonlocal node_index_counter
            dir_node_idx = node_index_counter
            node_index_counter += 1

            # Get directory contents sorted alphabetically
            entries = sorted(os.listdir(current_dir))
            dirs = [e for e in entries if os.path.isdir(os.path.join(current_dir, e))]
            files = [e for e in entries if os.path.isfile(os.path.join(current_dir, e))]

            dir_entry = {
                "index": dir_node_idx,
                "is_dir": True,
                "name": os.path.basename(current_dir) if dir_node_idx > 0 else "",
                "parent_index": parent_index,
                "end_index": 0,  # will set after children
                "file_path": None
            }
            nodes_info.append(dir_entry)

            # Process subdirectories
            for d in dirs:
                build_dir_nodes(os.path.join(current_dir, d), dir_node_idx)

            # Process files
            for f in files:
                file_idx = node_index_counter
                node_index_counter += 1
                f_path = os.path.join(current_dir, f)
                nodes_info.append({
                    "index": file_idx,
                    "is_dir": False,
                    "name": f,
                    "parent_index": dir_node_idx,
                    "file_path": f_path,
                    "size": os.path.getsize(f_path)
                })

            dir_entry["end_index"] = node_index_counter

        build_dir_nodes(input_dir, 0)
        total_nodes = len(nodes_info)

        # Build string pool and record offsets
        for node in nodes_info:
            if node["index"] == 0:
                node["name_offset"] = 0
            else:
                name_bytes = node["name"].encode("latin1") + b"\x00"
                node["name_offset"] = len(string_pool)
                string_pool.extend(name_bytes)

        # Align section offsets
        root_node_offset = 0x20
        nodes_size = total_nodes * 12
        header_size = nodes_size + len(string_pool)
        data_offset = (root_node_offset + header_size + 31) & ~31

        # Calculate file offsets
        curr_file_offset = data_offset
        file_payloads = []
        for node in nodes_info:
            if not node["is_dir"]:
                node["data_offset"] = curr_file_offset
                with open(node["file_path"], "rb") as f_in:
                    content = f_in.read()
                file_payloads.append((curr_file_offset, content))
                # 32-byte align for next file
                curr_file_offset = (curr_file_offset + len(content) + 31) & ~31

        # Build archive binary
        out = bytearray()
        archive_header = U8HeaderStruct(
            magic=b"\x55\xAA\x38\x2D",
            root_node_offset=root_node_offset,
            header_size=header_size,
            data_offset=data_offset,
        )
        out.extend(archive_header.to_bytes())

        # Write nodes (12 bytes each)
        for node in nodes_info:
            type_byte = 1 if node["is_dir"] else 0
            name_hi = (node["name_offset"] >> 16) & 0xFF
            name_lo = node["name_offset"] & 0xFFFF

            if node["is_dir"]:
                val1 = node["parent_index"]
                val2 = node["end_index"]
            else:
                val1 = node["data_offset"]
                val2 = node["size"]

            out.extend(U8NodeStruct(
                kind=type_byte,
                name_high=name_hi,
                name_low=name_lo,
                value1=val1,
                value2=val2,
            ).to_bytes())

        # Write string pool
        out.extend(string_pool)

        # Pad to data_offset
        while len(out) < data_offset:
            out.append(0)

        # Write file data
        for offset, content in file_payloads:
            while len(out) < offset:
                out.append(0)
            out.extend(content)

        # Pad total archive to 32 bytes
        while len(out) % 32 != 0:
            out.append(0)

        with open(output_archive_path, "wb") as f_out:
            f_out.write(out)

    @classmethod
    def _decompress_yaz0(cls, data: bytes) -> bytes:
        """Decompress Nintendo Yaz0 compressed stream."""
        if len(data) < Yaz0HeaderStruct.sizeof():
            raise ParseError("Invalid Yaz0 header")
        header = Yaz0HeaderStruct.from_bytes(data, offset=0)
        if header.magic != b"Yaz0":
            raise ParseError("Invalid Yaz0 header")

        uncompressed_size = header.uncompressed_size
        out = bytearray()
        in_pos = 16
        data_len = len(data)

        while len(out) < uncompressed_size and in_pos < data_len:
            flags = data[in_pos]
            in_pos += 1

            for bit in range(7, -1, -1):
                if len(out) >= uncompressed_size or in_pos >= data_len:
                    break

                if (flags >> bit) & 1:
                    out.append(data[in_pos])
                    in_pos += 1
                else:
                    if in_pos + 1 >= data_len:
                        break
                    b1 = data[in_pos]
                    b2 = data[in_pos + 1]
                    in_pos += 2

                    disp = (((b1 & 0x0F) << 8) | b2) + 1
                    count = b1 >> 4

                    if count == 0:
                        if in_pos >= data_len:
                            break
                        count = data[in_pos] + 0x12
                        in_pos += 1
                    else:
                        count += 2

                    copy_pos = len(out) - disp
                    for _ in range(count):
                        out.append(out[copy_pos])
                        copy_pos += 1
                        if len(out) >= uncompressed_size:
                            break

        return bytes(out)
