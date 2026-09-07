import pytest
import struct
from miorom.platforms.gba.rom import GBARom
from miorom.platforms.iso.iso9660 import ISO9660


def test_gba_rom_header_and_checksum():
    # Build minimal dummy GBA header (192 bytes)
    header = bytearray(0xC0)
    # ARM branch
    header[0:4] = b"\x2E\x00\x00\xEA"
    # Logo
    header[0x04:0xA0] = GBARom.NINTENDO_LOGO
    # Title
    header[0xA0:0xAC] = b"POKEMON EMER"
    # Game code
    header[0xAC:0xB0] = b"BPEE"
    # Maker code
    header[0xB0:0xB2] = b"01"
    header[0xB2] = 0x96
    # Calculate checksum
    chk = 0
    for b in header[0xA0:0xBD]:
        chk = (chk - b) & 0xFF
    header[0xBD] = (chk - 0x19) & 0xFF

    rom_data = bytes(header) + b"FLASH1M_V102 backup data simulation"
    rom = GBARom(rom_data)

    assert rom.title == "POKEMON EMER"
    assert rom.game_code == "BPEE"
    assert rom.maker_code == "01"
    assert rom.is_header_checksum_valid() is True
    assert rom.is_logo_valid() is True
    assert "FLASH (1Mbit / 128KB)" in rom.detect_save_type()

    # Modify title and fix checksum
    rom.title = "MINISH CAP"
    assert rom.title == "MINISH CAP"
    assert rom.is_header_checksum_valid() is False
    rom.fix_header_checksum()
    assert rom.is_header_checksum_valid() is True


def test_iso9660_read_and_replace():
    # Construct a minimal valid ISO9660 image
    # Sector 0-15: System area (16 * 2048 = 32768 bytes)
    # Sector 16: PVD (2048 bytes)
    # Sector 17: Root Directory Sector (2048 bytes)
    # Sector 18: File 1 (TEST.TXT)
    sector_size = 2048
    iso_data = bytearray(sector_size * 20)

    # Setup PVD at sector 16
    pvd_offset = 16 * sector_size
    iso_data[pvd_offset : pvd_offset + 6] = b"\x01CD001"
    iso_data[pvd_offset + 6] = 1 # version
    iso_data[pvd_offset + 40 : pvd_offset + 50] = b"TEST_DISC "
    struct.pack_into("<I", iso_data, pvd_offset + 80, 20) # volume space size LE
    struct.pack_into(">I", iso_data, pvd_offset + 84, 20) # BE
    struct.pack_into("<H", iso_data, pvd_offset + 128, 2048) # logical block size LE
    struct.pack_into(">H", iso_data, pvd_offset + 130, 2048) # BE

    # Root dir record in PVD (offset 156)
    root_rec = pvd_offset + 156
    iso_data[root_rec] = 34
    struct.pack_into("<I", iso_data, root_rec + 2, 17) # root dir is at sector 17
    struct.pack_into("<I", iso_data, root_rec + 10, 2048) # root dir size 2048

    # Setup Root Directory Sector at sector 17
    root_dir_offset = 17 * sector_size
    # Directory entry 1: TEST.TXT;1 at sector 18, size 12 bytes
    file_lba = 18
    file_content = b"Hello ISO9660"
    file_name = b"TEST.TXT;1"

    rec_len = 33 + len(file_name)
    if rec_len % 2 != 0:
        rec_len += 1

    entry_offset = root_dir_offset
    iso_data[entry_offset] = rec_len
    struct.pack_into("<I", iso_data, entry_offset + 2, file_lba)
    struct.pack_into(">I", iso_data, entry_offset + 6, file_lba)
    struct.pack_into("<I", iso_data, entry_offset + 10, len(file_content))
    struct.pack_into(">I", iso_data, entry_offset + 14, len(file_content))
    iso_data[entry_offset + 25] = 0 # file (not dir)
    iso_data[entry_offset + 32] = len(file_name)
    iso_data[entry_offset + 33 : entry_offset + 33 + len(file_name)] = file_name

    # Write file content at sector 18
    iso_data[18 * sector_size : 18 * sector_size + len(file_content)] = file_content

    # Load ISO9660
    iso = ISO9660(bytes(iso_data))
    assert iso.volume_id.startswith("TEST_DISC")
    assert "TEST.TXT" in iso.list_files()
    assert iso.read_file("TEST.TXT") == b"Hello ISO9660"

    # Replace file with new content (in-place)
    iso.replace_file("TEST.TXT", b"Replaced Text")
    assert iso.read_file("TEST.TXT") == b"Replaced Text"

    # Replace file with huge content (requires sector reallocation at end of disc)
    big_content = b"EXPANDED DATA! " * 500 # ~7.5KB = 4 sectors
    iso.replace_file("TEST.TXT", big_content)
    assert iso.read_file("TEST.TXT") == big_content
    # Entry LBA should now be relocated to 20
    assert iso.get_entry("TEST.TXT").lba == 20
