"""
miorom.helper.dual_table
~~~~~~~~~~~~~~~~~~~~~~~~
Helper for Neverland/Marvelous dual-table text files (Rune Factory, Harvest Moon).
Handles extraction and bit-perfect reconstruction of dual-table containers with
Table 1 at 0x10 and Table 2 in the footer.
"""

import struct
from typing import Any, Dict, List, Optional, Tuple


class DualTableHelper:
    """
    Helper for reading and rebuilding dual-table text containers.
    """

    @classmethod
    def extract(
        cls,
        data: bytes,
        encoding: str = "utf-16-be",
        endian: str = ">",
        strip: bool = False,
        filter_empty: bool = False,
        tag_converter: Optional[Any] = None,
    ) -> Tuple[List[str], List[str]]:
        """
        Extract strings from both Table 1 and Table 2.
        Returns (table1_strings, table2_strings).

        Keyword Args:
            encoding: Text encoding (default: 'utf-16-be').
            endian: Byte order ('>' for big-endian, '<' for little-endian).
            strip: Strip whitespace from extracted dialogue strings.
            filter_empty: Remove empty strings from returned lists.
            tag_converter: Optional TagConverter instance (or dict) to transform raw escapes into human tags.
        """
        if len(data) < 0x20:
            return [], []

        t2_offset = struct.unpack_from(f"{endian}I", data, 4)[0]
        if t2_offset <= 0 or t2_offset + 16 > len(data):
            return [], []

        c1, c2, m1, m2 = struct.unpack_from(f"{endian}IIII", data, t2_offset)
        t1_count = c1 - c2

        def process_str(s: str) -> str:
            if tag_converter is not None:
                if hasattr(tag_converter, "apply"):
                    s = tag_converter.apply(s)
                elif isinstance(tag_converter, dict):
                    for k, v in tag_converter.items():
                        s = s.replace(v, k)
            return s.strip() if strip else s

        # Extract Table 1
        t1_strings: List[str] = []
        for i in range(t1_count):
            ptr = struct.unpack_from(f"{endian}I", data, 0x10 + i * 4)[0]
            s = process_str(cls._read_string(data, ptr, encoding))
            if not filter_empty or s:
                t1_strings.append(s)

        # Extract Table 2 (starts after metadata block)
        t2_ptrs_offset = t2_offset + 16
        t2_strings: List[str] = []
        for i in range(c2):
            ptr = struct.unpack_from(f"{endian}I", data, t2_ptrs_offset + i * 4)[0]
            s = process_str(cls._read_string(data, ptr, encoding))
            if not filter_empty or s:
                t2_strings.append(s)

        return t1_strings, t2_strings

    @classmethod
    def repack(
        cls,
        table1_strings: List[str],
        table2_strings: List[str],
        encoding: str = "utf-16-be",
        endian: str = ">",
        alignment: int = 32,
        pad_byte: bytes = b"\x00",
        tag_converter: Optional[Any] = None,
    ) -> bytes:
        """
        Rebuild a dual-table binary container from modified Table 1 and Table 2 string lists.

        Keyword Args:
            encoding: Text encoding (default: 'utf-16-be').
            endian: Byte order (default: '>').
            alignment: Byte boundary to align container size to (default: 32).
            pad_byte: Byte used for alignment padding (default: b'\\x00').
            tag_converter: Optional TagConverter instance to revert tags back to raw escapes.
        """
        def revert_str(s: str) -> str:
            if tag_converter is not None:
                if hasattr(tag_converter, "revert"):
                    return tag_converter.revert(s)
                elif isinstance(tag_converter, dict):
                    for k, v in tag_converter.items():
                        s = s.replace(k, v)
            return s

        t1_list = [revert_str(s) for s in table1_strings]
        t2_list = [revert_str(s) for s in table2_strings]

        t1_count = len(t1_list)
        t2_count = len(t2_list)
        c1 = t1_count + t2_count

        t1_ptr_bytes = t1_count * 4
        pool1_start = 0x10 + t1_ptr_bytes

        # Encode Table 1 strings
        t1_offsets = []
        pool1_bytes = bytearray()
        for s in t1_list:
            t1_offsets.append(pool1_start + len(pool1_bytes))
            pool1_bytes.extend(s.encode(encoding, errors="replace") + b"\x00\x00")

        # Encode Table 2 strings
        pool2_start = pool1_start + len(pool1_bytes)
        t2_offsets = []
        pool2_bytes = bytearray()
        for s in t2_list:
            t2_offsets.append(pool2_start + len(pool2_bytes))
            pool2_bytes.extend(s.encode(encoding, errors="replace") + b"\x00\x00")

        p_end = pool2_start + len(pool2_bytes)
        # Pad after pool to align
        meta_start = p_end + 4  # 4 bytes padding

        # Construct binary
        out = bytearray()
        # Header (16 bytes): [0, t2_offset, 1, 0]
        out.extend(struct.pack(f"{endian}IIII", 0, meta_start, 1, 0))

        # Table 1 pointers
        for off in t1_offsets:
            out.extend(struct.pack(f"{endian}I", off))

        # String pools
        out.extend(pool1_bytes)
        out.extend(pool2_bytes)
        out.extend(b"\x00\x00\x00\x00")  # 4-byte padding

        # Metadata block: [c1, t2_count, 1, 0]
        out.extend(struct.pack(f"{endian}IIII", c1, t2_count, 1, 0))

        # Table 2 pointers
        for off in t2_offsets:
            out.extend(struct.pack(f"{endian}I", off))

        # p_end
        out.extend(struct.pack(f"{endian}I", p_end))

        # Align to boundary
        if alignment > 1:
            rem = len(out) % alignment
            if rem != 0:
                out.extend(pad_byte * (alignment - rem))

        return bytes(out)

    @classmethod
    def _read_string(cls, data: bytes, offset: int, encoding: str) -> str:
        p = offset
        chars = bytearray()
        while p + 1 < len(data):
            two = data[p:p + 2]
            if two == b"\x00\x00":
                break
            chars.extend(two)
            p += 2
        return chars.decode(encoding, errors="replace")
