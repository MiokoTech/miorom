import os
import glob
from typing import List, Optional
from miorom.formats.csv_handler import CsvHandler, TranslationRow


TRANSLATION_INSTRUCTIONS = """# Translation Guidelines
1. Translate ONLY the contents of the 'Translation' column.
2. Keep 'Index', 'Offset', and 'Original' UNCHANGED.
3. Preserve all tags like <ENTER>, <WARNA>, <PLAYER>, <TOMBOL>, <ANGKA_1>, <1>, <A>, etc. exactly as they appear.
4. Return the result in the exact same CSV format.
"""


class BatchSplitter:
    """
    Splits large translation files into manageable batches for translators
    or distributed translation teams.
    """

    @classmethod
    def split_csv(
        cls,
        input_csv: str,
        output_dir: str,
        batch_size: int = 500,
        prefix: str = "batch",
        create_prompt: bool = True
    ) -> List[str]:
        """Split a CSV into multiple batch CSV files."""
        os.makedirs(output_dir, exist_ok=True)
        rows = CsvHandler.import_csv(input_csv)
        total_rows = len(rows)
        created_files = []

        total_batches = (total_rows + batch_size - 1) // batch_size
        padding = max(3, len(str(total_batches)))

        is_clean_format = all(r.offset == 0 for r in rows)

        for b_idx in range(total_batches):
            start = b_idx * batch_size
            end = min(start + batch_size, total_rows)
            chunk = rows[start:end]

            batch_filename = f"{prefix}_{b_idx+1:0{padding}d}.csv"
            batch_path = os.path.join(output_dir, batch_filename)
            if is_clean_format:
                CsvHandler.export_clean_csv(batch_path, chunk)
            else:
                CsvHandler.export_csv(batch_path, chunk)
            created_files.append(batch_path)

        if create_prompt:
            prompt_path = os.path.join(output_dir, "INSTRUCTIONS.md")
            with open(prompt_path, "w", encoding="utf-8") as f:
                f.write(TRANSLATION_INSTRUCTIONS)

        return created_files


class BatchMerger:
    """
    Merges translated batch files back into a single master translation file.
    Uses index/id or offset keys for safe out-of-order merging.
    """

    @classmethod
    def merge_dir(
        cls,
        batch_dir: str,
        output_csv: str,
        master_csv: Optional[str] = None,
        pattern: str = "*.csv"
    ) -> int:
        """
        Merge all matching CSV files in batch_dir into output_csv.
        If master_csv is provided, uses it as the base and updates translations from batches.
        Returns total updated translation count.
        """
        batch_files = sorted(glob.glob(os.path.join(batch_dir, pattern)))
        # Exclude output_csv or master_csv if they happen to be in the same folder
        batch_files = [
            f for f in batch_files
            if os.path.abspath(f) != os.path.abspath(output_csv)
            and (master_csv is None or os.path.abspath(f) != os.path.abspath(master_csv))
        ]

        # Collect translations by id and by offset
        translation_by_id = {}
        translation_by_offset = {}
        for b_file in batch_files:
            try:
                b_rows = CsvHandler.import_csv(b_file)
                for r in b_rows:
                    if r.translation and r.translation.strip():
                        val = r.translation.strip()
                        translation_by_id[r.index] = val
                        if r.offset != 0:
                            translation_by_offset[r.offset] = val
            except Exception as e:
                print(f"[!] Warning reading {b_file}: {e}")

        # If master_csv exists, apply onto master
        if master_csv and os.path.exists(master_csv):
            master_rows = CsvHandler.import_csv(master_csv)
            is_clean_format = all(r.offset == 0 for r in master_rows)
            for r in master_rows:
                if r.index in translation_by_id:
                    r.translation = translation_by_id[r.index]
                    if is_clean_format:
                        r.original = translation_by_id[r.index]
                elif r.offset != 0 and r.offset in translation_by_offset:
                    r.translation = translation_by_offset[r.offset]
                    if is_clean_format:
                        r.original = translation_by_offset[r.offset]

            if is_clean_format:
                CsvHandler.export_clean_csv(output_csv, master_rows)
            else:
                CsvHandler.export_csv(output_csv, master_rows)
            return len(translation_by_id)

        # Otherwise merge all batch rows in order
        all_rows = []
        seen_ids = set()
        for b_file in batch_files:
            b_rows = CsvHandler.import_csv(b_file)
            for r in b_rows:
                if r.index not in seen_ids:
                    all_rows.append(r)
                    seen_ids.add(r.index)

        all_rows.sort(key=lambda x: x.index)
        is_clean_format = all(r.offset == 0 for r in all_rows)
        if is_clean_format:
            CsvHandler.export_clean_csv(output_csv, all_rows)
        else:
            CsvHandler.export_csv(output_csv, all_rows)
        return len(translation_by_id)
