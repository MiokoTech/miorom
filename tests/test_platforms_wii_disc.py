"""
tests/test_platforms_wii_disc.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests for Nintendo Wii Optical Disc (.iso) and WBFS Container Engine.
Tests cover:
- Disc header parsing and byte packing
- 32 KB cluster encryption, decryption, and H0 verification
- Hierarchical hash tree calculation (H0 -> H1 -> H2 -> H3)
- WBFS block translation and sparse reading
- End-to-end synthetic Wii disc creation, file injection, repacking, and roundtrip
- Trucha Bug fake-signing validation on Ticket and TMD
- WBFS saving and streaming read-back
"""

import hashlib
import os
import tempfile

import pytest

from miorom.core import schema
from miorom.platforms.wii import (
    WBFSDisc,
    WiiDisc,
    WiiDiscHeader,
    WiiPartition,
    build_hash_tree,
    decrypt_cluster,
    encrypt_cluster,
)
from miorom.platforms.wii.disc import (
    CLUSTER_PAYLOAD_SIZE,
    CLUSTER_SIZE,
    PARTITION_TYPE_DATA,
    WII_COMMON_KEY_RETAIL,
    WII_DISC_MAGIC,
    WiiDiscHeaderStruct,
)
from miorom.platforms.wii.u8 import WADTicket, WADTmd, aes128_cbc_encrypt


def test_wii_disc_header_parse_and_pack():
    """Verify Wii root disc header parsing, serialization, and roundtrip fidelity."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=True,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="Mario Kart Wii",
    )

    packed = header.pack()
    assert len(packed) == WiiDiscHeaderStruct.sizeof()
    assert packed[0x18:0x1C] == schema.pack(">I", WII_DISC_MAGIC)

    parsed = WiiDiscHeader.parse(packed)
    assert parsed.game_id == "RMCE"
    assert parsed.maker_code == "01"
    assert parsed.disc_number == 0
    assert parsed.version == 1
    assert parsed.audio_streaming is True
    assert parsed.magic == WII_DISC_MAGIC
    assert parsed.game_title == "Mario Kart Wii"


def test_cluster_encrypt_and_decrypt_with_h0():
    """Verify 32 KB cluster encryption, decryption, and H0 SHA-1 hash table validation."""
    title_key = bytes.fromhex("0123456789abcdef0123456789abcdef")
    # 0x7C00 (31,744 bytes) payload
    test_payload = (b"NINTENDO_WII_CLUSTER_TEST_PAYLOAD_DATA_BLOCK_" * 800)[:CLUSTER_PAYLOAD_SIZE]

    cluster_bytes, h0_tbl = encrypt_cluster(test_payload, title_key)
    assert len(cluster_bytes) == CLUSTER_SIZE
    assert len(h0_tbl) == 31 * 20

    # Decrypt and verify H0 hashes
    decrypted, hdr = decrypt_cluster(cluster_bytes, title_key, verify_h0=True)
    assert decrypted == test_payload
    assert hdr[:620] == h0_tbl

    # Test that corrupted payload triggers ValueError when verify_h0=True
    corrupted_cluster = bytearray(cluster_bytes)
    corrupted_cluster[0x400] ^= 0xFF  # flip byte in ciphertext
    with pytest.raises(ValueError, match="Cluster H0 hash mismatch"):
        decrypt_cluster(bytes(corrupted_cluster), title_key, verify_h0=True)


def test_hash_tree_hierarchy():
    """Verify H0 -> H1 -> H2 -> H3 hash tree calculation matching Nintendo NW4R disc spec."""
    # Generate 18 dummy H0 tables (spanning 3 H1 groups)
    h0_tables = []
    for i in range(18):
        h0 = bytearray()
        for j in range(31):
            chunk = f"cluster_{i}_subblock_{j}".encode("ascii")
            h0.extend(hashlib.sha1(chunk).digest())
        h0_tables.append(bytes(h0))

    h3_table, h2_tables, h1_tables = build_hash_tree(h0_tables)

    # 18 clusters / 8 = 3 H1 groups
    assert len(h1_tables) == 3
    for h1 in h1_tables:
        assert len(h1) == 160  # 8 x 20 bytes

    # Verify first H1 entry matches SHA-1 of cluster 0's H0 table
    expected_h1_0 = hashlib.sha1(h0_tables[0]).digest()
    assert h1_tables[0][:20] == expected_h1_0

    # 3 H1 groups fit in 1 H2 group
    assert len(h2_tables) == 1
    assert len(h2_tables[0]) == 160

    # Verify first H2 entry matches SHA-1 of H1 table 0
    expected_h2_0 = hashlib.sha1(h1_tables[0]).digest()
    assert h2_tables[0][:20] == expected_h2_0

    # H3 table contains hash of H2 table
    assert len(h3_table) % 0x400 == 0
    expected_h3_0 = hashlib.sha1(h2_tables[0]).digest()
    assert h3_table[:20] == expected_h3_0


def test_wbfs_block_mapper():
    """Verify WBFS container header parsing and sparse block reading."""
    # Build synthetic WBFS container
    wbfs_data = bytearray(2 * 1024 * 1024 * 3)  # 6 MB container (3 blocks of 2MB)
    # Block 0: Header + WBL table
    wbfs_data[:4] = b"WBFS"
    schema.pack_into(">I", wbfs_data, 4, 12000)  # n_hd_sec
    wbfs_data[8] = 9   # hd_sec_sz_s = 512
    wbfs_data[9] = 21  # wbfs_sec_sz_s = 2MB (0x200000)

    # WBL table at 0x100: map virtual block 0 -> physical block 1, virtual block 1 -> physical block 2
    schema.pack_into(">H", wbfs_data, 0x100, 1)  # vblock 0 -> pblock 1
    schema.pack_into(">H", wbfs_data, 0x102, 2)  # vblock 1 -> pblock 2

    # Fill pblock 1 (starts at 2MB = 0x200000) with marker
    wbfs_data[0x200000 : 0x200000 + 16] = b"PHYS_BLOCK_1_DAT"
    # Fill pblock 2 (starts at 4MB = 0x400000) with marker
    wbfs_data[0x400000 : 0x400000 + 16] = b"PHYS_BLOCK_2_DAT"

    from miorom.platforms.wii.disc import DiscStream
    d_stream = DiscStream.from_bytes(bytes(wbfs_data))
    wbfs = WBFSDisc.from_stream(d_stream)

    assert wbfs.wbfs_sec_size == 0x200000
    assert wbfs.wbl_table[0] == 1
    assert wbfs.wbl_table[1] == 2

    # Read virtual block 0
    read_b0 = wbfs.read_at(0, 16)
    assert read_b0 == b"PHYS_BLOCK_1_DAT"

    # Read virtual block 1
    read_b1 = wbfs.read_at(0x200000, 16)
    assert read_b1 == b"PHYS_BLOCK_2_DAT"

    # Read virtual block 2 (unallocated, should return zeros)
    read_b2 = wbfs.read_at(0x400000, 16)
    assert read_b2 == b"\x00" * 16


def _create_mock_partition(title_id: bytes = b"\x00\x01\x00\x00RMCE") -> WiiPartition:
    """Helper to create a valid minimal mock WiiPartition."""
    title_key = bytes.fromhex("112233445566778899aabbccddeeff00")

    # Build mock ticket
    tik_raw = bytearray(0x2A4)
    # Set title_id at 0x1CB
    tik_raw[0x1CB : 0x1D3] = title_id
    # Encrypt title_key with common key
    iv = title_id + (b"\x00" * 8)
    enc_title_key = aes128_cbc_encrypt(title_key, WII_COMMON_KEY_RETAIL, iv)
    tik_raw[0x1F0 : 0x200] = enc_title_key
    ticket = WADTicket.from_bytes(bytes(tik_raw))

    # Build mock TMD
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
        apploader_bin=b"APPLOADER_IMAGE_CODE",
        main_dol=b"MAIN_DOL_EXECUTABLE_CODE",
    )
    # Add files
    part["files/Stage/Course.arc"] = b"COURSE_ARC_DATA_PAYLOAD_123456"
    part["files/Text/message.bmg"] = b"BMG_MESSAGE_DATA_PAYLOAD_789012"

    return part


def test_synthetic_wii_disc_repack_and_roundtrip():
    """Verify full end-to-end synthetic Wii disc creation, repacking, and roundtrip parsing."""
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

    part = _create_mock_partition()
    disc = WiiDisc(header=header, partitions=[part])

    # Repack to ISO bytes
    iso_bytes = disc.to_bytes(fake_sign=True)
    assert len(iso_bytes) > 0x50000
    assert iso_bytes[0x18:0x1C] == schema.pack(">I", WII_DISC_MAGIC)

    # Read back disc from bytes
    loaded_disc = WiiDisc.from_bytes(iso_bytes)
    assert loaded_disc.header.game_id == "RMCE"
    assert loaded_disc.header.game_title == "Mario Kart Wii Test"
    assert len(loaded_disc.partitions) == 1

    loaded_part = loaded_disc.data_partition
    assert loaded_part is not None
    assert loaded_part.is_data_partition

    # Check files list
    file_list = loaded_part.list_files()
    assert "sys/boot.bin" in file_list
    assert "sys/bi2.bin" in file_list
    assert "sys/apploader.img" in file_list
    assert "sys/main.dol" in file_list
    assert "files/Stage/Course.arc" in file_list
    assert "files/Text/message.bmg" in file_list

    # Check file contents
    assert loaded_part["files/Stage/Course.arc"] == b"COURSE_ARC_DATA_PAYLOAD_123456"
    assert loaded_part["files/Text/message.bmg"] == b"BMG_MESSAGE_DATA_PAYLOAD_789012"
    assert loaded_part["sys/main.dol"].startswith(b"MAIN_DOL_EXECUTABLE_CODE")


def test_file_injection_and_replacement():
    """Verify in-memory file replacement, new file injection, and re-packing."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="Mario Kart Wii Injection Test",
    )

    part = _create_mock_partition()
    disc = WiiDisc(header=header, partitions=[part])

    # Repack base disc
    iso_bytes = disc.to_bytes()
    disc2 = WiiDisc.from_bytes(iso_bytes)
    part2 = disc2.data_partition
    assert part2 is not None

    # Replace existing file
    part2["files/Stage/Course.arc"] = b"NEW_MODIFIED_COURSE_DATA_9999"
    # Inject brand new file
    part2["files/Custom/patch.bin"] = b"CUSTOM_PATCH_PAYLOAD_DATA"

    # Repack modified disc
    modified_iso = disc2.to_bytes(fake_sign=True)

    # Read back and verify modifications
    disc3 = WiiDisc.from_bytes(modified_iso)
    part3 = disc3.data_partition
    assert part3 is not None
    assert part3["files/Stage/Course.arc"] == b"NEW_MODIFIED_COURSE_DATA_9999"
    assert part3["files/Custom/patch.bin"] == b"CUSTOM_PATCH_PAYLOAD_DATA"
    assert part3["files/Text/message.bmg"] == b"BMG_MESSAGE_DATA_PAYLOAD_789012"


def test_trucha_bug_fake_signing():
    """Verify Trucha Bug RSA-2048 null signature generation on repacked disc."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="Trucha Test",
    )
    part = _create_mock_partition()
    disc = WiiDisc(header=header, partitions=[part])

    iso_bytes = disc.to_bytes(fake_sign=True)

    # Check partition ticket at 0x50000
    ticket_sig_type = schema.unpack_from(">I", iso_bytes, 0x50000)[0]
    ticket_sig_bytes = iso_bytes[0x50004 : 0x50004 + 256]

    assert ticket_sig_type == 0x10001  # RSA-2048
    assert ticket_sig_bytes == b"\x00" * 256  # Trucha null signature


def test_disc_save_and_wbfs_roundtrip():
    """Verify disc extraction to directory and save_wbfs sparse packaging."""
    header = WiiDiscHeader(
        game_id="RMCE",
        maker_code="01",
        disc_number=0,
        version=1,
        audio_streaming=False,
        stream_buf_size=0,
        magic=WII_DISC_MAGIC,
        gc_magic=0xC2339F3D,
        game_title="WBFS Save Test",
    )
    part = _create_mock_partition()
    disc = WiiDisc(header=header, partitions=[part])

    with tempfile.TemporaryDirectory() as tmpdir:
        iso_path = os.path.join(tmpdir, "game.iso")
        wbfs_path = os.path.join(tmpdir, "game.wbfs")
        extract_dir = os.path.join(tmpdir, "extracted")

        # Save ISO
        disc.save(iso_path)
        assert os.path.exists(iso_path)

        # Save WBFS
        disc.save_wbfs(wbfs_path)
        assert os.path.exists(wbfs_path)
        assert os.path.getsize(wbfs_path) > 0

        # Read back from WBFS file directly!
        wbfs_disc = WiiDisc.from_file(wbfs_path)
        assert wbfs_disc.header.game_id == "RMCE"
        assert wbfs_disc.data_partition is not None
        assert wbfs_disc.data_partition["files/Stage/Course.arc"] == b"COURSE_ARC_DATA_PAYLOAD_123456"

        # Test batch extraction
        extracted = wbfs_disc.extract_all(extract_dir)
        assert "partition_0_data" in extracted
        assert os.path.exists(os.path.join(extract_dir, "partition_0_data", "files", "Stage", "Course.arc"))
        with open(os.path.join(extract_dir, "partition_0_data", "files", "Stage", "Course.arc"), "rb") as f:
            assert f.read() == b"COURSE_ARC_DATA_PAYLOAD_123456"
