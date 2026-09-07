import os
import struct
import tempfile
import pytest

from miorom.diff.mapper import BinaryDiffMapper
from miorom.diff.porter import CrossRegionPorter, PortReport
from miorom.formats.csv_handler import CsvHandler, TranslationRow


def test_port_csv_by_index():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_csv = os.path.join(tmpdir, "jap_translated.csv")
        tgt_csv = os.path.join(tmpdir, "usa_original.csv")
        out_csv = os.path.join(tmpdir, "usa_translated.csv")

        # Source (Japanese translated to Indonesian)
        src_rows = [
            TranslationRow(index=0, offset=0x1000, original="こんにちは", translation="Halo petualang!", context="NPC_01"),
            TranslationRow(index=1, offset=0x1040, original="さようなら", translation="Sampai jumpa!", context="NPC_01"),
            TranslationRow(index=2, offset=0x1080, original="宿屋へようこそ", translation="Selamat datang di penginapan!", context="INN"),
        ]
        CsvHandler.export_csv(src_csv, src_rows)

        # Target (USA original English, different offsets)
        tgt_rows = [
            TranslationRow(index=0, offset=0x2500, original="Hello adventurer!", translation="", context="NPC_01"),
            TranslationRow(index=1, offset=0x2540, original="Goodbye!", translation="", context="NPC_01"),
            TranslationRow(index=2, offset=0x2580, original="Welcome to the inn!", translation="", context="INN"),
        ]
        CsvHandler.export_csv(tgt_csv, tgt_rows)

        porter = CrossRegionPorter()
        ported_rows, report = porter.port_csv(src_csv, tgt_csv, strategy="index", output_csv=out_csv)

        assert report.migrated_strings == 3
        assert report.unmatched_strings == 0
        assert report.success_rate == 100.0

        # Check ported rows
        assert ported_rows[0].index == 0
        assert ported_rows[0].offset == 0x2500  # Kept USA offset
        assert ported_rows[0].original == "Hello adventurer!"  # Kept USA original
        assert ported_rows[0].translation == "Halo petualang!"  # Received Indonesian translation
        assert ported_rows[1].translation == "Sampai jumpa!"
        assert ported_rows[2].translation == "Selamat datang di penginapan!"

        # Verify output CSV file was written
        assert os.path.exists(out_csv)
        loaded = CsvHandler.import_csv(out_csv)
        assert len(loaded) == 3
        assert loaded[0].translation == "Halo petualang!"


def test_port_csv_by_offset_correlation():
    with tempfile.TemporaryDirectory() as tmpdir:
        src_csv = os.path.join(tmpdir, "src.csv")
        tgt_csv = os.path.join(tmpdir, "tgt.csv")

        # Create synthetic binaries where binary B is shifted by +0x200 bytes
        # 64-byte shared anchor block
        anchor = b"ANCHOR_SIGNATURE_SHARED_BETWEEN_BOTH_REGIONAL_BINARIES_12345678"
        bin_a = bytearray(0x400)
        bin_b = bytearray(0x600)

        bin_a[0x100:0x140] = anchor
        bin_b[0x300:0x340] = anchor  # Shifted by +0x200

        mapper = BinaryDiffMapper(bytes(bin_a), bytes(bin_b))
        mapper.find_matching_blocks(chunk_size=32)
        assert mapper.correlate_offset(0x100) == 0x300

        # Source CSV (offset 0x100)
        src_rows = [
            TranslationRow(index=10, offset=0x100, original="OrigA", translation="TransA", context="A"),
        ]
        # Target CSV (offset 0x300)
        tgt_rows = [
            TranslationRow(index=99, offset=0x300, original="OrigB", translation="", context="B"),
        ]

        porter = CrossRegionPorter(diff_mapper=mapper)
        ported, report = porter.port_csv(src_rows, tgt_rows, strategy="offset", tolerance_bytes=16)

        assert report.migrated_strings == 1
        assert ported[0].index == 99
        assert ported[0].translation == "TransA"


def test_port_csv_unmatched_fallback():
    src_rows = [
        TranslationRow(index=0, offset=0x10, original="A", translation="TransA"),
    ]
    tgt_rows = [
        TranslationRow(index=0, offset=0x20, original="USA_A", translation=""),
        TranslationRow(index=1, offset=0x30, original="USA_Extra", translation=""),
    ]

    porter = CrossRegionPorter()
    ported, report = porter.port_csv(src_rows, tgt_rows, strategy="index", fallback_to_original=True)

    assert report.migrated_strings == 1
    assert report.unmatched_strings == 1
    assert ported[0].translation == "TransA"
    assert ported[1].translation == "USA_Extra"  # Fallback to original target


def test_port_binary():
    # Build synthetic target binary with pointer table and string pool
    # Pointer table at 0x10 pointing to strings at 0x40, 0x60
    tgt_bin = bytearray(0x200)
    struct.pack_into(">II", tgt_bin, 0x10, 0x40, 0x60)
    tgt_bin[0x40:0x48] = "Hi".encode("utf-16-be") + b"\x00\x00"
    tgt_bin[0x60:0x68] = "Bye".encode("utf-16-be") + b"\x00\x00"

    src_dummy = bytearray(0x100)
    translated = ["Halo", "Dah"]

    porter = CrossRegionPorter()
    patched_bytes, report = porter.port_binary(
        source_data=src_dummy,
        target_data=tgt_bin,
        translated_strings=translated,
        target_table_offset=0x10,
        target_pool_offset=0x40,
        stride=4,
        endian=">",
        encoding="utf-16-be",
    )

    assert report.migrated_strings == 2
    # Verify pointer table updated
    p0 = struct.unpack_from(">I", patched_bytes, 0x10)[0]
    p1 = struct.unpack_from(">I", patched_bytes, 0x14)[0]
    assert p0 == 0x40
    assert p1 > p0
    # Verify translated string pool
    assert "Halo".encode("utf-16-be") in patched_bytes
    assert "Dah".encode("utf-16-be") in patched_bytes
