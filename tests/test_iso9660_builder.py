import os
import tempfile
import pytest

from miorom.platforms.iso.builder import (
    Iso9660Builder,
    normalize_iso_name,
    pack_both_u16,
    pack_both_u32,
)
from miorom.platforms.iso.iso9660 import ISO9660, ISODirectoryRecordStruct, ISOPvdStruct
from miorom.rom.handlers.iso9660 import Iso9660RomHandler


def test_iso_name_normalization():
    assert normalize_iso_name("system.cnf") == "SYSTEM.CNF;1"
    assert normalize_iso_name("GAME.BIN;1") == "GAME.BIN;1"
    assert normalize_iso_name("script", is_dir=True) == "SCRIPT"
    assert normalize_iso_name("sub/dir", is_dir=True) == "SUBDIR"


def test_iso9660_builder_memory_synthesis():
    builder = Iso9660Builder(volume_id="MY_GAME_MOD", system_id="PLAYSTATION")

    # Add custom 32KB boot system area
    sys_boot = b"PSX_BOOT_SECTOR_TEST" * 100
    builder.set_system_area(sys_boot)

    # Add files at root and subdirectories
    cnf_content = b"BOOT2 = cdrom0:\\SLUS_123.45;1\nVER = 1.00\n"
    exe_content = b"\x7FELF_FAKE_EXEC_BINARY" * 200
    text_content = b"Dialogue string table payload in Japanese/English\n" * 10

    builder.add_file("SYSTEM.CNF", cnf_content)
    builder.add_file("SLUS_123.45", exe_content)
    builder.add_file("DATA/MSG/DIALOGUE.DAT", text_content)

    iso_bytes = builder.build()
    assert len(iso_bytes) % 2048 == 0

    # Verify with ISO9660 parser
    iso = ISO9660(iso_bytes)
    assert iso.volume_id.strip() == "MY_GAME_MOD"

    file_list = iso.list_files()
    assert "SYSTEM.CNF" in file_list
    assert "SLUS_123.45" in file_list
    assert "DATA/MSG/DIALOGUE.DAT" in file_list

    # Read contents back
    assert iso.read_file("SYSTEM.CNF") == cnf_content
    assert iso.read_file("SLUS_123.45") == exe_content
    assert iso.read_file("DATA/MSG/DIALOGUE.DAT") == text_content

    # Check system area was preserved
    assert iso_bytes[:len(sys_boot)] == sys_boot


def test_iso9660_builder_filesystem_roundtrip():
    with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as out_dir:
        # Populate source tree
        os.makedirs(os.path.join(src_dir, "SECTOR1", "SUB"))
        with open(os.path.join(src_dir, "ROOT.TXT"), "wb") as f:
            f.write(b"ROOT_FILE_DATA")
        with open(os.path.join(src_dir, "SECTOR1", "SUB", "NESTED.BIN"), "wb") as f:
            f.write(b"NESTED_PAYLOAD_BYTES" * 50)

        # Build ISO to disk
        iso_file = os.path.join(out_dir, "game.iso")
        builder = Iso9660Builder(volume_id="FS_DISC")
        builder.add_from_fs(src_dir)
        builder.build_to_file(iso_file)

        assert os.path.exists(iso_file)

        # Unpack with Iso9660RomHandler
        unpack_dir = os.path.join(out_dir, "unpacked")
        handler = Iso9660RomHandler()
        assert handler.can_handle(b"", filepath=iso_file) is True

        with open(iso_file, "rb") as f:
            data = f.read()

        meta = handler.unpack(data, unpack_dir)
        assert meta["volume_id"].strip() == "FS_DISC"

        # Check unpacked files
        root_txt = os.path.join(unpack_dir, "root", "ROOT.TXT")
        nested_bin = os.path.join(unpack_dir, "root", "SECTOR1", "SUB", "NESTED.BIN")
        assert os.path.exists(root_txt)
        assert os.path.exists(nested_bin)

        with open(root_txt, "rb") as f:
            assert f.read() == b"ROOT_FILE_DATA"
        with open(nested_bin, "rb") as f:
            assert f.read() == b"NESTED_PAYLOAD_BYTES" * 50


def test_pack_both_endian_standards_compliance():
    # ECMA-119 Section 7.2.3: 16-bit both-byte orders (LE then BE)
    assert pack_both_u16(1) == b"\x01\x00\x00\x01"
    assert pack_both_u16(2048) == b"\x00\x08\x08\x00"
    assert pack_both_u16(0x1234) == b"\x34\x12\x12\x34"

    # ECMA-119 Section 7.3.3: 32-bit both-byte orders (LE then BE)
    assert pack_both_u32(1) == b"\x01\x00\x00\x00\x00\x00\x00\x01"
    assert pack_both_u32(20) == b"\x14\x00\x00\x00\x00\x00\x00\x14"
    assert pack_both_u32(0x12345678) == b"\x78\x56\x34\x12\x12\x34\x56\x78"


def test_iso_pvd_and_directory_records_both_endian_symmetry():
    builder = Iso9660Builder(volume_id="BOTH_ENDIAN_TEST")
    builder.add_file("FILE_A.DAT", b"PAYLOAD_A" * 100)
    builder.add_file("SUB/FILE_B.BIN", b"PAYLOAD_B" * 200)

    iso_bytes = builder.build()
    assert len(iso_bytes) % 2048 == 0

    # Validate Primary Volume Descriptor (PVD at sector 16)
    pvd = ISOPvdStruct.from_bytes(iso_bytes, offset=16 * 2048)
    assert pvd.volume_space_size.little == pvd.volume_space_size.big
    assert pvd.volume_space_size.little > 0
    assert pvd.logical_block_size == pvd.logical_block_size_big == 2048

    # Validate Root Directory Record in PVD
    root_rec = ISODirectoryRecordStruct.from_bytes(pvd.root_directory, offset=0)
    assert root_rec.lba.little == root_rec.lba.big
    assert root_rec.size.little == root_rec.size.big
    assert root_rec.volume_sequence_number == root_rec.volume_sequence_number_big == 1

    # Traverse directory records in Root Directory sector
    root_sector_offset = root_rec.lba.little * 2048
    offset = root_sector_offset
    sector_end = root_sector_offset + 2048

    records_checked = 0
    while offset < sector_end:
        rec_len = iso_bytes[offset]
        if rec_len == 0:
            break
        rec = ISODirectoryRecordStruct.from_bytes(iso_bytes, offset=offset)
        assert rec.lba.little == rec.lba.big
        assert rec.size.little == rec.size.big
        assert rec.volume_sequence_number == rec.volume_sequence_number_big
        records_checked += 1
        offset += rec_len

    assert records_checked >= 3  # ., .., FILE_A.DAT, SUB

