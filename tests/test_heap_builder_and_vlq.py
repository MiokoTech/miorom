import pytest
from miorom.core.heap_builder import StringHeapBuilder, HeapBuildResult
from miorom.core.vlq import VariableLengthIntCodec
from miorom.core.string_carver import StringPoolCarver, CarvedString


def test_string_heap_builder_sequence():
    strings = ["Halo", "Dunia", "Petualang"]
    res = StringHeapBuilder.build(
        items=strings,
        alignment=4,
        start_offset=0x10,
    )
    assert len(res.offsets) == 3
    assert res.offsets[0] == 0x10
    # "Halo\0" = 5 bytes -> 0x10 + 5 = 0x15 -> aligned up to 4 = 0x18
    assert res.offsets[1] == 0x18
    # "Dunia\0" = 6 bytes -> 0x18 + 6 = 0x1E -> aligned up to 4 = 0x20
    assert res.offsets[2] == 0x20

    # Read back from data
    data = res.data
    s0 = data[res.offsets[0] - 0x10 : data.find(b"\x00", res.offsets[0] - 0x10)].decode("utf-8")
    assert s0 == "Halo"


def test_string_heap_builder_dict():
    items = {"item_1": "Pedang", "item_2": "Perisai"}
    res = StringHeapBuilder.build(items=items, alignment=2)
    assert "item_1" in res.offset_map
    assert "item_2" in res.offset_map
    assert res.offset_map["item_1"] == 0
    assert res.offset_map["item_2"] > 0


def test_variable_length_int_codec():
    # VLQ (MIDI-style)
    test_values = [0, 64, 127, 128, 300, 16384, 0x1FFFFF]
    for val in test_values:
        encoded = VariableLengthIntCodec.encode_vlq(val)
        decoded, consumed = VariableLengthIntCodec.decode_vlq(encoded)
        assert decoded == val
        assert consumed == len(encoded)

    # LEB128 unsigned
    for val in [0, 1, 127, 128, 65535, 1000000]:
        enc = VariableLengthIntCodec.encode_leb128(val, signed=False)
        dec, consumed = VariableLengthIntCodec.decode_leb128(enc, signed=False)
        assert dec == val
        assert consumed == len(enc)

    # LEB128 signed
    for val in [-1, -64, -128, -500, 0, 127, 500]:
        enc = VariableLengthIntCodec.encode_leb128(val, signed=True)
        dec, consumed = VariableLengthIntCodec.decode_leb128(enc, signed=True)
        assert dec == val
        assert consumed == len(enc)


def test_string_pool_carver():
    buf = bytearray(b"\x00\xFF\x00Halo Dunia\x00Selamat Pagi\x00\x00\x00")
    carved = StringPoolCarver.carve_null_terminated(bytes(buf), min_len=3)
    texts = [c.text for c in carved]
    assert "Halo Dunia" in texts
    assert "Selamat Pagi" in texts

    # Pascal string carving: 1-byte length prefix
    pascal_buf = bytearray([0x04, ord("K"), ord("o"), ord("t"), ord("a"), 0x00])
    carved_pascal = StringPoolCarver.carve_pascal_strings(bytes(pascal_buf), min_len=2, length_size=1)
    assert len(carved_pascal) == 1
    assert carved_pascal[0].text == "Kota"
