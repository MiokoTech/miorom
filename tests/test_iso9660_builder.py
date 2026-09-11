import os
import tempfile
import pytest

from miorom.platforms.iso.builder import Iso9660Builder, normalize_iso_name
from miorom.platforms.iso.iso9660 import ISO9660
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
