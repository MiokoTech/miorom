"""
miorom.platforms.wii.u8
~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii & GameCube U8 Archive and Wii WAD Package Engine.

U8 archives (.arc / .szs) are the standard hierarchical asset containers used across
Nintendo GameCube and Wii titles (e.g., Super Mario Galaxy, The Legend of Zelda: Twilight Princess,
Mario Kart Wii, Super Smash Bros. Brawl), supporting nested directories, Yaz0/LZ11 compression,
and in-memory mutable filesystem manipulation.

WAD files are installable title package containers for the Nintendo Wii OS (WiiWare,
Virtual Console, Channels, DLC, and System Updates), bundling Tickets, Title Metadata (TMD),
certificates, and AES-128-CBC encrypted .app contents with Trucha Bug fake-signing support
and direct in-memory U8Archive bridging.
"""

import hashlib
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.compression import decompress
from miorom.core import schema
from miorom.core.schema import U8, U16, U32, BinaryStruct, RawBytes
from miorom.errors import ParseError
from miorom.result import MioRomResult
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

    def __init__(self, files: Optional[Dict[str, bytes]] = None):
        self.files: Dict[str, bytes] = dict(files) if files else {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "U8Archive":
        """Parses a U8 archive binary buffer into an in-memory U8Archive object."""
        if not cls.is_u8(data):
            if data and data[0] == 0x11:
                data = decompress(data)
            elif data[:4] == b"Yaz0":
                data = cls._decompress_yaz0(data)
        if not cls.is_u8(data):
            raise ParseError("Buffer is not a valid Nintendo U8 archive.")
        files = cls.extract_dict(data)
        return cls(files)

    @classmethod
    def from_file(cls, path: str) -> "U8Archive":
        """Reads a U8 archive file from disk into an in-memory U8Archive object."""
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def to_bytes(self) -> bytes:
        """Serializes all in-memory files into a valid U8 binary archive."""
        return self.pack_dict(self.files)

    def save(self, path: str) -> None:
        """Saves this in-memory U8 archive directly to a file on disk."""
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def __getitem__(self, path: str) -> bytes:
        norm = path.lstrip("/")
        return self.files[norm]

    def __setitem__(self, path: str, content: bytes) -> None:
        norm = path.lstrip("/")
        self.files[norm] = bytes(content)

    def __contains__(self, path: str) -> bool:
        norm = path.lstrip("/")
        return norm in self.files

    def __len__(self) -> int:
        return len(self.files)

    def keys(self):
        return self.files.keys()

    def values(self):
        return self.files.values()

    def items(self):
        return self.files.items()

    def get(self, path: str, default: Optional[bytes] = None) -> Optional[bytes]:
        norm = path.lstrip("/")
        return self.files.get(norm, default)

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
        _header_size = archive_header.header_size
        _data_offset = archive_header.data_offset

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
    def extract_dict(cls, data: bytes) -> Dict[str, bytes]:
        """
        Extracts all files from an in-memory U8 archive (.arc / .szs) into a dict of {relative_path: bytes}.
        Automatically decompresses Yaz0 or LZ11 if present.
        Zero disk I/O.
        """
        if not cls.is_u8(data):
            if data[:4] == b"Yaz0":
                data = cls._decompress_yaz0(data)
            elif len(data) > 0 and data[0] == 0x11:
                data = decompress(data)

        if not cls.is_u8(data):
            raise ParseError("Data is not a valid Nintendo U8 archive.")

        entries, file_data_map = cls._parse_archive(data, read_data=True)
        result: Dict[str, bytes] = {}
        for entry in entries:
            if not entry.is_dir:
                result[entry.path.replace("\\", "/")] = file_data_map.get(entry.index, b"")
        return result

    @classmethod
    def pack_dict(
        cls,
        files_dict: Dict[str, bytes],
        exclude_extensions: Optional[List[str]] = None,
    ) -> bytes:
        """
        Packs an in-memory dictionary of {relative_path: bytes} into a standard Nintendo U8 archive (.arc).
        Ensures 32-byte data alignment according to Nintendo Wii SDK standards.
        Zero disk I/O.
        """
        filtered: Dict[str, bytes] = {}
        for path, data in files_dict.items():
            norm_path = path.replace("\\", "/").strip("/")
            if exclude_extensions and any(norm_path.lower().endswith(ext.lower()) for ext in exclude_extensions):
                continue
            filtered[norm_path] = data

        tree: Dict[str, Any] = {"is_dir": True, "children": {}}
        for path, data in sorted(filtered.items()):
            parts = path.split("/")
            curr = tree
            for p in parts[:-1]:
                if p not in curr["children"]:
                    curr["children"][p] = {"is_dir": True, "children": {}}
                curr = curr["children"][p]
            curr["children"][parts[-1]] = {"is_dir": False, "data": data}

        nodes_info = []
        string_pool = bytearray(b"\x00")
        node_index_counter = 0

        def traverse_tree(name: str, node: Dict[str, Any], parent_idx: int):
            nonlocal node_index_counter
            my_idx = node_index_counter
            node_index_counter += 1

            info = {
                "index": my_idx,
                "is_dir": node["is_dir"],
                "name": name if my_idx > 0 else "",
                "parent_index": parent_idx,
                "end_index": 0,
                "data": node.get("data", b""),
                "size": len(node.get("data", b"")),
            }
            nodes_info.append(info)

            if node["is_dir"]:
                sorted_keys = sorted(node["children"].keys())
                dirs = [k for k in sorted_keys if node["children"][k]["is_dir"]]
                files = [k for k in sorted_keys if not node["children"][k]["is_dir"]]
                for d in dirs:
                    traverse_tree(d, node["children"][d], my_idx)
                for f in files:
                    traverse_tree(f, node["children"][f], my_idx)
                info["end_index"] = node_index_counter

        traverse_tree("", tree, 0)
        total_nodes = len(nodes_info)

        for node in nodes_info:
            if node["index"] == 0:
                node["name_offset"] = 0
            else:
                name_bytes = node["name"].encode("latin1") + b"\x00"
                node["name_offset"] = len(string_pool)
                string_pool.extend(name_bytes)

        root_node_offset = 0x20
        nodes_size = total_nodes * 12
        header_size = nodes_size + len(string_pool)
        data_offset = (root_node_offset + header_size + 31) & ~31

        curr_file_offset = data_offset
        file_payloads = []
        for node in nodes_info:
            if not node["is_dir"]:
                node["data_offset"] = curr_file_offset
                payload = node["data"]
                file_payloads.append((curr_file_offset, payload))
                curr_file_offset = (curr_file_offset + len(payload) + 31) & ~31

        out = bytearray()
        archive_header = U8HeaderStruct(
            magic=b"\x55\xAA\x38\x2D",
            root_node_offset=root_node_offset,
            header_size=header_size,
            data_offset=data_offset,
        )
        out.extend(archive_header.to_bytes())

        for node in nodes_info:
            type_byte = 1 if node["is_dir"] else 0
            name_hi = (node["name_offset"] >> 16) & 0xFF
            name_lo = node["name_offset"] & 0xFFFF
            val1 = node["parent_index"] if node["is_dir"] else node["data_offset"]
            val2 = node["end_index"] if node["is_dir"] else node["size"]

            out.extend(U8NodeStruct(
                kind=type_byte,
                name_high=name_hi,
                name_low=name_lo,
                value1=val1,
                value2=val2,
            ).to_bytes())

        out.extend(string_pool)

        while len(out) < data_offset:
            out.append(0)

        for offset, content in file_payloads:
            while len(out) < offset:
                out.append(0)
            out.extend(content)

        while len(out) % 32 != 0:
            out.append(0)

        return bytes(out)

    @classmethod
    def pack(
        cls,
        input_dir: str,
        output_archive_path: str,
        exclude_extensions: Optional[List[str]] = None,
    ) -> None:
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
            if exclude_extensions:
                files = [
                    e
                    for e in files
                    if not any(e.lower().endswith(ext.lower()) for ext in exclude_extensions)
                ]

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


# AES-128-CBC Cipher
# ==============================================================================

_AES_SBOX = (
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
)

_AES_INV_SBOX = [0] * 256
for _idx, _val in enumerate(_AES_SBOX):
    _AES_INV_SBOX[_val] = _idx
_AES_INV_SBOX = tuple(_AES_INV_SBOX)

_AES_RCON = (0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36)


def _aes_xtimes(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if (a & 0x80) else (a << 1)


def _aes_mul(a: int, b: int) -> int:
    res = 0
    for _ in range(8):
        if b & 1:
            res ^= a
        hi = a & 0x80
        a = ((a << 1) ^ 0x1B) & 0xFF if hi else (a << 1)
        b >>= 1
    return res


def _aes_key_expansion(key: bytes) -> List[List[int]]:
    w = list(key)
    for i in range(4, 44):
        temp = w[(i - 1) * 4 : i * 4]
        if i % 4 == 0:
            temp = temp[1:] + temp[:1]
            temp = [_AES_SBOX[b] for b in temp]
            temp[0] ^= _AES_RCON[(i // 4) - 1]
        prev = w[(i - 4) * 4 : (i - 3) * 4]
        w.extend([p ^ t for p, t in zip(prev, temp)])
    return [w[i * 16 : (i + 1) * 16] for i in range(11)]


def _aes_encrypt_block(block: bytes, rkeys: List[List[int]]) -> bytes:
    s = list(block)
    s = [a ^ b for a, b in zip(s, rkeys[0])]
    for r in range(1, 10):
        s = [_AES_SBOX[b] for b in s]
        s = [
            s[0], s[5], s[10], s[15],
            s[4], s[9], s[14], s[3],
            s[8], s[13], s[2], s[7],
            s[12], s[1], s[6], s[11],
        ]
        ns = [0] * 16
        for c in range(4):
            c0, c1, c2, c3 = s[c * 4 : c * 4 + 4]
            ns[c * 4] = _aes_xtimes(c0 ^ c1) ^ c1 ^ c2 ^ c3
            ns[c * 4 + 1] = _aes_xtimes(c1 ^ c2) ^ c2 ^ c3 ^ c0
            ns[c * 4 + 2] = _aes_xtimes(c2 ^ c3) ^ c3 ^ c0 ^ c1
            ns[c * 4 + 3] = _aes_xtimes(c3 ^ c0) ^ c0 ^ c1 ^ c2
        s = [a ^ b for a, b in zip(ns, rkeys[r])]

    s = [_AES_SBOX[b] for b in s]
    s = [
        s[0], s[5], s[10], s[15],
        s[4], s[9], s[14], s[3],
        s[8], s[13], s[2], s[7],
        s[12], s[1], s[6], s[11],
    ]
    s = [a ^ b for a, b in zip(s, rkeys[10])]
    return bytes(s)


def _aes_decrypt_block(block: bytes, rkeys: List[List[int]]) -> bytes:
    s = list(block)
    s = [a ^ b for a, b in zip(s, rkeys[10])]
    for r in range(9, 0, -1):
        s = [
            s[0], s[13], s[10], s[7],
            s[4], s[1], s[14], s[11],
            s[8], s[5], s[2], s[15],
            s[12], s[9], s[6], s[3],
        ]
        s = [_AES_INV_SBOX[b] for b in s]
        s = [a ^ b for a, b in zip(s, rkeys[r])]
        ns = [0] * 16
        for c in range(4):
            c0, c1, c2, c3 = s[c * 4 : c * 4 + 4]
            ns[c * 4] = _aes_mul(c0, 14) ^ _aes_mul(c1, 11) ^ _aes_mul(c2, 13) ^ _aes_mul(c3, 9)
            ns[c * 4 + 1] = _aes_mul(c0, 9) ^ _aes_mul(c1, 14) ^ _aes_mul(c2, 11) ^ _aes_mul(c3, 13)
            ns[c * 4 + 2] = _aes_mul(c0, 13) ^ _aes_mul(c1, 9) ^ _aes_mul(c2, 14) ^ _aes_mul(c3, 11)
            ns[c * 4 + 3] = _aes_mul(c0, 11) ^ _aes_mul(c1, 13) ^ _aes_mul(c2, 9) ^ _aes_mul(c3, 14)
        s = ns

    s = [
        s[0], s[13], s[10], s[7],
        s[4], s[1], s[14], s[11],
        s[8], s[5], s[2], s[15],
        s[12], s[9], s[6], s[3],
    ]
    s = [_AES_INV_SBOX[b] for b in s]
    s = [a ^ b for a, b in zip(s, rkeys[0])]
    return bytes(s)


def aes128_cbc_encrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """
    Encrypts data using AES-128 in CBC mode (100% zero external dependencies).
    Auto-pads data to a multiple of 16 bytes with zero padding if needed.
    """
    if len(key) != 16:
        raise ValueError("AES-128 key must be exactly 16 bytes.")
    if len(iv) != 16:
        raise ValueError("AES-128 IV must be exactly 16 bytes.")

    pad_len = (16 - (len(data) % 16)) % 16
    padded = data + (b"\x00" * pad_len)

    rkeys = _aes_key_expansion(key)
    out = bytearray()
    prev = iv

    for i in range(0, len(padded), 16):
        block = padded[i : i + 16]
        xored = bytes([b ^ p for b, p in zip(block, prev)])
        enc = _aes_encrypt_block(xored, rkeys)
        out.extend(enc)
        prev = enc

    return bytes(out)


def aes128_cbc_decrypt(data: bytes, key: bytes, iv: bytes) -> bytes:
    """
    Decrypts data using AES-128 in CBC mode (100% zero external dependencies).
    """
    if len(key) != 16:
        raise ValueError("AES-128 key must be exactly 16 bytes.")
    if len(iv) != 16:
        raise ValueError("AES-128 IV must be exactly 16 bytes.")
    if len(data) % 16 != 0:
        raise ValueError("Data length must be a multiple of 16 for AES-CBC.")

    rkeys = _aes_key_expansion(key)
    out = bytearray()
    prev = iv

    for i in range(0, len(data), 16):
        block = data[i : i + 16]
        dec = _aes_decrypt_block(block, rkeys)
        plain = bytes([b ^ p for b, p in zip(dec, prev)])
        out.extend(plain)
        prev = block

    return bytes(out)

@dataclass
class WADContentRecord(MioRomResult):
    """Represents a single content entry (.app) record in a Wii Title Metadata (TMD)."""

    content_id: int
    index: int
    content_type: int
    size: int
    sha1_hash: bytes


class WADTicket(MioRomResult):
    """
    Nintendo Wii Ticket parser, serializer, and Title Key cryptor.
    """

    TICKET_SIZE_V0 = 0x2A4

    def __init__(
        self,
        raw_data: bytes,
        title_id: bytes,
        common_key_index: int,
        encrypted_title_key: bytes,
        console_id: int = 0,
    ):
        self.raw_data = bytearray(raw_data)
        self.title_id = title_id
        self.common_key_index = common_key_index
        self.encrypted_title_key = encrypted_title_key
        self.console_id = console_id

    @classmethod
    def from_bytes(cls, data: bytes) -> "WADTicket":
        if len(data) < cls.TICKET_SIZE_V0:
            raise ParseError(f"Ticket too small: {len(data)} bytes (minimum 0x2A4).")

        title_id = data[0x1CB:0x1D3]
        console_id = schema.unpack_from(">I", data, 0x1C7)[0]
        common_key_index = data[0x1DF]
        enc_key = data[0x1F0:0x200]

        return cls(
            raw_data=data,
            title_id=title_id,
            common_key_index=common_key_index,
            encrypted_title_key=enc_key,
            console_id=console_id,
        )

    def decrypt_title_key(self, common_key: bytes) -> bytes:
        """
        Decrypts the AES-128 Title Key using the user-provided Wii Common Key.
        IV is Title ID (8 bytes) padded with 8 zero bytes.
        """
        iv = self.title_id + (b"\x00" * 8)
        return aes128_cbc_decrypt(self.encrypted_title_key, common_key, iv)

    def encrypt_title_key(self, title_key: bytes, common_key: bytes) -> None:
        """
        Encrypts a new Title Key with Common Key and updates the ticket payload in-place.
        """
        iv = self.title_id + (b"\x00" * 8)
        enc = aes128_cbc_encrypt(title_key, common_key, iv)
        self.encrypted_title_key = enc
        if len(self.raw_data) >= 0x200:
            self.raw_data[0x1F0:0x200] = enc

    def to_bytes(self, fake_sign: bool = True) -> bytes:
        out = bytearray(self.raw_data)
        if fake_sign and len(out) >= 0x140:
            schema.pack_into(">I", out, 0, 0x10001)  # RSA-2048
            out[4:260] = b"\x00" * 256  # Null signature (Trucha Bug)
        return bytes(out)


class WADTmd(MioRomResult):
    """
    Nintendo Wii Title Metadata (TMD) parser, serializer, and content hash manager.
    """

    def __init__(
        self,
        raw_data: bytes,
        title_id: bytes,
        title_version: int,
        boot_index: int,
        contents: List[WADContentRecord],
    ):
        self.raw_data = bytearray(raw_data)
        self.title_id = title_id
        self.title_version = title_version
        self.boot_index = boot_index
        self.contents = contents

    @classmethod
    def from_bytes(cls, data: bytes) -> "WADTmd":
        if len(data) < 0x1E4:
            raise ParseError("Data too small for TMD header (minimum 0x1E4 bytes).")

        title_id = data[0x18C:0x194]
        title_version = schema.unpack_from(">H", data, 0x1DC)[0]
        num_contents = schema.unpack_from(">H", data, 0x1DE)[0]
        boot_index = schema.unpack_from(">H", data, 0x1E0)[0]

        contents: List[WADContentRecord] = []
        rec_offset = 0x1E4

        for _ in range(num_contents):
            if rec_offset + 36 > len(data):
                break
            cid, idx, ctype, csize = schema.unpack_from(">IHHQ", data, rec_offset)
            sha1 = data[rec_offset + 16 : rec_offset + 36]
            contents.append(
                WADContentRecord(
                    content_id=cid,
                    index=idx,
                    content_type=ctype,
                    size=csize,
                    sha1_hash=sha1,
                )
            )
            rec_offset += 36

        return cls(
            raw_data=data,
            title_id=title_id,
            title_version=title_version,
            boot_index=boot_index,
            contents=contents,
        )

    def update_content(self, index: int, decrypted_data: bytes) -> None:
        """
        Updates size and SHA-1 hash of specified content index in TMD.
        """
        for i, rec in enumerate(self.contents):
            if rec.index == index:
                rec.size = len(decrypted_data)
                rec.sha1_hash = hashlib.sha1(decrypted_data).digest()
                rec_off = 0x1E4 + i * 36
                if rec_off + 36 <= len(self.raw_data):
                    schema.pack_into(">Q", self.raw_data, rec_off + 8, rec.size)
                    self.raw_data[rec_off + 16 : rec_off + 36] = rec.sha1_hash
                return
        raise KeyError(f"Content index {index} not found in TMD.")

    def to_bytes(self, fake_sign: bool = True) -> bytes:
        out = bytearray(self.raw_data)
        if fake_sign and len(out) >= 0x140:
            schema.pack_into(">I", out, 0, 0x10001)  # RSA-2048
            out[4:260] = b"\x00" * 256  # Null signature (Trucha Bug)
        return bytes(out)


class WADFile(MioRomResult):
    """
    Parser, builder, and extractor for Nintendo Wii WAD installable packages
    (WiiWare, Virtual Console, Channels, System Updates, and DLCs).

    Directly integrates with `U8Archive` to provide seamless in-memory inspection
    and modification of WiiWare game filesystem contents.
    """

    def __init__(
        self,
        wad_type: str = "Is",
        wad_version: int = 0,
        certs: bytes = b"",
        crl: bytes = b"",
        ticket: Optional[WADTicket] = None,
        tmd: Optional[WADTmd] = None,
        raw_contents: Optional[Dict[int, bytes]] = None,
        decrypted_contents: Optional[Dict[int, bytes]] = None,
        title_key: Optional[bytes] = None,
        footer: bytes = b"",
    ):
        self.wad_type = wad_type
        self.wad_version = wad_version
        self.certs = bytes(certs)
        self.crl = bytes(crl)
        self.ticket = ticket
        self.tmd = tmd
        self.raw_contents: Dict[int, bytes] = dict(raw_contents) if raw_contents else {}
        self.decrypted_contents: Dict[int, bytes] = dict(decrypted_contents) if decrypted_contents else {}
        self.title_key = title_key
        self.footer = bytes(footer)

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        common_key: Optional[bytes] = None,
        title_key: Optional[bytes] = None,
    ) -> "WADFile":
        """
        Parses a raw binary WAD package buffer.
        Optionally decrypts content payloads if common_key or title_key is supplied.
        """
        if len(data) < 32:
            raise ParseError("Data too small for WAD header (minimum 32 bytes).")

        hdr_size, wad_type_u16, wad_ver, cert_sz, crl_sz, tik_sz, tmd_sz, data_sz, footer_sz = (
            schema.unpack_from(">IHHIIIIII", data, 0)
        )
        if hdr_size != 0x20:
            raise ParseError(f"Invalid WAD header size: {hdr_size} (expected 0x20)")

        wad_type_bytes = schema.pack(">H", wad_type_u16)
        wad_type_str = wad_type_bytes.decode("ascii", errors="replace").strip("\x00")

        def _align64(sz: int) -> int:
            return (sz + 63) & ~63

        off = 0x40  # Header is padded to 64 bytes
        certs = data[off : off + cert_sz]
        off += _align64(cert_sz)

        crl = data[off : off + crl_sz]
        off += _align64(crl_sz)

        tik_data = data[off : off + tik_sz]
        off += _align64(tik_sz)

        tmd_data = data[off : off + tmd_sz]
        off += _align64(tmd_sz)

        data_chunk = data[off : off + data_sz]
        off += _align64(data_sz)

        footer = data[off : off + footer_sz]

        ticket = WADTicket.from_bytes(tik_data) if tik_sz >= 0x2A4 else None
        tmd = WADTmd.from_bytes(tmd_data) if tmd_sz >= 0x1E4 else None

        # Resolve Title Key
        resolved_title_key = title_key
        if ticket and common_key and not resolved_title_key:
            try:
                resolved_title_key = ticket.decrypt_title_key(common_key)
            except Exception:
                resolved_title_key = None

        raw_contents: Dict[int, bytes] = {}
        decrypted_contents: Dict[int, bytes] = {}

        if tmd:
            curr_data_off = 0
            for rec in tmd.contents:
                rec_enc_len = _align64(rec.size)
                raw_c = data_chunk[curr_data_off : curr_data_off + rec_enc_len]
                curr_data_off += rec_enc_len
                raw_contents[rec.index] = raw_c

                if resolved_title_key and len(raw_c) >= 16:
                    iv = schema.pack(">H", rec.index) + (b"\x00" * 14)
                    try:
                        dec = aes128_cbc_decrypt(raw_c, resolved_title_key, iv)
                        decrypted_contents[rec.index] = dec[: rec.size]
                    except Exception:
                        pass

        return cls(
            wad_type=wad_type_str,
            wad_version=wad_ver,
            certs=certs,
            crl=crl,
            ticket=ticket,
            tmd=tmd,
            raw_contents=raw_contents,
            decrypted_contents=decrypted_contents,
            title_key=resolved_title_key,
            footer=footer,
        )

    @classmethod
    def from_file(
        cls,
        path: str,
        common_key: Optional[bytes] = None,
        title_key: Optional[bytes] = None,
    ) -> "WADFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read(), common_key=common_key, title_key=title_key)

    def get_content(self, index: int) -> bytes:
        """
        Returns the decrypted content payload for the given content index.
        """
        if index in self.decrypted_contents:
            return self.decrypted_contents[index]
        if self.title_key and index in self.raw_contents and self.tmd:
            raw_c = self.raw_contents[index]
            rec = next((r for r in self.tmd.contents if r.index == index), None)
            if rec and len(raw_c) >= 16:
                iv = schema.pack(">H", rec.index) + (b"\x00" * 14)
                dec = aes128_cbc_decrypt(raw_c, self.title_key, iv)
                self.decrypted_contents[index] = dec[: rec.size]
                return self.decrypted_contents[index]

        raise KeyError(
            f"Decrypted content {index} unavailable (ensure common_key or title_key is set)."
        )

    def set_content(self, index: int, decrypted_data: bytes) -> None:
        """
        Replaces the content at `index` with new decrypted data.
        Automatically updates TMD size, re-calculates SHA-1 hash, and re-encrypts if title_key is set.
        """
        self.decrypted_contents[index] = bytes(decrypted_data)
        if self.tmd:
            self.tmd.update_content(index, decrypted_data)

        if self.title_key:
            iv = schema.pack(">H", index) + (b"\x00" * 14)
            pad_len = ((len(decrypted_data) + 63) & ~63) - len(decrypted_data)
            padded = decrypted_data + (b"\x00" * pad_len)
            enc = aes128_cbc_encrypt(padded, self.title_key, iv)
            self.raw_contents[index] = enc

    def get_u8_archive(self, index: int = 0) -> U8Archive:
        """
        Convenience bridge returning decrypted content at `index` as an in-memory U8Archive.
        """
        raw = self.get_content(index)
        return U8Archive.from_bytes(raw)

    def set_u8_archive(self, index: int, archive: Union[U8Archive, Dict[str, bytes]]) -> None:
        """
        Serializes an in-memory U8Archive (or dict) and replaces WAD content at `index`.
        """
        if isinstance(archive, U8Archive):
            data = archive.to_bytes()
        elif isinstance(archive, dict):
            data = U8Archive.pack_dict(archive)
        else:
            raise TypeError(f"Expected U8Archive or dict, got {type(archive)}")
        self.set_content(index, data)

    def to_bytes(self, fake_sign: bool = True) -> bytes:
        """
        Synthesizes all WAD sections into a valid 64-byte aligned Nintendo Wii WAD binary.
        Applies standard Trucha Bug fake-signing if `fake_sign=True`.
        """
        def _align64(sz: int) -> int:
            return (sz + 63) & ~63

        data_section = bytearray()
        if self.tmd:
            for rec in self.tmd.contents:
                raw_c = self.raw_contents.get(rec.index, b"")
                data_section.extend(raw_c)
                pad = _align64(len(raw_c)) - len(raw_c)
                data_section.extend(b"\x00" * pad)

        tik_bytes = self.ticket.to_bytes(fake_sign=fake_sign) if self.ticket else b""
        tmd_bytes = self.tmd.to_bytes(fake_sign=fake_sign) if self.tmd else b""

        cert_sz = len(self.certs)
        crl_sz = len(self.crl)
        tik_sz = len(tik_bytes)
        tmd_sz = len(tmd_bytes)
        data_sz = len(data_section)
        footer_sz = len(self.footer)

        type_b = self.wad_type.encode("ascii", errors="replace")[:2].ljust(2, b"\x00")
        type_u16 = schema.unpack_from(">H", type_b, 0)[0]

        hdr = bytearray(0x20)
        schema.pack_into(
            ">IHHIIIIII",
            hdr,
            0,
            0x20,
            type_u16,
            self.wad_version,
            cert_sz,
            crl_sz,
            tik_sz,
            tmd_sz,
            data_sz,
            footer_sz,
        )

        out = bytearray()
        out.extend(hdr)
        out.extend(b"\x00" * (_align64(0x20) - 0x20))

        if cert_sz > 0:
            out.extend(self.certs)
            out.extend(b"\x00" * (_align64(cert_sz) - cert_sz))

        if crl_sz > 0:
            out.extend(self.crl)
            out.extend(b"\x00" * (_align64(crl_sz) - crl_sz))

        if tik_sz > 0:
            out.extend(tik_bytes)
            out.extend(b"\x00" * (_align64(tik_sz) - tik_sz))

        if tmd_sz > 0:
            out.extend(tmd_bytes)
            out.extend(b"\x00" * (_align64(tmd_sz) - tmd_sz))

        if data_sz > 0:
            out.extend(data_section)
            out.extend(b"\x00" * (_align64(data_sz) - data_sz))

        if footer_sz > 0:
            out.extend(self.footer)
            out.extend(b"\x00" * (_align64(footer_sz) - footer_sz))

        return bytes(out)

    def save(self, path: str, fake_sign: bool = True) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes(fake_sign=fake_sign))

    def summary(self) -> str:
        """Returns a formatted diagnostic report of this WAD container."""
        lines = [f"WAD Package (Type: {self.wad_type!r}, v{self.wad_version})"]
        if self.tmd:
            tid_hex = self.tmd.title_id.hex().upper()
            try:
                ascii_code = self.tmd.title_id[4:8].decode("ascii")
            except Exception:
                ascii_code = "????"
            lines.append(f"  Title ID: {tid_hex} [{ascii_code}] (v{self.tmd.title_version})")
            lines.append(f"  Contents: {len(self.tmd.contents)} file(s)")
            for rec in self.tmd.contents:
                sha_prefix = rec.sha1_hash[:4].hex().upper()
                lines.append(
                    f"    [{rec.index}] ID {rec.content_id:08x}: {rec.size:,} bytes (type 0x{rec.content_type:04x}, SHA1: {sha_prefix}...)"
                )
        if self.ticket:
            lines.append(f"  Common Key Index: {self.ticket.common_key_index}")
            key_status = "Available" if self.title_key else "Missing"
            lines.append(f"  Title Key Status: {key_status}")
        return "\n".join(lines)

