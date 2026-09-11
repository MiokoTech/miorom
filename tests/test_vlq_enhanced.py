import pytest
from miorom.core.vlq import (
    VariableLengthIntCodec,
    encode_vlq,
    decode_vlq,
    encode_uleb128,
    decode_uleb128,
    encode_sleb128,
    decode_sleb128,
)


def test_sqlite_varint():
    test_values = [0, 1, 127, 128, 16383, 16384, 2097151, 2097152, (1 << 32) - 1, (1 << 62) - 1]
    for v in test_values:
        encoded = VariableLengthIntCodec.encode_sqlite_varint(v)
        decoded, consumed = VariableLengthIntCodec.decode_sqlite_varint(encoded)
        assert decoded == v
        assert consumed == len(encoded)


def test_zigzag():
    cases = [(0, 0), (-1, 1), (1, 2), (-2, 3), (2, 4), (-100, 199), (100, 200)]
    for signed_val, expected_zigzag in cases:
        assert VariableLengthIntCodec.zigzag_encode(signed_val) == expected_zigzag
        assert VariableLengthIntCodec.zigzag_decode(expected_zigzag) == signed_val


def test_module_shortcuts():
    vlq_bytes = encode_vlq(0x12345)
    val, consumed = decode_vlq(vlq_bytes)
    assert val == 0x12345
    assert consumed == len(vlq_bytes)

    uleb = encode_uleb128(624485)
    uval, uconsumed = decode_uleb128(uleb)
    assert uval == 624485
    assert uconsumed == len(uleb)

    sleb = encode_sleb128(-624485)
    sval, sconsumed = decode_sleb128(sleb)
    assert sval == -624485
    assert sconsumed == len(sleb)
