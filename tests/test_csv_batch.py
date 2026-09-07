import os
import tempfile
from miorom.formats.csv_handler import CsvHandler, TranslationRow
from miorom.formats.batch import BatchSplitter, BatchMerger


def test_csv_export_import():
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "test.csv")
        rows = [
            TranslationRow(index=0, offset=0x1000, original="Hello, world!", translation="Halo, dunia!"),
            TranslationRow(index=1, offset=0x1050, original="Goodbye!", translation="")
        ]

        CsvHandler.export_csv(csv_path, rows)
        imported = CsvHandler.import_csv(csv_path)

        assert len(imported) == 2
        assert imported[0].offset == 0x1000
        assert imported[0].original == "Hello, world!"
        assert imported[0].translation == "Halo, dunia!"

        # Test dictionary mapping
        d = CsvHandler.to_offset_dict(csv_path, fallback_to_original=True)
        assert d[0x1000] == "Halo, dunia!"
        assert d[0x1050] == "Goodbye!"  # Fallback worked


def test_batch_split_and_merge():
    with tempfile.TemporaryDirectory() as tmpdir:
        master_csv = os.path.join(tmpdir, "master.csv")
        batch_dir = os.path.join(tmpdir, "batches")
        merged_csv = os.path.join(tmpdir, "merged.csv")

        rows = [
            TranslationRow(index=i, offset=0x1000 + i*10, original=f"Line {i}")
            for i in range(12)
        ]
        CsvHandler.export_csv(master_csv, rows)

        # Split into batches of 5
        batch_files = BatchSplitter.split_csv(master_csv, batch_dir, batch_size=5)
        assert len(batch_files) == 3  # 5 + 5 + 2 = 12

        # Simulate translating batch 1
        batch1_rows = CsvHandler.import_csv(batch_files[0])
        batch1_rows[0].translation = "Baris 0"
        batch1_rows[1].translation = "Baris 1"
        CsvHandler.export_csv(batch_files[0], batch1_rows)

        # Merge back
        count = BatchMerger.merge_dir(batch_dir, merged_csv, master_csv=master_csv)
        assert count == 2

        merged_dict = CsvHandler.to_offset_dict(merged_csv)
        assert merged_dict[0x1000] == "Baris 0"
        assert merged_dict[0x1000 + 10] == "Baris 1"
        assert merged_dict[0x1000 + 20] == "Line 2"  # Unchanged
