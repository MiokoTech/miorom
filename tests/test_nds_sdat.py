"""
test_nds_sdat.py - Unit tests for Nintendo DS SDAT audio container parser and rebuilder.
"""

import os
import struct
import tempfile
import pytest

from miorom.audio.sdat import SDATContainer, SDATFileEntry


def _create_mock_sdat() -> bytes:
    """Constructs a minimal valid SDAT binary container for testing."""
    # 1. FILE payload
    sseq_data = b"SSEQ\x00\x00\x00\x00" + (b"\x11" * 24)  # 32 bytes
    sbnk_data = b"SBNK\x00\x00\x00\x00" + (b"\x22" * 24)  # 32 bytes

    file_block = bytearray(b"FILE")
    file_block.extend(struct.pack("<II", 80, 2))  # size=80, file_count=2
    file_block.extend(b"\x00\x00\x00\x00")  # 4 bytes padding to align data to offset 16
    file_block.extend(sseq_data)
    file_block.extend(sbnk_data)

    # 2. SYMB block: Table 0 (SSEQ), Table 2 (SBNK)
    symb_block = bytearray(b"SYMB")
    # Header: size placeholder (uint32), 8 offsets
    symb_block.extend(struct.pack("<I", 0))  # Placeholder size
    # Offsets: SEQ=40, SEQARC=0, BANK=60, others=0
    symb_block.extend(struct.pack("<8I", 40, 0, 60, 0, 0, 0, 0, 0))

    # SEQ Sub-table at offset 40: count=1, string offset=80
    symb_block = symb_block.ljust(40, b"\x00")
    symb_block.extend(struct.pack("<II", 1, 80))

    # BANK Sub-table at offset 60: count=1, string offset=96
    symb_block = symb_block.ljust(60, b"\x00")
    symb_block.extend(struct.pack("<II", 1, 96))

    # Strings at 80 and 96
    symb_block = symb_block.ljust(80, b"\x00")
    symb_block.extend(b"SEQ_TEST\x00")
    symb_block = symb_block.ljust(96, b"\x00")
    symb_block.extend(b"BANK_TEST\x00")
    symb_block = symb_block.ljust(112, b"\x00")
    struct.pack_into("<I", symb_block, 4, len(symb_block))

    # 3. INFO block: Table 0 (SSEQ), Table 2 (SBNK)
    info_block = bytearray(b"INFO")
    info_block.extend(struct.pack("<I", 0))  # Placeholder size
    # Offsets: SEQ=40, SEQARC=0, BANK=52, others=0
    info_block.extend(struct.pack("<8I", 40, 0, 52, 0, 0, 0, 0, 0))

    # SEQ Sub-table at 40: count=1, record offset=64
    info_block = info_block.ljust(40, b"\x00")
    info_block.extend(struct.pack("<II", 1, 64))

    # BANK Sub-table at 52: count=1, record offset=72
    info_block = info_block.ljust(52, b"\x00")
    info_block.extend(struct.pack("<II", 1, 72))

    # Records: SEQ Record at 64 -> file_id=0; BANK Record at 72 -> file_id=1
    info_block = info_block.ljust(64, b"\x00")
    info_block.extend(struct.pack("<HH", 0, 0))  # file_id=0
    info_block = info_block.ljust(72, b"\x00")
    info_block.extend(struct.pack("<HH", 1, 0))  # file_id=1
    info_block = info_block.ljust(80, b"\x00")
    struct.pack_into("<I", info_block, 4, len(info_block))

    # 4. FAT block
    fat_off = 64 + len(symb_block) + len(info_block)
    fat_pad = (32 - (fat_off % 32)) % 32
    fat_off += fat_pad

    file_off = fat_off + 12 + 16  # 2 FAT entries = 16 bytes
    file_pad = (32 - (file_off % 32)) % 32
    file_off += file_pad

    fat_block = bytearray(b"FAT ")
    fat_block.extend(struct.pack("<II", 28, 2))
    # Record 0: SSEQ at file_off + 16
    fat_block.extend(struct.pack("<II", file_off + 16, 32))
    # Record 1: SBNK at file_off + 48
    fat_block.extend(struct.pack("<II", file_off + 48, 32))

    total_len = file_off + len(file_block)

    # 5. Header
    header = bytearray(b"SDAT")
    header.extend(struct.pack("<HH", 0xFEFF, 0x0100))
    header.extend(struct.pack("<I", total_len))
    header.extend(struct.pack("<HH", 64, 4))
    header.extend(struct.pack("<II", 64, len(symb_block)))
    header.extend(struct.pack("<II", 64 + len(symb_block), len(info_block)))
    header.extend(struct.pack("<II", fat_off, len(fat_block)))
    header.extend(struct.pack("<II", file_off, len(file_block)))
    header = header.ljust(64, b"\x00")

    out = bytearray(header)
    out.extend(symb_block)
    out.extend(info_block)
    if fat_pad > 0:
        out.extend(b"\x00" * fat_pad)
    out.extend(fat_block)
    if file_pad > 0:
        out.extend(b"\x00" * file_pad)
    out.extend(file_block)

    return bytes(out)


def test_mock_sdat_parsing_and_linking():
    data = _create_mock_sdat()
    sdat = SDATContainer(data)

    assert len(sdat.entries) == 2
    assert "SEQ_TEST" in sdat.sequences
    assert "BANK_TEST" in sdat.sound_banks

    assert sdat.sequences["SEQ_TEST"].data[:4] == b"SSEQ"
    assert sdat.sound_banks["BANK_TEST"].data[:4] == b"SBNK"


def test_mock_sdat_extract_and_replace():
    data = _create_mock_sdat()
    sdat = SDATContainer(data)

    with tempfile.TemporaryDirectory() as tmpdir:
        counts = sdat.extract_all(tmpdir)
        assert counts["sseq"] == 1
        assert counts["sbnk"] == 1

        sseq_file = os.path.join(tmpdir, "sseq", "SEQ_TEST.sseq")
        sbnk_file = os.path.join(tmpdir, "sbnk", "BANK_TEST.sbnk")
        assert os.path.isfile(sseq_file)
        assert os.path.isfile(sbnk_file)

        # Test replace by name
        new_payload = b"SSEQ_NEW_TRACK_DATA"
        assert sdat.replace_by_name("SEQ_TEST", new_payload)
        assert bytes(sdat.sequences["SEQ_TEST"].data) == new_payload

        # Rebuild container
        rebuilt = sdat.to_bytes()
        sdat2 = SDATContainer(rebuilt)
        assert "SEQ_TEST" in sdat2.sequences
        assert bytes(sdat2.sequences["SEQ_TEST"].data) == new_payload


def test_real_rf1_sdat_dataset():
    rf1_sdat = "/mnt/sdcard/MiokoTech/Rune Factory 1 nds/workspace/filesystem/root/res/sound_data.sdat"
    if not os.path.isfile(rf1_sdat):
        pytest.skip("Rune Factory 1 sound_data.sdat not present on filesystem.")

    sdat = SDATContainer.from_file(rf1_sdat)
    assert len(sdat.entries) == 1300
    assert sum(1 for e in sdat.entries if len(e.data) > 0) == 650
    assert len(sdat.sequences) == 111
    assert len(sdat.sound_banks) == 39
    assert len(sdat.wave_archives) == 2
    assert len(sdat.streams) == 506

    # Verify key track names
    assert "SEQ_OPENING" in sdat.sequences
    assert sdat.sequences["SEQ_OPENING"].data[:4] == b"SSEQ"
    assert "Bgm_MAIN" in sdat.sound_banks
    assert sdat.sound_banks["Bgm_MAIN"].data[:4] == b"SBNK"
    assert "Bgm_MAIN_ARC" in sdat.wave_archives
    assert sdat.wave_archives["Bgm_MAIN_ARC"].data[:4] == b"SWAR"

    # Verify rebuild container integrity
    rebuilt_bytes = sdat.to_bytes()
    rebuilt_sdat = SDATContainer(rebuilt_bytes)
    assert len(rebuilt_sdat.sequences) == 111
    assert len(rebuilt_sdat.sound_banks) == 39
    assert len(rebuilt_sdat.wave_archives) == 2
    assert len(rebuilt_sdat.streams) == 506
