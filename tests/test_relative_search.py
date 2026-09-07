import struct
import pytest

from miorom.text.relative_search import RelativeSearcher, RelativeMatch
from miorom.text.charmap import CharMap


def test_relative_search_1byte():
    # Simulate a ROM buffer with text "DRAGON" encoded with a custom table shift (+0x25)
    # 'D'=0x44 -> 0x69, 'R'=0x52 -> 0x77, 'A'=0x41 -> 0x66, etc.
    shift = 0x25
    text = "DRAGON"
    encoded_dragon = bytes([(ord(c) + shift) & 0xFF for c in text])

    # Put dummy data before and after
    rom_data = b"\x00\x12\x34\x56" + encoded_dragon + b"\xFF\xAA\xBB\xCC"

    matches = RelativeSearcher.search_1byte(rom_data, "DRAGON")
    assert len(matches) == 1
    m = matches[0]
    assert m.offset == 4
    assert m.length == 6
    assert m.base_delta == shift
    assert m.matched_bytes == encoded_dragon

    # Build CharMap from match and decode
    cm = m.build_charmap()
    decoded = cm.decode(rom_data[4:10])
    assert decoded == "DRAGON"

    # Export to .tbl
    tbl_text = m.to_tbl()
    assert "69=D" in tbl_text
    assert "66=A" in tbl_text


def test_relative_search_2byte():
    # Simulate 2-byte text (16-bit Big-Endian) with shift = 0x1000
    shift = 0x1000
    text = "SWORD"
    encoded_be = bytearray()
    for c in text:
        val = (ord(c) + shift) & 0xFFFF
        encoded_be.extend(struct.pack(">H", val))

    rom_data = b"\x00\x00\x00\x00" + bytes(encoded_be) + b"\x00\x00"

    matches = RelativeSearcher.search(rom_data, "SWORD", mode="2byte_be")
    assert len(matches) == 1
    m = matches[0]
    assert m.offset == 4
    assert m.length == 10
    assert m.base_delta == shift

    # Build 2-byte CharMap
    cm = m.build_charmap()
    decoded = cm.decode(rom_data[4:14])
    assert decoded == "SWORD"
