"""
miorom.compression.inspector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Compression Header Inspector & Size Forensics Primitive.
Inspects and patches uncompressed size headers (Nintendo LZ10/LZ11/RLE, Yaz0)
and evaluates payload size deltas to predict RAM buffer safety.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass
import struct
from typing import Dict, Optional, Tuple


@dataclass
class CompressionSizeReport(MioRomResult):
    """Report comparing compressed and uncompressed sizes."""
    format: str
    original_size: int
    new_size: int
    delta: int
    has_expanded: bool


class CompressionHeaderInspector:
    """
    Pure primitive to inspect and patch uncompressed size headers in compressed streams.
    """

    @classmethod
    def read_uncompressed_size(cls, data: bytes, format_hint: str = "auto") -> Optional[int]:
        """
        Reads the expected decompressed buffer size from the compression header.
        """
        if len(data) < 4:
            return None

        magic = data[0]

        # Yaz0 check
        if data[:4] == b"Yaz0" and len(data) >= 8:
            return struct.unpack_from(">I", data, 4)[0]

        # Nintendo LZ10 (0x10), LZ11 (0x11), RLE (0x30)
        if magic in (0x10, 0x11, 0x30):
            size_24 = data[1] | (data[2] << 8) | (data[3] << 16)
            if size_24 == 0 and magic == 0x11 and len(data) >= 8:
                # LZ11 extended 32-bit length
                return struct.unpack_from("<I", data, 4)[0]
            return size_24

        return None

    @classmethod
    def patch_uncompressed_size(
        cls,
        data: bytearray,
        new_size: int,
        format_hint: str = "auto",
    ) -> bool:
        """
        Patches the uncompressed size header in-place in data.
        """
        if len(data) < 4:
            return False

        # Yaz0
        if data[:4] == b"Yaz0" and len(data) >= 8:
            struct.pack_into(">I", data, 4, new_size)
            return True

        magic = data[0]
        # Nintendo LZ10, LZ11, RLE
        if magic in (0x10, 0x11, 0x30):
            if new_size <= 0xFFFFFF:
                data[1] = new_size & 0xFF
                data[2] = (new_size >> 8) & 0xFF
                data[3] = (new_size >> 16) & 0xFF
                return True
            elif magic == 0x11 and len(data) >= 8:
                # Extended LZ11: zero out 24-bit field and write 32-bit at offset 4
                data[1] = data[2] = data[3] = 0
                struct.pack_into("<I", data, 4, new_size)
                return True

        return False


class CompressedSizeComparator:
    """
    Pure primitive to compare compressed payload sizes before and after translation.
    """

    @classmethod
    def compare(
        cls,
        original_compressed: bytes,
        new_compressed: bytes,
        format_name: str = "generic",
    ) -> CompressionSizeReport:
        """
        Compares binary sizes and returns report.
        """
        orig_sz = len(original_compressed)
        new_sz = len(new_compressed)
        delta = new_sz - orig_sz

        return CompressionSizeReport(
            format=format_name,
            original_size=orig_sz,
            new_size=new_sz,
            delta=delta,
            has_expanded=delta > 0,
        )
