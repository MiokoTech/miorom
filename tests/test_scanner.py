import struct
import pytest
from miorom.core.scanner import StringScanner, PointerScanner, FoundString
from miorom.text.charmap import CharMap


def test_string_scanner_ascii():
    data = b"\x00\x00\x00Hello World\x00\x01\x02\x03Goodbye World!\x00\xFF\xFF"
    strings = StringScanner.scan_strings(data, min_length=4, encoding="ascii")

    assert len(strings) == 2
    assert strings[0].text == "Hello World"
    assert strings[0].offset == 3
    assert strings[1].text == "Goodbye World!"


def test_string_group_blocks():
    data = bytearray(500)
    # Block 1 at 0x20
    data[0x20:0x27] = b"Line 1\x00"
    data[0x27:0x2E] = b"Line 2\x00"
    # Block 2 far away at 0x150
    data[0x150:0x157] = b"Line 3\x00"

    strings = StringScanner.scan_strings(bytes(data), min_length=4)
    assert len(strings) == 3

    blocks = StringScanner.group_into_blocks(strings, max_gap=32)
    assert len(blocks) == 2
    assert blocks[0].start_offset == 0x20
    assert len(blocks[0].strings) == 2
    assert blocks[1].start_offset == 0x150
    assert len(blocks[1].strings) == 1


def test_pointer_scanner_little_endian():
    # Build a simulated ROM:
    # 0x00 - 0x1F: Pointer table (8 pointers x 4 bytes = 32 bytes)
    # 0x20 - 0x100: Strings
    rom = bytearray(256)

    # Strings at 0x50, 0x60, 0x70, 0x80, 0x90
    string_offsets = [0x50, 0x60, 0x70, 0x80, 0x90]
    for i, off in enumerate(string_offsets):
        s = f"Dialogue {i}\x00".encode("ascii")
        rom[off:off+len(s)] = s

    # Write pointer table at 0x10 (stride 4, little endian)
    table_offset = 0x10
    for i, off in enumerate(string_offsets):
        rom[table_offset + i*4 : table_offset + (i+1)*4] = struct.pack("<I", off)

    strings = StringScanner.scan_strings(bytes(rom), min_length=4)
    found_offsets = [s.offset for s in strings]

    tables = PointerScanner.find_pointer_tables(
        data=bytes(rom),
        target_offsets=found_offsets,
        strides=(4,),
        endians=("<",),
        min_pointers=4
    )

    assert len(tables) >= 1
    best_table = tables[0]
    assert best_table.table_offset == table_offset
    assert best_table.count == 5
    assert best_table.endian == "<"
    assert best_table.stride == 4


def test_pointer_scanner_big_endian_with_base():
    # Wii / GameCube scenario: RAM Base 0x80000000
    rom = bytearray(b"\xFF" * 512)
    ram_base = 0x80000000

    target_offsets = [0x100, 0x120, 0x140, 0x160, 0x180]
    for off in target_offsets:
        s = b"Test String\x00"
        rom[off:off+len(s)] = s

    table_offset = 0x40
    for i, off in enumerate(target_offsets):
        ptr_val = off - 0x100  # Relative pointer to section base 0x100!
        rom[table_offset + i*4 : table_offset + (i+1)*4] = struct.pack(">I", ptr_val)

    tables = PointerScanner.find_pointer_tables(
        data=bytes(rom),
        target_offsets=target_offsets,
        strides=(4,),
        endians=(">",),
        base_offsets=[0x100],
        min_pointers=4
    )

    assert len(tables) >= 1
    assert tables[0].table_offset == table_offset
    assert tables[0].base_offset == 0x100
    assert tables[0].count == 5


def test_string_scanner_charmap(tmp_path):
    tbl_file = tmp_path / "custom.tbl"
    tbl_file.write_text("80=A\n81=B\n82=C\n83=D\n84=E\n00=<END>\n", encoding="utf-8")
    charmap = CharMap.from_file(str(tbl_file))

    data = b"\xFF\xFF\x80\x81\x82\x83\x84\x00\xFF"
    strings = StringScanner.scan_strings(data, min_length=4, charmap=charmap)

    assert len(strings) == 1
    assert strings[0].text == "ABCDE<END>"
    assert strings[0].offset == 2
