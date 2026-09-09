import importlib.metadata
import logging

from miorom.compression.lz10 import LZ10
from miorom.errors import CompressionError
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
    "register_codec",
    "list_codecs",
]

_compress_registry: dict = {}
_magic_registry: dict = {}
_plugin_logger = logging.getLogger(__name__)


def register_codec(name, cls, *, magic_bytes=None, magic_int=None, compress_func=None):
    """Register a compression codec for auto-detection and named dispatch."""
    _compress_registry[name.lower()] = compress_func or cls.compress
    decompress_fn = cls.decompress
    if magic_bytes is not None:
        _magic_registry[magic_bytes] = decompress_fn
    if magic_int is not None:
        _magic_registry[magic_int] = decompress_fn


def list_codecs():
    """Return sorted list of registered codec names."""
    return sorted(_compress_registry.keys())


def decompress(data: bytes) -> bytes:
    """Auto-detects and decompresses Nintendo compression formats."""
    if len(data) < 4:
        raise CompressionError("Data too short to detect compression header")

    if data[:4] in _magic_registry:
        return _magic_registry[data[:4]](data)

    magic = data[0]
    if magic in _magic_registry:
        return _magic_registry[magic](data)
    raise CompressionError(f"Unknown or unsupported compression header: {hex(magic)} / {data[:4]!r}")


def compress(data: bytes, fmt: str = "lz11") -> bytes:
    """Compresses data using registered codec by name."""
    fn = _compress_registry.get(fmt.lower())
    if fn is None:
        raise CompressionError(
            f"Unsupported compression format: '{fmt}'. Available: {', '.join(list_codecs())}."
        )
    return fn(data)


register_codec("lz10", LZ10, magic_int=0x10)
register_codec("lz11", LZ11, magic_int=0x11)
register_codec("rle", RLE, magic_int=0x30)
register_codec("yaz0", Yaz0, magic_bytes=b"Yaz0")
register_codec("huffman4", Huffman, magic_int=0x24, compress_func=lambda d: Huffman.compress(d, bit_depth=4))
register_codec("huffman8", Huffman, magic_int=0x28, compress_func=lambda d: Huffman.compress(d, bit_depth=8))
register_codec("huffman", Huffman, magic_int=0x28, compress_func=lambda d: Huffman.compress(d, bit_depth=8))

def _discover_codec_plugins():
    """Auto-discover third-party compression codecs via entry_points."""
    try:
        eps = importlib.metadata.entry_points(group="miorom.codecs")
    except TypeError:
        return
    for entry_point in eps:
        try:
            codec = entry_point.load()
            if callable(codec):
                codec = codec()
            register_codec(entry_point.name, codec, magic_bytes=getattr(codec, "MAGIC", None))
        except Exception:
            _plugin_logger.debug("Failed to load compression codec plugin: %s", entry_point.name, exc_info=True)

_discover_codec_plugins()
