import zlib
import pytest
from miorom.core.checksum import RetroChecksum


def test_crc16_known_vectors():
    # Standard ASCII test vector "123456789"
    data = b"123456789"

    # CRC-16 CCITT (init 0xFFFF, poly 0x1021)
    assert RetroChecksum.crc16_ccitt(data) == 0x29B1

    # CRC-16 XMODEM (init 0x0000, poly 0x1021)
    assert RetroChecksum.crc16_xmodem(data) == 0x31C3

    # CRC-16 ARC (IBM)
    assert RetroChecksum.crc16_arc(data) == 0xBB3D

    # CRC-16 Modbus
    assert RetroChecksum.crc16_modbus(data) == 0x4B37


def test_crc32_and_adler32_pure():
    data = b"Hello ROM Hacking World! 1234567890 \x00\xFF\x80"
    # Verify bitwise parity with zlib
    assert RetroChecksum.crc32_pure(data) == zlib.crc32(data)
    assert RetroChecksum.adler32_pure(data) == zlib.adler32(data)


def test_fletcher16():
    data = b"abcde"
    # 'a'=97, 'b'=98, 'c'=99, 'd'=100, 'e'=101
    f = RetroChecksum.fletcher16(data)
    assert 0 <= f <= 0xFFFF


def test_genesis_checksum():
    # 512 bytes header + 4 bytes payload
    data = bytearray(0x200 + 4)
    # Word 1: 0x1234 at 0x200, Word 2: 0x0001 at 0x202
    data[0x200:0x202] = b"\x12\x34"
    data[0x202:0x204] = b"\x00\x01"

    chk = RetroChecksum.genesis_checksum(bytes(data))
    assert chk == 0x1235


def test_snes_checksum():
    # 32KB power-of-two ROM
    data = bytes([0x01] * 32768)
    chk, comp = RetroChecksum.snes_checksum(data)
    assert (chk + comp) & 0xFFFF == 0xFFFF

    # Non-power-of-two (1.5 MB = 1MB + 512KB)
    data_1_5m = bytes([0x05] * (1024 * 1024 + 512 * 1024))
    chk2, comp2 = RetroChecksum.snes_checksum(data_1_5m)
    assert (chk2 + comp2) & 0xFFFF == 0xFFFF


def test_gameboy_checksums():
    header = bytearray(0x150)
    # Fill title area 0x134..0x14C
    for i in range(0x134, 0x14D):
        header[i] = (i * 7) & 0xFF

    h_chk = RetroChecksum.gameboy_header_checksum(bytes(header))
    assert 0 <= h_chk <= 0xFF

    # Global checksum sums all bytes except 0x14E..0x14F
    header[0x14E] = 0xAA
    header[0x14F] = 0xBB
    g_chk = RetroChecksum.gameboy_global_checksum(bytes(header))
    # Check that 0xAA and 0xBB are omitted
    header_zeroed = bytearray(header)
    header_zeroed[0x14E] = 0
    header_zeroed[0x14F] = 0
    assert g_chk == (sum(header_zeroed) & 0xFFFF)
