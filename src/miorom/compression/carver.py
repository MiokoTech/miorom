"""
miorom.compression.carver
~~~~~~~~~~~~~~~~~~~~~~~~~
Heuristic Stream Carver for discovering and extracting embedded compressed streams
from ROM files, archives, and memory dumps.
Supports Nintendo standard formats: LZ10, LZ11, RLE, Huffman, and Yaz0.
"""

import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from miorom.compression.lz10 import LZ10
from miorom.compression.lz11 import LZ11
from miorom.compression.rle import RLE
from miorom.compression.huffman import Huffman
from miorom.compression.yaz0 import Yaz0


@dataclass
class CarvedStream:
    """Represents a discovered and decompressed stream within binary data."""
    offset: int
    format: str
    decompressed_size: int
    data: bytes

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    def save(self, filepath: str) -> None:
        """Save decompressed payload to disk."""
        with open(filepath, "wb") as f:
            f.write(self.data)

    def __repr__(self) -> str:
        return f"<CarvedStream offset=0x{self.offset:06X} fmt={self.format} size={self.decompressed_size}>"


class CompressionCarver:
    """
    Automated binary carver scanning for embedded compressed payloads.
    """

    SUPPORTED_FORMATS = ["lz10", "lz11", "rle", "yaz0", "huffman"]

    @classmethod
    def carve_all(
        cls,
        data: bytes,
        formats: Optional[List[str]] = None,
        min_decomp_size: int = 32,
        max_decomp_size: int = 16 * 1024 * 1024,
        step: int = 4,
        skip_overlaps: bool = True,
    ) -> List[CarvedStream]:
        """
        Scans data for embedded compressed streams and decompresses them.

        Args:
            data: Binary buffer to scan.
            formats: List of formats to test ('lz10', 'lz11', 'rle', 'yaz0', 'huffman'). Defaults to all.
            min_decomp_size: Minimum decompressed payload size to accept (filters out noise).
            max_decomp_size: Maximum decompressed payload size to prevent OOM on corrupt headers.
            step: Offset step increment (default 4 bytes for 32-bit aligned structures).
            skip_overlaps: If True, advances search position after finding a valid stream.
        """
        target_formats = set(fmt.lower() for fmt in (formats or cls.SUPPORTED_FORMATS))
        carved: List[CarvedStream] = []
        data_len = len(data)

        i = 0
        while i <= data_len - 8:
            # 1. Check Yaz0
            if "yaz0" in target_formats and data[i : i + 4] == b"Yaz0":
                try:
                    dec_sz = struct.unpack(">I", data[i + 4 : i + 8])[0]
                    if min_decomp_size <= dec_sz <= max_decomp_size:
                        decomp = Yaz0.decompress(data[i:])
                        if len(decomp) == dec_sz:
                            stream = CarvedStream(
                                offset=i,
                                format="yaz0",
                                decompressed_size=len(decomp),
                                data=decomp,
                            )
                            carved.append(stream)
                            if skip_overlaps:
                                i += 16
                                continue
                except Exception:
                    pass

            # 2. Check Nintendo 4-byte header: magic byte + 24-bit LE decompressed size
            magic = data[i]

            # Parse expected size
            expected_sz = data[i + 1] | (data[i + 2] << 8) | (data[i + 3] << 16)
            header_len = 4
            if expected_sz == 0 and magic in (0x10, 0x11):
                if i + 8 <= data_len:
                    expected_sz = struct.unpack("<I", data[i + 4 : i + 8])[0]
                    header_len = 8

            if min_decomp_size <= expected_sz <= max_decomp_size:
                # Try LZ10 (0x10)
                if "lz10" in target_formats and magic == 0x10:
                    try:
                        decomp = LZ10.decompress(data[i:])
                        if len(decomp) == expected_sz:
                            carved.append(CarvedStream(
                                offset=i,
                                format="lz10",
                                decompressed_size=len(decomp),
                                data=decomp,
                            ))
                            if skip_overlaps:
                                i += header_len
                                continue
                    except Exception:
                        pass

                # Try LZ11 (0x11)
                if "lz11" in target_formats and magic == 0x11:
                    try:
                        decomp = LZ11.decompress(data[i:])
                        if len(decomp) == expected_sz:
                            carved.append(CarvedStream(
                                offset=i,
                                format="lz11",
                                decompressed_size=len(decomp),
                                data=decomp,
                            ))
                            if skip_overlaps:
                                i += header_len
                                continue
                    except Exception:
                        pass

                # Try RLE (0x30)
                if "rle" in target_formats and magic == 0x30:
                    try:
                        decomp = RLE.decompress(data[i:])
                        if len(decomp) == expected_sz:
                            carved.append(CarvedStream(
                                offset=i,
                                format="rle",
                                decompressed_size=len(decomp),
                                data=decomp,
                            ))
                            if skip_overlaps:
                                i += header_len
                                continue
                    except Exception:
                        pass

                # Try Huffman (0x24 / 0x28)
                if "huffman" in target_formats and magic in (0x24, 0x28):
                    try:
                        decomp = Huffman.decompress(data[i:])
                        if len(decomp) == expected_sz:
                            carved.append(CarvedStream(
                                offset=i,
                                format="huffman",
                                decompressed_size=len(decomp),
                                data=decomp,
                            ))
                            if skip_overlaps:
                                i += header_len
                                continue
                    except Exception:
                        pass

            i += step

        return carved

    @classmethod
    def extract_all(
        cls,
        data: bytes,
        output_dir: str,
        prefix: str = "stream_",
        formats: Optional[List[str]] = None,
    ) -> List[str]:
        """
        Scans data and writes all discovered decompressed streams directly to output_dir.
        Returns list of extracted file paths.
        """
        os.makedirs(output_dir, exist_ok=True)
        streams = cls.carve_all(data, formats=formats)
        extracted_paths: List[str] = []

        for idx, s in enumerate(streams):
            filename = f"{prefix}{idx:04d}_0x{s.offset:08X}_{s.format}.bin"
            out_path = os.path.join(output_dir, filename)
            s.save(out_path)
            extracted_paths.append(out_path)

        return extracted_paths
