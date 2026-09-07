import tempfile
import os
from miorom.archive import ArchiveContainer, ArchiveEntry, VirtualFileSystem


def test_vfs_basic_file_and_dir_operations():
    vfs = VirtualFileSystem()

    # Create directories and files
    vfs.mkdir("/game/scripts")
    vfs.write("/game/scripts/event01.bin", b"\x01\x02\x03\x04")
    vfs.write("/game/title.png", b"PNG_DATA")

    assert vfs.exists("/game/scripts/event01.bin") is True
    assert vfs.is_file("/game/scripts/event01.bin") is True
    assert vfs.is_dir("/game/scripts") is True
    assert vfs.exists("/game/nonexistent") is False

    # Read content
    assert vfs.read("/game/scripts/event01.bin") == b"\x01\x02\x03\x04"
    assert vfs.read("/game/title.png") == b"PNG_DATA"

    # In-place write / patch
    file_node = vfs.open("/game/scripts/event01.bin", "rb+")
    file_node.write(b"\x99", offset=1)
    assert vfs.read("/game/scripts/event01.bin") == b"\x01\x99\x03\x04"

    # Directory listing
    children = vfs.list_dir("/game")
    assert "scripts" in children
    assert "title.png" in children


def test_vfs_mounting_and_archive_export():
    vfs = VirtualFileSystem()

    # Mount dictionary of files
    vfs.mount("/audio", {
        "bgm/track1.xa": b"TRACK1_DATA",
        "sfx/jump.wav": b"JUMP_SFX",
    })

    assert vfs.exists("/audio/bgm/track1.xa") is True
    assert vfs.read("/audio/bgm/track1.xa") == b"TRACK1_DATA"
    assert vfs.read("/audio/sfx/jump.wav") == b"JUMP_SFX"

    # Mount another VFS
    sub_vfs = VirtualFileSystem()
    sub_vfs.write("/boss.bin", b"BOSS_DATA")
    vfs.mount("/data/enemies", sub_vfs)

    assert vfs.read("/data/enemies/boss.bin") == b"BOSS_DATA"

    # Export to ArchiveContainer
    container = vfs.to_archive_container()
    names = [entry.name for entry in container.entries]
    assert "audio/bgm/track1.xa" in names
    assert "data/enemies/boss.bin" in names

    # Disk export and import
    with tempfile.TemporaryDirectory() as tmpdir:
        vfs.export_to_disk(tmpdir)
        assert os.path.isfile(os.path.join(tmpdir, "audio", "bgm", "track1.xa"))

        # Import into fresh VFS
        imported_vfs = VirtualFileSystem()
        imported_vfs.import_from_disk(tmpdir)
        assert imported_vfs.read("/audio/bgm/track1.xa") == b"TRACK1_DATA"
        assert imported_vfs.read("/data/enemies/boss.bin") == b"BOSS_DATA"
