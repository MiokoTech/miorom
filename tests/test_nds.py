import struct
import pytest
from miorom.platforms.nds.narc import NARCArchive
from miorom.platforms.nds.rom import NDSRom


def test_narc_pack_and_unpack_roundtrip():
    file1 = b"Hello from NARC file 1!"
    file2 = b"Binary asset payload \x00\xFF\xAA\x55" * 10
    file3 = b"Script dialogue text lines."

    files = [file1, file2, file3]

    # Pack files
    narc_bytes = NARCArchive.pack_files(files)
    assert NARCArchive.is_narc(narc_bytes)

    # Unpack entries
    entries = NARCArchive.unpack_entries(narc_bytes)
    assert len(entries) == 3
    assert entries[0].data == file1
    assert entries[1].data == file2
    assert entries[2].data == file3


def test_nds_rom_header_parse():
    # Construct synthetic 0x400 byte NDS ROM header
    raw = bytearray(0x400)
    raw[0:12] = b"RUNEFACTORY\x00"
    raw[12:16] = b"ARFE"
    raw[16:18] = b"01"

    # ARM9 offset & size
    struct.pack_into("<I", raw, 0x20, 0x200)   # arm9_offset = 0x200
    struct.pack_into("<I", raw, 0x2C, 0x80)    # arm9_size = 0x80

    # FAT offset & size
    struct.pack_into("<I", raw, 0x48, 0x280)   # fat_offset = 0x280
    struct.pack_into("<I", raw, 0x4C, 16)      # fat_size = 16 (2 entries)

    # Put 2 entries in FAT (0x280)
    struct.pack_into("<II", raw, 0x280, 0x300, 0x320)  # File 0: 0x300-0x320 (32 bytes)
    struct.pack_into("<II", raw, 0x288, 0x320, 0x350)  # File 1: 0x320-0x350 (48 bytes)

    # Put file data
    raw[0x300:0x320] = b"F" * 32
    raw[0x320:0x350] = b"G" * 48

    rom = NDSRom(bytes(raw))
    assert rom.title == "RUNEFACTORY"
    assert rom.game_code == "ARFE"
    assert rom.arm9_offset == 0x200
    assert rom.arm9_size == 0x80

    files = rom.list_files()
    assert len(files) == 2
    assert files[0].size == 32
    assert files[1].size == 48

    assert rom.get_file(0) == b"F" * 32
    assert rom.get_file(1) == b"G" * 48


def test_nds_append_file_preserves_downstream():
    raw = bytearray(0x400)
    raw[0:12] = b"SAMPLE_GAME\x00"
    struct.pack_into("<I", raw, 0x20, 0x200)   # arm9_offset = 0x200
    struct.pack_into("<I", raw, 0x2C, 0x80)    # arm9_size = 0x80
    struct.pack_into("<I", raw, 0x48, 0x280)   # fat_offset = 0x280
    struct.pack_into("<I", raw, 0x4C, 16)      # fat_size = 16 (2 entries)

    # Put 2 entries in FAT
    struct.pack_into("<II", raw, 0x280, 0x300, 0x320)  # File 0: 0x300-0x320 (32 bytes)
    struct.pack_into("<II", raw, 0x288, 0x320, 0x350)  # File 1: 0x320-0x350 (48 bytes)
    raw[0x300:0x320] = b"A" * 32
    raw[0x320:0x350] = b"B" * 48

    rom = NDSRom(bytes(raw))
    rom.fix_header_checksum()
    assert rom.verify_header_checksum()

    # Append new large data to File 0
    large_data = b"EXTENDED_FILE_0_CONTENT_" * 30
    new_offset = rom.append_file(0, large_data, alignment=512)

    # Offset must be sector-aligned to 512 bytes at EOF
    assert new_offset >= 0x400
    assert new_offset % 512 == 0

    # File 0 must return new data
    assert rom.get_file(0) == large_data

    # File 1 must remain completely untouched at original offset 0x320!
    assert rom.get_file(1) == b"B" * 48
    fat_f1_start, fat_f1_end = struct.unpack_from("<II", rom.data, 0x288)
    assert fat_f1_start == 0x320
    assert fat_f1_end == 0x350

    # Header checksum must still be valid
    assert rom.verify_header_checksum()


def test_nds_ram_translation_and_arm9_patching():
    raw = bytearray(0x600)
    struct.pack_into("<I", raw, 0x20, 0x200)       # arm9_offset = 0x200
    struct.pack_into("<I", raw, 0x28, 0x02000800)  # arm9_ram_address = 0x02000800
    struct.pack_into("<I", raw, 0x2C, 0x200)       # arm9_size = 0x200

    # Place code in ARM9
    raw[0x200:0x204] = b"\x12\x34\x56\x78"

    rom = NDSRom(bytes(raw))

    # RAM to file offset
    assert rom.ram_to_file_offset(0x02000800) == 0x200
    assert rom.ram_to_file_offset(0x02000850) == 0x250

    # File to RAM offset
    assert rom.file_to_ram_offset(0x200) == 0x02000800
    assert rom.file_to_ram_offset(0x250) == 0x02000850

    # Out of range checks
    with pytest.raises(ValueError):
        rom.ram_to_file_offset(0x03000000)
    with pytest.raises(ValueError):
        rom.file_to_ram_offset(0x100)

    # Read ARM9
    assert rom.read_arm9(0x02000800, 4) == b"\x12\x34\x56\x78"

    # Patch ARM9 with uint32
    rom.patch_arm9(0x02000800, 0xEA000010)
    assert rom.read_arm9(0x02000800, 4) == b"\x10\x00\x00\xEA"

    # Patch ARM9 with bytes
    rom.patch_arm9(0x02000810, b"\xAA\xBB\xCC\xDD")
    assert rom.read_arm9(0x02000810, 4) == b"\xAA\xBB\xCC\xDD"


def test_nds_overlay_parsing():
    raw = bytearray(0x800)
    struct.pack_into("<I", raw, 0x20, 0x200)       # arm9_offset = 0x200
    struct.pack_into("<I", raw, 0x28, 0x02000800)  # arm9_ram = 0x02000800
    struct.pack_into("<I", raw, 0x2C, 0x100)       # arm9_size = 0x100

    # Overlay table at 0x300, size 32 (1 entry)
    struct.pack_into("<I", raw, 0x50, 0x300)       # arm9_overlay_offset
    struct.pack_into("<I", raw, 0x54, 32)          # arm9_overlay_size

    # FAT at 0x350, size 8 (1 entry)
    struct.pack_into("<I", raw, 0x48, 0x350)
    struct.pack_into("<I", raw, 0x4C, 8)
    struct.pack_into("<II", raw, 0x350, 0x400, 0x440)  # File 0: 0x400-0x440 (64 bytes)
    raw[0x400:0x440] = b"OVERLAY_PAYLOAD_" * 4

    # Pack 32-byte overlay entry at 0x300:
    # id=5, ram_addr=0x02100000, ram_sz=64, bss_sz=128, sinit=0, sinit_end=0, file_id=0, flags=0
    struct.pack_into("<IIIIIIII", raw, 0x300, 5, 0x02100000, 64, 128, 0, 0, 0, 0)

    rom = NDSRom(bytes(raw))
    overlays = rom.list_overlays("arm9")
    assert len(overlays) == 1
    assert overlays[0].id == 5
    assert overlays[0].ram_address == 0x02100000
    assert overlays[0].ram_size == 64
    assert overlays[0].bss_size == 128
    assert overlays[0].file_id == 0

    # Get overlay binary
    data = rom.get_overlay_binary(5, "arm9")
    assert data == b"OVERLAY_PAYLOAD_" * 4


def test_nds_extract_and_repack_helpers(tmp_path):
    from miorom.platforms.nds import extract_rom, repack_rom, extract_nds_rom, repack_nds_rom
    assert extract_rom is extract_nds_rom
    assert repack_rom is repack_nds_rom


def test_nds_patch_arm9_vaddr():
    raw = bytearray(0x800)
    struct.pack_into("<I", raw, 0x20, 0x200)       # arm9_offset = 0x200
    struct.pack_into("<I", raw, 0x28, 0x02000000)  # arm9_ram = 0x02000000
    struct.pack_into("<I", raw, 0x2C, 0x200)       # arm9_size = 0x200

    # Place an original instruction at virtual RAM 0x02000100 (file offset 0x300)
    # E1DD10F8: ldrsh r1, [sp, #8]
    struct.pack_into("<I", raw, 0x300, 0xE1DD10F8)

    rom = NDSRom(bytes(raw))
    # Test vaddr offset mapping
    assert rom.get_arm9_vaddr_offset(0x02000100) == 0x300

    # Test patch with wrong expected fails
    assert not rom.patch_arm9_vaddr(0x02000100, 0xE1DD10B8, expected=0x12345678)

    # Test patch with correct expected succeeds
    success = rom.patch_arm9_vaddr(0x02000100, 0xE1DD10B8, expected=0xE1DD10F8)
    assert success
    assert struct.unpack_from("<I", rom.data, 0x300)[0] == 0xE1DD10B8
    assert rom.verify_header_checksum()


def test_nds_patch_arm7_vaddr():
    raw = bytearray(0x800)
    struct.pack_into("<I", raw, 0x30, 0x400)       # arm7_offset = 0x400
    struct.pack_into("<I", raw, 0x38, 0x02380000)  # arm7_ram = 0x02380000
    struct.pack_into("<I", raw, 0x3C, 0x100)       # arm7_size = 0x100

    # Place instruction at 0x02380020 (file offset 0x420)
    struct.pack_into("<I", raw, 0x420, 0xDEADBEEF)

    rom = NDSRom(bytes(raw))
    assert rom.get_arm7_vaddr_offset(0x02380020) == 0x420
    assert rom.patch_arm7_vaddr(0x02380020, 0xCAFEBABE, expected=0xDEADBEEF)
    assert struct.unpack_from("<I", rom.data, 0x420)[0] == 0xCAFEBABE



