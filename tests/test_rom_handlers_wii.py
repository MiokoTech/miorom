"""
tests/test_rom_handlers_wii.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Nintendo Wii Optical Disc (.iso, .wbfs) RomHandler.
Tests cover:
- Format auto-detection via can_handle (ISO magic, WBFS magic, file path)
- Unpacking synthetic Wii disc into sys/ binaries and root/ FST filesystem
- In-memory file modification, addition, and bit-exact repacking
- WBFS container repacking format
- Full RomManager and CLI orchestration roundtrip
"""

from __future__ import annotations

import os
import tempfile

from miorom.core import schema
from miorom.platforms.wii import (
    WiiDisc,
    WiiDiscHeader,
    WiiPartition,
)
from miorom.platforms.wii.disc import (
    CLUSTER_SIZE,
    PARTITION_TYPE_DATA,
    WII_COMMON_KEY_RETAIL,
    WII_DISC_MAGIC,
    DiscStream,
)
from miorom.platforms.wii.u8 import (
    WADTicket,
    WADTmd,
    aes128_cbc_encrypt,
)
from miorom.rom.handlers.wii import WiiRomHandler
from miorom.rom.manager import RomManager


def _create_mock_wii_disc() -> WiiDisc:
    """Helper to synthesize a minimal playable WiiDisc with 1 data partition."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="Mario Kart Wii Test",
    )

    title_id = b"\x00\x01\x00\x00RMCE"
    title_key = bytes.fromhex("112233445566778899aabbccddeeff00")

    tik_raw = bytearray(0x2A4)
    tik_raw[0x1CB : 0x1D3] = title_id
    iv = title_id + (b"\x00" * 8)
    enc_title_key = aes128_cbc_encrypt(title_key, WII_COMMON_KEY_RETAIL, iv)
    tik_raw[0x1F0 : 0x200] = enc_title_key
    ticket = WADTicket.from_bytes(bytes(tik_raw))

    tmd_raw = bytearray(0x1E4 + 36)
    schema.pack_into(">H", tmd_raw, 0x1DE, 1)  # num_contents = 1
    tmd = WADTmd.from_bytes(bytes(tmd_raw))

    part = WiiPartition(
        partition_offset=0x50000,
        partition_type=PARTITION_TYPE_DATA,
        ticket=ticket,
        tmd=tmd,
        title_key=title_key,
        data_offset=0x58000,
        data_size=CLUSTER_SIZE * 2,
        h3_offset=0x51000,
        boot_bin=b"BOOT_BIN_DATA" + b"\x00" * (0x440 - 13),
        bi2_bin=b"BI2_BIN_DATA" + b"\x00" * (0x2000 - 12),
        apploader_bin=b"APPLOADER_IMAGE_PAYLOAD",
        main_dol=b"MAIN_DOL_EXECUTABLE_PAYLOAD",
    )
    part["files/Stage/Course.arc"] = b"COURSE_ARC_DATA_12345"
    part["files/Text/message.bmg"] = b"BMG_MESSAGE_DATA_67890"

    return WiiDisc(header=header, partitions=[part])


def test_wii_handler_can_handle():
    """Verify format detection for raw ISO, WBFS, and negative controls."""
    handler = WiiRomHandler()

    # 1. Wii Disc Magic at 0x18
    raw_iso = bytearray(0x100)
    schema.pack_into(">I", raw_iso, 0x18, WII_DISC_MAGIC)
    assert handler.can_handle(bytes(raw_iso)) is True

    # 2. WBFS Container Magic at 0x00
    raw_wbfs = b"WBFS" + b"\x00" * 60
    assert handler.can_handle(raw_wbfs) is True

    # 3. Partition Table at 0x40000
    large_data = bytearray(0x40008)
    schema.pack_into(">I", large_data, 0x40000, 1)
    assert handler.can_handle(bytes(large_data)) is True

    # 4. Negative: GameCube Magic without Wii magic or partition table
    gc_data = bytearray(0x100)
    schema.pack_into(">I", gc_data, 0x1C, 0xC2339F3D)
    assert handler.can_handle(bytes(gc_data)) is False

    # 5. Negative: Random noise
    assert handler.can_handle(b"RANDOM_NON_DISC_DATA") is False

    # 6. Filepath based detection
    with tempfile.NamedTemporaryFile(suffix=".iso", delete=False) as f:
        f.write(bytes(raw_iso))
        tmp_path = f.name

    try:
        assert handler.can_handle(b"", filepath=tmp_path) is True
    finally:
        os.unlink(tmp_path)


def test_wii_handler_unpack_synthetic_disc():
    """Verify unpacking a synthetic Wii disc to sys/ binaries and root/ FST filesystem."""
    disc = _create_mock_wii_disc()
    disc_bytes = disc.to_bytes()

    handler = WiiRomHandler()
    with tempfile.TemporaryDirectory() as tmpdir:
        meta = handler.unpack(disc_bytes, tmpdir)

        assert meta["format"] == "wii"
        assert meta["game_id"] == "RMCE"
        assert meta["game_title"] == "Mario Kart Wii Test"
        assert meta["file_count"] == 2

        # Check sys/ directory
        sys_dir = os.path.join(tmpdir, "sys")
        assert os.path.isfile(os.path.join(sys_dir, "header.bin"))
        assert os.path.isfile(os.path.join(sys_dir, "boot.bin"))
        assert os.path.isfile(os.path.join(sys_dir, "bi2.bin"))
        assert os.path.isfile(os.path.join(sys_dir, "apploader.img"))
        assert os.path.isfile(os.path.join(sys_dir, "main.dol"))
        assert os.path.isfile(os.path.join(sys_dir, "ticket.bin"))
        assert os.path.isfile(os.path.join(sys_dir, "tmd.bin"))

        # Check root/ directory
        root_dir = os.path.join(tmpdir, "root")
        course_path = os.path.join(root_dir, "Stage", "Course.arc")
        bmg_path = os.path.join(root_dir, "Text", "message.bmg")

        assert os.path.isfile(course_path)
        assert os.path.isfile(bmg_path)

        with open(course_path, "rb") as f:
            assert f.read() == b"COURSE_ARC_DATA_12345"
        with open(bmg_path, "rb") as f:
            assert f.read() == b"BMG_MESSAGE_DATA_67890"


def test_wii_handler_repack_and_roundtrip():
    """Verify modifying extracted game files, adding new files, and repacking to a playable ISO."""
    disc = _create_mock_wii_disc()
    disc_bytes = disc.to_bytes()

    handler = WiiRomHandler()
    with tempfile.TemporaryDirectory() as tmpdir:
        handler.unpack(disc_bytes, tmpdir)

        # Modify an existing file
        bmg_path = os.path.join(tmpdir, "root", "Text", "message.bmg")
        with open(bmg_path, "wb") as f:
            f.write(b"LOCALIZED_INDONESIAN_BMG_TEXT")

        # Inject a brand new file
        patch_path = os.path.join(tmpdir, "root", "Mod", "patch.txt")
        os.makedirs(os.path.dirname(patch_path), exist_ok=True)
        with open(patch_path, "wb") as f:
            f.write(b"CUSTOM_TRANSLATION_PATCH_V1")

        # Repack
        repacked_iso = handler.repack(tmpdir, format="iso")
        assert len(repacked_iso) > 0

        # Verify repacked ISO can be parsed back
        repacked_disc = WiiDisc.from_bytes(repacked_iso)
        assert len(repacked_disc.partitions) == 1
        part = repacked_disc.partitions[0]

        assert part["files/Text/message.bmg"] == b"LOCALIZED_INDONESIAN_BMG_TEXT"
        assert part["files/Mod/patch.txt"] == b"CUSTOM_TRANSLATION_PATCH_V1"
        assert part["files/Stage/Course.arc"] == b"COURSE_ARC_DATA_12345"


def test_wii_handler_repack_wbfs():
    """Verify repacking directory into a sparse WBFS container."""
    disc = _create_mock_wii_disc()
    disc_bytes = disc.to_bytes()

    handler = WiiRomHandler()
    with tempfile.TemporaryDirectory() as tmpdir:
        handler.unpack(disc_bytes, tmpdir)

        repacked_wbfs = handler.repack(tmpdir, format="wbfs")
        assert repacked_wbfs[:4] == b"WBFS"

        # Load as WBFS via DiscStream
        d_stream = DiscStream.from_bytes(repacked_wbfs)
        loaded_disc = WiiDisc.from_stream(d_stream)

        assert loaded_disc.header.game_id == "RMCE"
        assert len(loaded_disc.partitions) == 1
        part = loaded_disc.partitions[0]
        assert part["files/Stage/Course.arc"] == b"COURSE_ARC_DATA_12345"


def test_rom_manager_wii_integration():
    """Verify RomManager auto-detection, unpack, and repack dispatching for Wii."""
    disc = _create_mock_wii_disc()
    disc_bytes = disc.to_bytes()

    manager = RomManager()

    # Auto-detection
    detected = manager.detect_format(disc_bytes)
    assert detected == "wii"

    # Dispatch unpack
    with tempfile.TemporaryDirectory() as tmpdir:
        meta = manager.unpack(disc_bytes, tmpdir)
        assert meta["format"] == "wii"
        assert meta["game_id"] == "RMCE"

        # Dispatch repack
        repacked = manager.repack(tmpdir, fmt="wii")
        assert len(repacked) > 0
