import os
import tempfile
import pytest

from miorom.compression.lz10 import LZ10
from miorom.compression.lz11 import LZ11
from miorom.compression.rle import RLE
from miorom.compression.yaz0 import Yaz0
from miorom.compression.carver import CompressionCarver, CarvedStream


def test_compression_carver_multi_format():
    payload1 = b"Hello from decompressed stream 1! Repetition " * 5  # > 32 bytes
    payload2 = b"Second stream payload testing LZ11 carver engine " * 4
    payload3 = b"Yaz0 stream payload testing GameCube/Wii decompression " * 3

    comp_lz10 = LZ10.compress(payload1)
    comp_lz11 = LZ11.compress(payload2)
    comp_yaz0 = Yaz0.compress(payload3)

    # Assemble synthetic ROM buffer with padding
    buf = bytearray(0x2000)
    # Stream 1 at 0x100
    buf[0x100 : 0x100 + len(comp_lz10)] = comp_lz10
    # Stream 2 at 0x400
    buf[0x400 : 0x400 + len(comp_lz11)] = comp_lz11
    # Stream 3 at 0x800
    buf[0x800 : 0x800 + len(comp_yaz0)] = comp_yaz0

    carved = CompressionCarver.carve_all(bytes(buf), min_decomp_size=32)

    assert len(carved) >= 3
    # Check that our streams are found at expected offsets
    offsets = {c.offset: c for c in carved}

    assert 0x100 in offsets
    assert offsets[0x100].format == "lz10"
    assert offsets[0x100].data == payload1

    assert 0x400 in offsets
    assert offsets[0x400].format == "lz11"
    assert offsets[0x400].data == payload2

    assert 0x800 in offsets
    assert offsets[0x800].format == "yaz0"
    assert offsets[0x800].data == payload3


def test_compression_carver_extract_all():
    payload = b"Extract test data for compression carver file extraction " * 4
    comp = LZ10.compress(payload)

    buf = bytearray(0x500)
    buf[0x100 : 0x100 + len(comp)] = comp

    with tempfile.TemporaryDirectory() as tmpdir:
        paths = CompressionCarver.extract_all(bytes(buf), output_dir=tmpdir, formats=["lz10"])
        assert len(paths) >= 1
        assert os.path.exists(paths[0])
        with open(paths[0], "rb") as f:
            data = f.read()
        assert data == payload
