import struct
import pytest
from miorom.debug.gdb_client import GDBEmulatorClient
from miorom.text.charmap import CharMap


def test_gdb_ram_search_bytes_and_boundaries():
    client = GDBEmulatorClient.with_mock(ram_size=64 * 1024, base_address=0x02000000)
    
    pattern = b"MIOKO"
    client.write_bytes(0x0200000E, pattern)
    client.write_bytes(0x02000030, pattern)

    matches = client.find_bytes_in_ram(pattern, 0x02000000, 0x02000050, chunk_size=16)
    assert matches == [0x0200000E, 0x02000030]

    # No match
    assert client.find_bytes_in_ram(b"NOTFOUND", 0x02000000, 0x02000050) == []
    # Empty pattern or invalid range
    assert client.find_bytes_in_ram(b"", 0x02000000, 0x02000050) == []
    assert client.find_bytes_in_ram(pattern, 0x02000050, 0x02000010) == []


def test_gdb_ram_search_string():
    client = GDBEmulatorClient.with_mock(ram_size=64 * 1024, base_address=0x02000000)
    client.write_bytes(0x02000100, "SaveGameData".encode("ascii"))

    matches = client.find_string_in_ram("SaveGameData", 0x02000000, 0x02000200)
    assert matches == [0x02000100]

    # With custom CharMap
    charmap = CharMap({b"\x81\x40": " ", b"\x82\x60": "A", b"\x82\x61": "B"})
    client.write_bytes(0x02000150, b"\x82\x60\x82\x61")
    matches_cm = client.find_string_in_ram("AB", 0x02000000, 0x02000200, charmap=charmap)
    assert matches_cm == [0x02000150]


def test_gdb_ram_search_pointers():
    client = GDBEmulatorClient.with_mock(ram_size=64 * 1024, base_address=0x02000000)
    target_addr = 0x02001234

    # 32-bit little endian pointer
    client.write_bytes(0x02000020, struct.pack("<I", target_addr))
    # 32-bit big endian pointer
    client.write_bytes(0x02000040, struct.pack(">I", target_addr))
    # 16-bit little endian pointer
    client.write_bytes(0x02000060, struct.pack("<H", 0x9ABC))

    le_matches = client.find_pointers_to_in_ram(target_addr, 0x02000000, 0x02000100, endian="<", pointer_size=4)
    assert le_matches == [0x02000020]

    be_matches = client.find_pointers_to_in_ram(target_addr, 0x02000000, 0x02000100, endian=">", pointer_size=4)
    assert be_matches == [0x02000040]

    h_matches = client.find_pointers_to_in_ram(0x9ABC, 0x02000000, 0x02000100, endian="<", pointer_size=2)
    assert h_matches == [0x02000060]


def test_gdb_dump_ram_range(tmp_path):
    client = GDBEmulatorClient.with_mock(ram_size=64 * 1024, base_address=0x02000000)
    client.write_bytes(0x02000000, b"HEADER_TEST_BYTES")

    dump_file = tmp_path / "ram_dump.bin"
    data = client.dump_ram_range(0x02000000, 17, output_path=str(dump_file))
    assert data == b"HEADER_TEST_BYTES"
    assert dump_file.read_bytes() == b"HEADER_TEST_BYTES"
