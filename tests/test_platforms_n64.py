import struct
from miorom.platforms.n64 import (
    N64ByteOrder,
    N64CIC,
    N64Header,
    N64Rom,
    calculate_n64_checksum,
    detect_byte_order,
    detect_cic,
    fix_n64_checksum,
    parse_byte_order,
    convert_endianness,
    convert_file_endianness,
    swap_from_big_endian,
    swap_to_big_endian,
    verify_n64_checksum,
)


def test_n64_byte_order_detection_and_swap():
    # Big-Endian (.z64)
    z64_data = b"\x80\x37\x12\x40\x11\x22\x33\x44"
    assert detect_byte_order(z64_data) == N64ByteOrder.BIG_ENDIAN

    # Byte-swapped (.v64)
    v64_data = b"\x37\x80\x40\x12\x22\x11\x44\x33"
    assert detect_byte_order(v64_data) == N64ByteOrder.BYTE_SWAPPED

    # Little-Endian (.n64)
    n64_data = b"\x40\x12\x37\x80\x44\x33\x22\x11"
    assert detect_byte_order(n64_data) == N64ByteOrder.LITTLE_ENDIAN

    # Swapping to big endian
    assert swap_to_big_endian(v64_data) == z64_data
    assert swap_to_big_endian(n64_data) == z64_data

    # Swapping from big endian
    assert swap_from_big_endian(z64_data, N64ByteOrder.BYTE_SWAPPED) == v64_data
    assert swap_from_big_endian(z64_data, N64ByteOrder.LITTLE_ENDIAN) == n64_data


def test_n64_header_and_checksum():
    # Build minimal valid N64 header
    header_raw = bytearray(0x40)
    header_raw[0:4] = b"\x80\x37\x12\x40"
    struct.pack_into(">IIIII", header_raw, 0x04, 0x0F, 0x80000400, 0x1444, 0, 0)
    header_raw[0x20:0x34] = b"SUPER MARIO 64      "
    header_raw[0x3B] = ord("N")
    header_raw[0x3C:0x3E] = b"SM"
    header_raw[0x3E] = ord("E")
    header_raw[0x3F] = 0

    header = N64Header.parse(bytes(header_raw))
    assert header.title == "SUPER MARIO 64"
    assert header.game_code == "SM"
    assert header.country_code == "E"
    assert header.version == 0
    assert header.entrypoint == 0x80000400

    # Test full ROM with checksum calculation
    # Dummy ROM: 0x1000 header/bootcode + 0x100000 payload
    rom_buf = bytearray(header_raw)
    rom_buf.extend(b"\x00" * (0x101000 - len(rom_buf)))

    # Calculate checksum with 6102
    crc1, crc2 = calculate_n64_checksum(bytes(rom_buf), N64CIC.CIC_6102_7101)
    assert crc1 == 0xF8CA4DDC  # Known constant for zeroed 1MB buffer with CIC 6102

    # Fix checksum in ROM
    patched = fix_n64_checksum(bytes(rom_buf), N64CIC.CIC_6102_7101)
    assert verify_n64_checksum(patched, N64CIC.CIC_6102_7101) is True

    # Test N64Rom wrapper
    rom = N64Rom(bytes(rom_buf))
    assert rom.verify_checksum() is False
    rom.recalculate_checksum()
    assert rom.verify_checksum() is True
    assert rom.header.crc1 == 0xF8CA4DDC

    # Test exporting to .v64 and re-opening
    v64_bytes = rom.to_bytes(N64ByteOrder.BYTE_SWAPPED)
    assert detect_byte_order(v64_bytes) == N64ByteOrder.BYTE_SWAPPED
    rom_from_v64 = N64Rom(v64_bytes)
    assert rom_from_v64.verify_checksum() is True
    assert rom_from_v64.header.title == "SUPER MARIO 64"


def test_n64_endianness_conversion_helpers():
    # Test alias parsing
    assert parse_byte_order("z64") == N64ByteOrder.BIG_ENDIAN
    assert parse_byte_order(".z64") == N64ByteOrder.BIG_ENDIAN
    assert parse_byte_order("big") == N64ByteOrder.BIG_ENDIAN
    assert parse_byte_order("v64") == N64ByteOrder.BYTE_SWAPPED
    assert parse_byte_order("byteswapped") == N64ByteOrder.BYTE_SWAPPED
    assert parse_byte_order("n64") == N64ByteOrder.LITTLE_ENDIAN
    assert parse_byte_order("little") == N64ByteOrder.LITTLE_ENDIAN

    z64_data = b"\x80\x37\x12\x40\x11\x22\x33\x44"
    v64_data = b"\x37\x80\x40\x12\x22\x11\x44\x33"
    n64_data = b"\x40\x12\x37\x80\x44\x33\x22\x11"

    # Direct conversions with aliases
    assert convert_endianness(z64_data, "v64") == v64_data
    assert convert_endianness(v64_data, "n64") == n64_data
    assert convert_endianness(n64_data, "big") == z64_data
    assert convert_endianness(v64_data, "byteswapped") == v64_data


def test_n64_stream_convert_file(tmp_path):
    z64_data = b"\x80\x37\x12\x40\x00\x00\x00\x0F" * 1024  # 8KB
    src_file = tmp_path / "game.z64"
    dst_file = tmp_path / "game.v64"
    src_file.write_bytes(z64_data)

    src_order, dst_order = convert_file_endianness(src_file, dst_file, target_order="v64", chunk_size=512)
    assert src_order == N64ByteOrder.BIG_ENDIAN
    assert dst_order == N64ByteOrder.BYTE_SWAPPED

    converted_bytes = dst_file.read_bytes()
    assert len(converted_bytes) == len(z64_data)
    assert detect_byte_order(converted_bytes) == N64ByteOrder.BYTE_SWAPPED

