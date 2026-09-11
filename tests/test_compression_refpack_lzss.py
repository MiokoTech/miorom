import pytest
from miorom.compression.refpack import RefPack
from miorom.compression.lzss import LZSS
from miorom.compression import compress, decompress
from miorom.errors import CompressionError


def test_refpack_roundtrip_simple_and_repetitive():
    data = b"THE_QUICK_BROWN_FOX_JUMPS_OVER_THE_LAZY_DOG" * 20
    comp = RefPack.compress(data)

    assert len(comp) < len(data)
    assert comp.startswith(b"\x10\xfb")

    decomp = RefPack.decompress(comp)
    assert decomp == data


def test_refpack_various_patterns():
    # Long repetitive sequences to trigger 3-byte matches and large literal runs
    pattern = (b"ABCDEFG123456789" * 30) + (b"RANDOM_TAIL_LITERALS_12345" * 5)
    comp = RefPack.compress(pattern)
    decomp = RefPack.decompress(comp)
    assert decomp == pattern


def test_refpack_dispatcher_integration():
    data = b"REFPACK_DISPATCHER_INTEGRATION_TEST_DATA" * 15
    comp = compress(data, fmt="refpack")
    decomp = decompress(comp)
    assert decomp == data


def test_refpack_error_handling():
    with pytest.raises(CompressionError):
        RefPack.decompress(b"TINY")

    with pytest.raises(CompressionError):
        RefPack.decompress(b"\x00\x00\x00\x00\x00")

    # Corrupt backreference offset
    corrupted = bytearray(b"\x10\xfb\x00\x00\x10")
    corrupted.extend(b"\x00\xFF")  # 2-byte command with huge offset on empty buffer
    with pytest.raises(CompressionError):
        RefPack.decompress(bytes(corrupted))


def test_lzss_roundtrip_okumura():
    data = b"TO_BE_OR_NOT_TO_BE_THAT_IS_THE_QUESTION_WHETHER_TIS_NOBLER" * 10
    comp = LZSS.compress(data)

    assert len(comp) < len(data)

    decomp = LZSS.decompress(comp, uncompressed_size=len(data))
    assert decomp == data


def test_lzss_empty_and_short():
    assert LZSS.compress(b"") == b""
    assert LZSS.decompress(b"") == b""

    short_data = b"MioROM"
    comp = LZSS.compress(short_data)
    decomp = LZSS.decompress(comp, uncompressed_size=len(short_data))
    assert decomp == short_data


def test_lzss_custom_fill():
    data = b"TESTING_CUSTOM_BUFFER_INITIAL_FILL" * 8
    comp = LZSS.compress(data, init_fill=0x00)
    decomp = LZSS.decompress(comp, uncompressed_size=len(data), init_fill=0x00)
    assert decomp == data


def test_lzss_named_compress_dispatch():
    data = b"DISPATCH_LZSS_GENERIC_DATA_STREAM" * 12
    comp = compress(data, fmt="lzss")
    assert len(comp) > 0
    decomp = LZSS.decompress(comp, uncompressed_size=len(data))
    assert decomp == data
