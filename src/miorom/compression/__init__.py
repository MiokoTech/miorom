from miorom.compression.lz10 import LZ10
from miorom.compression.lz11 import LZ11
from miorom.compression.rle import RLE
from miorom.compression.yaz0 import Yaz0
from miorom.compression.huffman import Huffman
from miorom.compression.heuristic import (
    LZSSConfig,
    decompress_lzss,
    compress_lzss,
    HeuristicLZSolver,
)
from miorom.compression.carver import CompressionCarver, CarvedStream
from miorom.compression.speculative import SpeculativeStreamCarver, SpeculativeStream
from miorom.compression.inspector import (
    CompressionHeaderInspector,
    CompressedSizeComparator,
    CompressionSizeReport,
)

__all__ = [
    "LZ10",
    "LZ11",
    "RLE",
    "Yaz0",
    "Huffman",
    "LZSSConfig",
    "decompress_lzss",
    "compress_lzss",
    "HeuristicLZSolver",
    "CompressionCarver",
    "CarvedStream",
    "SpeculativeStreamCarver",
    "SpeculativeStream",
    "CompressionHeaderInspector",
    "CompressedSizeComparator",
    "CompressionSizeReport",
    "decompress",
    "compress",
]


def decompress(data: bytes) -> bytes:
    """
    Auto-detects and decompresses Nintendo compression formats:
    - Yaz0 ('Yaz0' magic)
    - LZ10 (0x10)
    - LZ11 (0x11)
    - Huffman 4-bit (0x24)
    - Huffman 8-bit (0x28)
    - RLE (0x30)
    """
    if len(data) < 4:
        raise ValueError("Data too short to detect compression header")

    if data[:4] == b"Yaz0":
        return Yaz0.decompress(data)

    magic = data[0]
    if magic == 0x10:
        return LZ10.decompress(data)
    elif magic == 0x11:
        return LZ11.decompress(data)
    elif magic in (0x24, 0x28):
        return Huffman.decompress(data)
    elif magic == 0x30:
        return RLE.decompress(data)
    else:
        raise ValueError(f"Unknown or unsupported compression header: {hex(magic)} / {data[:4]!r}")


def compress(data: bytes, fmt: str = "lz11") -> bytes:
    """
    Compresses data using specified format:
    'lz10', 'lz11', 'rle', 'yaz0', 'huffman4', 'huffman8'. Default: 'lz11'.
    """
    fmt_lower = fmt.lower()
    if fmt_lower in ["lz10", "0x10"]:
        return LZ10.compress(data)
    elif fmt_lower in ["lz11", "0x11"]:
        return LZ11.compress(data)
    elif fmt_lower in ["rle", "0x30"]:
        return RLE.compress(data)
    elif fmt_lower == "yaz0":
        return Yaz0.compress(data)
    elif fmt_lower in ["huffman4", "0x24"]:
        return Huffman.compress(data, bit_depth=4)
    elif fmt_lower in ["huffman8", "huffman", "0x28"]:
        return Huffman.compress(data, bit_depth=8)
    else:
        raise ValueError(
            f"Unsupported compression format: '{fmt}'. Choose 'lz10', 'lz11', 'rle', 'yaz0', 'huffman4', or 'huffman8'."
        )
