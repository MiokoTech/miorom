import pytest
from miorom.core.bitfield import BitField, BitFieldSchema, BitFieldCodec


def test_bitfield_single_byte():
    # Schema: 3 bits ailment (0..7), 1 bit poison flag, 4 bits elemental (0..15) = 8 bits
    codec = BitFieldCodec([
        BitField("ailment", 3),
        BitField("poison", 1),
        BitField("element", 4),
    ], bit_order="msb")

    assert codec.byte_size == 1
    assert codec.total_bits == 8

    # ailment = 5 (0b101), poison = 1 (0b1), element = 9 (0b1001)
    # Binary: 101 1 1001 = 0xB9
    packed = codec.pack({"ailment": 5, "poison": 1, "element": 9})
    assert packed == bytes([0xB9])

    unpacked = codec.unpack(packed, bool_flags=True)
    assert unpacked["ailment"] == 5
    assert unpacked["poison"] is True
    assert unpacked["element"] == 9


def test_bitfield_cross_byte_boundary():
    # 20-bit record: HP (10 bits, 0..1023), MP (6 bits, 0..63), Level (4 bits, 0..15)
    # Total bytes: ceil(20/8) = 3 bytes
    codec = BitFieldCodec([
        ("hp", 10),
        ("mp", 6),
        ("level", 4),
    ], bit_order="msb")

    assert codec.byte_size == 3
    assert codec.total_bits == 20

    data = {"hp": 750, "mp": 45, "level": 12}
    packed = codec.pack(data)
    assert len(packed) == 3

    unpacked = codec.unpack(packed)
    assert unpacked["hp"] == 750
    assert unpacked["mp"] == 45
    assert unpacked["level"] == 12


def test_bitfield_signed_values():
    # Schema: 5-bit signed delta (-16..15), 3-bit unsigned count (0..7)
    codec = BitFieldCodec([
        BitField("delta", 5, signed=True),
        BitField("count", 3, signed=False),
    ], bit_order="msb")

    data = {"delta": -7, "count": 5}
    packed = codec.pack(data)
    assert len(packed) == 1

    unpacked = codec.unpack(packed)
    assert unpacked["delta"] == -7
    assert unpacked["count"] == 5


def test_bitfield_lsb_order():
    # 4 bits low, 4 bits high in LSB order
    codec = BitFieldCodec([
        ("low_nibble", 4),
        ("high_nibble", 4),
    ], bit_order="lsb")

    packed = codec.pack({"low_nibble": 0x3, "high_nibble": 0xA})
    assert packed == bytes([0xA3])

    unpacked = codec.unpack(packed)
    assert unpacked["low_nibble"] == 0x3
    assert unpacked["high_nibble"] == 0xA


def test_bitfield_pack_into_and_tables():
    codec = BitFieldCodec([
        ("id", 4),
        ("flag", 1),
        ("val", 3),
    ], bit_order="msb")

    records = [
        {"id": 1, "flag": 0, "val": 2},
        {"id": 2, "flag": 1, "val": 7},
        {"id": 3, "flag": 0, "val": 5},
    ]

    packed_all = codec.pack_all(records)
    assert len(packed_all) == 3

    unpacked_all = codec.unpack_all(packed_all)
    assert len(unpacked_all) == 3
    assert unpacked_all == records

    # In-place patching inside a ROM buffer
    rom_buffer = bytearray(b"\x00\x00\xFF\xFF\x00\x00")
    codec.pack_into(rom_buffer, offset=2, values={"id": 0xF, "flag": 1, "val": 0})
    unpacked_patched = codec.unpack(rom_buffer, offset=2)
    assert unpacked_patched["id"] == 0xF
    assert unpacked_patched["flag"] == 1
    assert unpacked_patched["val"] == 0


def test_bitfield_validation_errors():
    codec = BitFieldCodec([("small", 3)], bit_order="msb")

    # 3 bits unsigned max is 7; 8 should raise ValueError
    with pytest.raises(ValueError):
        codec.pack({"small": 8})

    # negative for unsigned should raise ValueError
    with pytest.raises(ValueError):
        codec.pack({"small": -1})
