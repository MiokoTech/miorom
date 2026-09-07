import zlib
import pytest
from miorom.compression.speculative import SpeculativeStreamCarver, calculate_entropy
from miorom.compression.lz10 import LZ10


def test_speculative_zlib_carving():
    payload = b"Hello from speculative carver test stream! Repeating payload to compress well. " * 5
    compressed_zlib = zlib.compress(payload)

    buf = bytearray(512)
    # Put compressed stream at offset 0x40
    buf[0x40 : 0x40 + len(compressed_zlib)] = compressed_zlib

    carved = SpeculativeStreamCarver.carve_all(bytes(buf), min_decomp_size=32)
    assert len(carved) >= 1
    found = next(c for c in carved if c.offset == 0x40)
    assert found.format == "zlib"
    assert found.data == payload
    assert found.compressed_size == len(compressed_zlib)
    assert found.decompressed_size == len(payload)
    assert found.entropy > 0.0


def test_speculative_lz10_carving():
    payload = b"Testing LZ10 compression stream embedded in dummy binary data buffer. " * 4
    comp_lz10 = LZ10.compress(payload)

    buf = bytearray(512)
    buf[0x80 : 0x80 + len(comp_lz10)] = comp_lz10

    carved = SpeculativeStreamCarver.carve_all(bytes(buf), min_decomp_size=32)
    assert len(carved) >= 1
    found = next(c for c in carved if c.offset == 0x80)
    assert found.format == "lz10"
    assert found.data == payload
