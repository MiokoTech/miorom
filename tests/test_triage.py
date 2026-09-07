import os
import tempfile
import pytest

from miorom.scanner.triage import RomTriageEngine, AssetType, TriageReport, FileTriageRecord


def test_triage_buffer_categories():
    # 1. Padding
    pad_data = b"\x00" * 1024
    rec_pad = RomTriageEngine.triage_buffer(pad_data, name="padding.bin")
    assert rec_pad.asset_type == AssetType.PADDING_EMPTY

    # 2. Text
    text_data = b"Hello warrior! Welcome to the fantasy kingdom. Are you ready to embark on your quest?\n" * 10
    rec_text = RomTriageEngine.triage_buffer(text_data, name="story.txt")
    assert rec_text.asset_type == AssetType.TEXT_SCRIPT

    # 3. Known Archives
    narc_data = b"NARC\xFE\xFF\x00\x01" + b"\x00" * 32
    rec_narc = RomTriageEngine.triage_buffer(narc_data, name="archive.narc")
    assert rec_narc.asset_type == AssetType.ARCHIVE_CONTAINER
    assert rec_narc.format_detected == "NARC"

    # 4. Known Audio
    sseq_data = b"SSEQ\xFE\xFF\x00\x01" + b"\x00" * 32
    rec_sseq = RomTriageEngine.triage_buffer(sseq_data, name="bgm.sseq")
    assert rec_sseq.asset_type == AssetType.AUDIO_MUSIC

    # 5. Known Font
    nftr_data = b"NFTR\xFE\xFF\x00\x01" + b"\x00" * 32
    rec_nftr = RomTriageEngine.triage_buffer(nftr_data, name="font.nftr")
    assert rec_nftr.asset_type == AssetType.TEXTURE_GRAPHICS


def test_triage_directory_batch():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create 3 files
        with open(os.path.join(tmpdir, "f1_dialogue.txt"), "wb") as f:
            f.write(b"Good morning, hero! Time to save the world again.\n" * 5)
        with open(os.path.join(tmpdir, "f2_empty.bin"), "wb") as f:
            f.write(b"\xFF" * 512)
        with open(os.path.join(tmpdir, "f3_pack.narc"), "wb") as f:
            f.write(b"NARC\x00" * 10)

        report = RomTriageEngine.triage_directory(tmpdir)
        assert report.total_files == 3

        text_files = report.filter_by_type(AssetType.TEXT_SCRIPT)
        assert len(text_files) == 1
        assert "f1_dialogue.txt" in text_files[0].path

        summary_text = report.summary()
        assert "TEXT_SCRIPT" in summary_text
        assert "PADDING_EMPTY" in summary_text
        assert "ARCHIVE_CONTAINER" in summary_text
