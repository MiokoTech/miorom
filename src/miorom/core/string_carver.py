"""
miorom.core.string_carver
~~~~~~~~~~~~~~~~~~~~~~~~~
Low-Level Binary String Pool Carver Primitive.
Carves contiguous text sequences (null-terminated and Pascal-length prefixed)
from arbitrary binary ROM buffers with encoding verification and printable filtering.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass
import struct
from typing import List, Optional, Tuple


@dataclass
class CarvedString(MioRomResult):
    """Represents a discovered string inside a binary buffer."""
    offset: int
    text: str
    byte_length: int
    encoding: str


class StringPoolCarver:
    """
    Pure modular primitive to carve string pools out of raw binary dumps.
    """

    @classmethod
    def _is_printable(cls, s: str) -> bool:
        """Checks if decoded string consists predominantly of printable characters."""
        if not s:
            return False
        printable_cnt = sum(1 for c in s if c.isprintable() or c in ("\n", "\r", "\t"))
        return (printable_cnt / len(s)) >= 0.85

    @classmethod
    def carve_null_terminated(
        cls,
        data: bytes,
        min_len: int = 3,
        encoding: str = "utf-8",
        start: int = 0,
        end: Optional[int] = None,
    ) -> List[CarvedString]:
        """
        Carves all null-terminated strings within [start, end).
        """
        limit = end if end is not None else len(data)
        results: List[CarvedString] = []
        cur = start

        while cur < limit:
            null_pos = data.find(b"\x00", cur, limit)
            if null_pos == -1:
                break

            chunk = data[cur:null_pos]
            if len(chunk) >= min_len:
                try:
                    text = chunk.decode(encoding)
                    if cls._is_printable(text):
                        results.append(
                            CarvedString(
                                offset=cur,
                                text=text,
                                byte_length=len(chunk) + 1,  # include null terminator
                                encoding=encoding,
                            )
                        )
                except (UnicodeDecodeError, ValueError):
                    pass

            cur = null_pos + 1

        return results

    @classmethod
    def carve_pascal_strings(
        cls,
        data: bytes,
        min_len: int = 2,
        length_size: int = 1,
        encoding: str = "utf-8",
        start: int = 0,
        end: Optional[int] = None,
        endian: str = "<",
    ) -> List[CarvedString]:
        """
        Carves Pascal-style length-prefixed strings within [start, end).
        """
        limit = end if end is not None else len(data)
        results: List[CarvedString] = []
        cur = start
        fmt = "B" if length_size == 1 else (f"{endian}H" if length_size == 2 else f"{endian}I")

        while cur + length_size < limit:
            length = struct.unpack_from(fmt, data, cur)[0]
            if min_len <= length <= 256 and cur + length_size + length <= limit:
                chunk = data[cur + length_size : cur + length_size + length]
                try:
                    text = chunk.decode(encoding)
                    if cls._is_printable(text):
                        results.append(
                            CarvedString(
                                offset=cur,
                                text=text,
                                byte_length=length_size + length,
                                encoding=encoding,
                            )
                        )
                        cur += length_size + length
                        continue
                except (UnicodeDecodeError, ValueError):
                    pass

            cur += 1

        return results
