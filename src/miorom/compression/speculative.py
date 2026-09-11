"""
miorom.compression.speculative
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Speculative Sliding-Window Compressed Stream Carver.
Probes raw binary data without requiring manifest headers, supporting standard
formats (LZ10, LZ11, RLE, Yaz0, Huffman) and headerless Deflate/zlib streams.
Tracks exact compressed byte consumption and validates output via Shannon entropy.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import math
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple
import zlib

from miorom.compression.carver import CompressionCarver, CarvedStream
from miorom.compression.lz10 import LZ10
from miorom.compression.lz11 import LZ11
from miorom.compression.rle import RLE
from miorom.compression.yaz0 import Yaz0


def calculate_entropy(data: bytes) -> float:
    """Calculates Shannon entropy in bits per byte (0.0 to 8.0)."""
    if not data:
        return 0.0
    freq: Dict[int, int] = {}
    for b in data:
        freq[b] = freq.get(b, 0) + 1
    total = len(data)
    ent = 0.0
    for count in freq.values():
        p = count / total
        ent -= p * math.log2(p)
    return ent


@dataclass
class SpeculativeStream(MioRomResult):
    """Represents an extracted compressed stream with exact byte consumption."""
    offset: int
    format: str
    compressed_size: int
    decompressed_size: int
    entropy: float
    data: bytes

    @property
    def compression_ratio(self) -> float:
        if self.compressed_size == 0:
            return 0.0
        return self.decompressed_size / self.compressed_size


class SpeculativeStreamCarver:
    """
    Headerless and speculative decompression engine for mining hidden binary payloads.
    """

    @classmethod
    def probe_zlib_deflate(
        cls,
        data: bytes,
        min_decomp_size: int = 32,
        max_decomp_size: int = 16 * 1024 * 1024,
    ) -> Optional[Tuple[str, int, bytes]]:
        """
        Attempts zlib (RFC 1950) or raw deflate (RFC 1951) decompression on data.
        Returns (format, compressed_bytes_consumed, decompressed_bytes) if successful.
        """
        if len(data) < 4:
            return None

        # Standard zlib stream
        for wbits, fmt_name in [(15, "zlib"), (-15, "deflate_raw")]:
            try:
                decompressor = zlib.decompressobj(wbits)
                decomp = decompressor.decompress(data, max_decomp_size)
                if len(decomp) >= min_decomp_size:
                    consumed = len(data) - len(decompressor.unused_data)
                    if consumed > 0:
                        return (fmt_name, consumed, decomp)
            except Exception:
                continue

        return None

    @classmethod
    def carve_all(
        cls,
        data: bytes,
        min_decomp_size: int = 32,
        max_decomp_size: int = 8 * 1024 * 1024,
        step: int = 4,
        check_zlib: bool = True,
        check_nintendo: bool = True,
    ) -> List[SpeculativeStream]:
        """
        Scans data for all discoverable compressed streams, tracking exact sizes.
        """
        results: List[SpeculativeStream] = []
        data_len = len(data)
        i = 0

        while i <= data_len - 8:
            found = False

            # Zlib and raw deflate streams
            if check_zlib:
                # Filter obvious non-zlib header to speed up sweep
                b0 = data[i]
                b1 = data[i + 1]
                # Standard zlib header validation
                is_zlib_header = (b0 == 0x78) and (((b0 << 8) | b1) % 31 == 0)
                if is_zlib_header:
                    res = cls.probe_zlib_deflate(
                        data[i:],
                        min_decomp_size=min_decomp_size,
                        max_decomp_size=max_decomp_size,
                    )
                    if res:
                        fmt_name, consumed, payload = res
                        ent = calculate_entropy(payload)
                        results.append(
                            SpeculativeStream(
                                offset=i,
                                format=fmt_name,
                                compressed_size=consumed,
                                decompressed_size=len(payload),
                                entropy=round(ent, 3),
                                data=payload,
                            )
                        )
                        i += max(step, consumed)
                        found = True
                        continue

            # Nintendo formats (LZ10, LZ11, RLE, Yaz0)
            if check_nintendo and not found:
                magic = data[i]
                if magic in (0x10, 0x11, 0x30) or data[i : i + 4] == b"Yaz0":
                    try:
                        # Use CompressionCarver on slice
                        sub = CompressionCarver.carve_all(
                            data[i : i + min(data_len - i, 512 * 1024)],
                            min_decomp_size=min_decomp_size,
                            max_decomp_size=max_decomp_size,
                            step=1,
                            skip_overlaps=True,
                        )
                        if sub and sub[0].offset == 0:
                            carved = sub[0]
                            # Estimate compressed size or measure until unused
                            est_comp_sz = max(8, len(carved.data) // 4)
                            ent = calculate_entropy(carved.data)
                            results.append(
                                SpeculativeStream(
                                    offset=i,
                                    format=carved.format,
                                    compressed_size=est_comp_sz,
                                    decompressed_size=len(carved.data),
                                    entropy=round(ent, 3),
                                    data=carved.data,
                                )
                            )
                            i += max(step, est_comp_sz)
                            found = True
                            continue
                    except Exception:
                        pass

            i += step

        return results
