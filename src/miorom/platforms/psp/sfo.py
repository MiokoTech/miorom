"""
miorom.platforms.psp.sfo
~~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation PARAM.SFO (System File Object) metadata parser and builder.

PARAM.SFO is the standard key-value configuration and metadata container
used across PlayStation Portable (PSP), PS Vita, PS3, and PS4 packages.
"""

import struct
from typing import Any, Dict, List, Optional, Union

from miorom.errors import ParseError
from miorom.result import MioRomResult


SFO_MAGIC = b"\x00PSF"
FMT_UTF8_SPECIAL = 0x0004
FMT_ASCII_STRING = 0x0204
FMT_UINT32 = 0x0404


class SFOFile(MioRomResult):
    """
    Parser and serializer for Sony PARAM.SFO metadata dictionaries.
    """

    def __init__(self, entries: Optional[Dict[str, Union[str, int]]] = None):
        self.entries: Dict[str, Union[str, int]] = dict(entries) if entries else {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "SFOFile":
        """Parses raw binary PARAM.SFO bytes."""
        if len(data) < 20:
            raise ParseError("Data too small for PARAM.SFO header (minimum 20 bytes).")

        magic = data[:4]
        if magic != SFO_MAGIC:
            raise ParseError(f"Invalid PARAM.SFO magic: {magic!r}, expected {SFO_MAGIC!r}")

        version, key_tbl_start, data_tbl_start, count = struct.unpack_from("<IIII", data, 4)

        if len(data) < 20 + count * 16:
            raise ParseError("PARAM.SFO index table truncated.")

        entries: Dict[str, Union[str, int]] = {}

        for i in range(count):
            entry_off = 20 + i * 16
            key_off, data_fmt, data_len, data_max_len, data_off = struct.unpack_from(
                "<HHIII", data, entry_off
            )

            # Read key name from key table
            k_start = key_tbl_start + key_off
            k_end = data.find(b"\x00", k_start)
            if k_end == -1:
                k_end = len(data)
            key_str = data[k_start:k_end].decode("ascii", errors="replace")

            # Read value from data table
            val_start = data_tbl_start + data_off
            val_bytes = data[val_start : val_start + data_len]

            if data_fmt == FMT_UINT32:
                if len(val_bytes) >= 4:
                    val: Union[str, int] = struct.unpack_from("<I", val_bytes, 0)[0]
                else:
                    val = 0
            elif data_fmt in (FMT_ASCII_STRING, FMT_UTF8_SPECIAL):
                # String value (strip trailing null bytes)
                val = val_bytes.rstrip(b"\x00").decode("utf-8", errors="replace")
            else:
                # Default raw string
                val = val_bytes.rstrip(b"\x00").decode("latin-1", errors="replace")

            entries[key_str] = val

        return cls(entries)

    @classmethod
    def from_file(cls, path: str) -> "SFOFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def get(self, key: str, default: Any = None) -> Any:
        return self.entries.get(key, default)

    def set(self, key: str, value: Union[str, int]):
        self.entries[key] = value

    def __getitem__(self, key: str) -> Union[str, int]:
        return self.entries[key]

    def __setitem__(self, key: str, value: Union[str, int]):
        self.entries[key] = value

    def __contains__(self, key: str) -> bool:
        return key in self.entries

    @property
    def title(self) -> Optional[str]:
        val = self.entries.get("TITLE")
        return str(val) if val is not None else None

    @property
    def disc_id(self) -> Optional[str]:
        val = self.entries.get("DISC_ID")
        return str(val) if val is not None else None

    @property
    def category(self) -> Optional[str]:
        val = self.entries.get("CATEGORY")
        return str(val) if val is not None else None

    def to_bytes(self) -> bytes:
        """Serializes dictionary entries into standards-compliant PARAM.SFO binary bytes."""
        sorted_keys = sorted(self.entries.keys())
        count = len(sorted_keys)

        # Build key table
        key_table = bytearray()
        key_offsets: Dict[str, int] = {}
        for k in sorted_keys:
            key_offsets[k] = len(key_table)
            key_table.extend(k.encode("ascii") + b"\x00")

        # Build data table
        data_table = bytearray()
        entry_meta: List[Tuple[int, int, int, int, int]] = []

        for k in sorted_keys:
            val = self.entries[k]
            k_off = key_offsets[k]
            val_off = len(data_table)

            if isinstance(val, int):
                fmt = FMT_UINT32
                val_bytes = struct.pack("<I", val & 0xFFFFFFFF)
                data_len = 4
                data_max_len = 4
            else:
                fmt = FMT_UTF8_SPECIAL
                encoded_str = str(val).encode("utf-8") + b"\x00"
                val_bytes = encoded_str
                data_len = len(encoded_str)
                # Pad max length to 4-byte boundary
                data_max_len = (data_len + 3) & ~3
                val_bytes = val_bytes.ljust(data_max_len, b"\x00")

            data_table.extend(val_bytes)
            entry_meta.append((k_off, fmt, data_len, data_max_len, val_off))

        # Calculate section offsets (4-byte aligned)
        index_table_len = count * 16
        key_tbl_start = 20 + index_table_len
        # Pad key table to 4 bytes
        key_tbl_padded_len = (len(key_table) + 3) & ~3
        data_tbl_start = key_tbl_start + key_tbl_padded_len

        # Construct header (20 bytes)
        out = bytearray(20)
        out[0:4] = SFO_MAGIC
        struct.pack_into("<IIII", out, 4, 0x00010100, key_tbl_start, data_tbl_start, count)

        # Append index entries
        for k_off, fmt, d_len, d_max, d_off in entry_meta:
            out.extend(struct.pack("<HHIII", k_off, fmt, d_len, d_max, d_off))

        # Append key table
        out.extend(key_table)
        if len(key_table) < key_tbl_padded_len:
            out.extend(b"\x00" * (key_tbl_padded_len - len(key_table)))

        # Append data table
        out.extend(data_table)

        return bytes(out)

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(self.to_bytes())
