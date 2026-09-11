import pytest

from miorom.compression import Yay0, APLib, decompress, compress
from miorom.errors import CompressionError


def test_yay0_roundtrip_basic():
    original = b"Hello world! Hello world! This is a Yay0 test string. Hello world!"
    compressed = Yay0.compress(original)

    assert compressed.startswith(b"Yay0")
    assert len(compressed) < len(original) + 32  # Valid compression stream

    decompressed = Yay0.decompress(compressed)
    assert decompressed == original


def test_yay0_roundtrip_large_repeats():
    original = b"ABCDEF1234567890" * 100
    compressed = Yay0.compress(original)
    assert len(compressed) < len(original)  # Significant compression

    decompressed = Yay0.decompress(compressed)
    assert decompressed == original


def test_yay0_auto_dispatch():
    data = b"Testing generic dispatcher for Nintendo Yay0 compression format."
    comp = compress(data, fmt="yay0")
    assert comp.startswith(b"Yay0")

    decomp = decompress(comp)
    assert decomp == data


def test_yay0_invalid_headers():
    with pytest.raises(CompressionError):
        Yay0.decompress(b"SHORT")
    with pytest.raises(CompressionError):
        Yay0.decompress(b"NOPE\x00\x00\x00\x10\x00\x00\x00\x10\x00\x00\x00\x10")


def test_aplib_known_test_vector():
    # Canonical aPLib test vector
    test_packed = b'T\x00he quick\xecb\x0erown\xcef\xaex\x80jumps\xed\xe4veur`t?lazy\xead\xfeg\xc0\x00'
    expected = b"The quick brown fox jumps over the lazy dog"
    assert APLib.decompress(test_packed) == expected


def test_aplib_roundtrip():
    original = b"aPLib compression test. Repeating pattern: 1234567890 1234567890 1234567890 end!"
    compressed = APLib.compress(original, with_header=False)
    decompressed = APLib.decompress(compressed)
    assert decompressed == original


def test_aplib_with_ap32_header():
    original = b"Testing aPLib AP32 container header with full CRC and length checks." * 5
    compressed = APLib.compress(original, with_header=True)
    assert compressed.startswith(b"AP32")

    decompressed = APLib.decompress(compressed, strict=True)
    assert decompressed == original


def test_aplib_auto_dispatch():
    data = b"Testing generic compression dispatcher for aPLib."
    comp = compress(data, fmt="aplib")
    decomp = APLib.decompress(comp)
    assert decomp == data
