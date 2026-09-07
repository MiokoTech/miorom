"""
miorom.diff.porter
~~~~~~~~~~~~~~~~~~
Cross-Region Script and Asset Porter.
Automates migrating translations, string pools, and pointer tables between
different regional releases of a game (e.g. Japanese -> USA -> European PAL).
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.core.scanner import StringScanner, PointerScanner
from miorom.diff.mapper import BinaryDiffMapper, MatchedBlock
from miorom.formats.csv_handler import CsvHandler, TranslationRow
from miorom.helper.string_pool import StringPoolBuilder
from miorom.helper.relocator import BinaryRelocator


@dataclass
class PortReport:
    """Detailed summary report of cross-region migration."""
    strategy: str
    total_source_strings: int = 0
    total_target_strings: int = 0
    migrated_strings: int = 0
    unmatched_strings: int = 0
    shifted_offset_delta: int = 0
    warnings: List[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_target_strings == 0:
            return 100.0 if self.migrated_strings > 0 else 0.0
        return (self.migrated_strings / self.total_target_strings) * 100.0

    def summary(self) -> str:
        lines = [
            "=" * 60,
            f"Cross-Region Porting Report (Strategy: {self.strategy.upper()})",
            "=" * 60,
            f"Source Strings Total : {self.total_source_strings:,}",
            f"Target Strings Total : {self.total_target_strings:,}",
            f"Migrated Successfully: {self.migrated_strings:,} ({self.success_rate:.1f}%)",
            f"Unmatched / Skipped  : {self.unmatched_strings:,}",
        ]
        if self.shifted_offset_delta != 0:
            sign = "+" if self.shifted_offset_delta > 0 else ""
            lines.append(f"Primary Block Shift  : {sign}0x{abs(self.shifted_offset_delta):X} bytes")
        if self.warnings:
            lines.append("-" * 60)
            lines.append(f"Warnings ({len(self.warnings)}):")
            for w in self.warnings[:10]:
                lines.append(f"  - {w}")
            if len(self.warnings) > 10:
                lines.append(f"  ... and {len(self.warnings) - 10} more warnings")
        lines.append("=" * 60)
        return "\n".join(lines)


class CrossRegionPorter:
    """
    Automates transferring translations across regional game versions.
    """

    def __init__(self, diff_mapper: Optional[BinaryDiffMapper] = None):
        self.diff_mapper = diff_mapper

    # ------------------------------------------------------------------
    # CSV-Level Cross-Region Migration
    # ------------------------------------------------------------------

    def port_csv(
        self,
        source: Union[str, List[TranslationRow]],
        target: Union[str, List[TranslationRow]],
        strategy: str = "index",
        output_csv: Optional[str] = None,
        fallback_to_original: bool = True,
        tolerance_bytes: int = 64,
    ) -> Tuple[List[TranslationRow], PortReport]:
        """
        Migrate translations from source CSV into target CSV.

        Strategies:
            'index': Matches rows by index / ID (ideal when message order is identical).
            'offset': Uses BinaryDiffMapper to correlate source offsets to target offsets.
            'fuzzy': Matches by original English/Japanese text similarity.

        Returns:
            (ported_rows, port_report)
        """
        src_rows = CsvHandler.import_csv(source) if isinstance(source, str) else source
        tgt_rows = CsvHandler.import_csv(target) if isinstance(target, str) else target

        report = PortReport(
            strategy=strategy,
            total_source_strings=len(src_rows),
            total_target_strings=len(tgt_rows),
        )

        ported: List[TranslationRow] = []

        if strategy.lower() == "index":
            # Map source by index
            src_by_id: Dict[int, str] = {
                r.index: (r.translation if r.translation.strip() else r.original)
                for r in src_rows
            }
            for tgt_r in tgt_rows:
                if tgt_r.index in src_by_id:
                    trans = src_by_id[tgt_r.index]
                    ported.append(TranslationRow(
                        index=tgt_r.index,
                        offset=tgt_r.offset,
                        original=tgt_r.original,
                        translation=trans,
                        context=tgt_r.context,
                    ))
                    report.migrated_strings += 1
                else:
                    report.unmatched_strings += 1
                    report.warnings.append(f"Target index {tgt_r.index} ('{tgt_r.original[:20]}') not found in source.")
                    fallback = tgt_r.original if fallback_to_original else ""
                    ported.append(TranslationRow(
                        index=tgt_r.index,
                        offset=tgt_r.offset,
                        original=tgt_r.original,
                        translation=fallback,
                        context=tgt_r.context,
                    ))

        elif strategy.lower() == "offset":
            if not self.diff_mapper:
                raise ValueError("BinaryDiffMapper must be provided to use 'offset' correlation strategy.")

            # Create target lookup by offset
            tgt_by_offset: Dict[int, TranslationRow] = {r.offset: r for r in tgt_rows}
            tgt_offsets = sorted(tgt_by_offset.keys())

            # Correlate each source row to target
            matched_tgt_indices = set()
            src_to_tgt_map: Dict[int, str] = {}

            for src_r in src_rows:
                corr_off = self.diff_mapper.correlate_offset(src_r.offset)
                if corr_off is None:
                    continue

                # Find closest target offset within tolerance
                closest_off = min(tgt_offsets, key=lambda off: abs(off - corr_off))
                if abs(closest_off - corr_off) <= tolerance_bytes:
                    tgt_r = tgt_by_offset[closest_off]
                    trans = src_r.translation if src_r.translation.strip() else src_r.original
                    src_to_tgt_map[tgt_r.index] = trans
                    matched_tgt_indices.add(tgt_r.index)

            for tgt_r in tgt_rows:
                if tgt_r.index in src_to_tgt_map:
                    trans = src_to_tgt_map[tgt_r.index]
                    ported.append(TranslationRow(
                        index=tgt_r.index,
                        offset=tgt_r.offset,
                        original=tgt_r.original,
                        translation=trans,
                        context=tgt_r.context,
                    ))
                    report.migrated_strings += 1
                else:
                    report.unmatched_strings += 1
                    fallback = tgt_r.original if fallback_to_original else ""
                    ported.append(TranslationRow(
                        index=tgt_r.index,
                        offset=tgt_r.offset,
                        original=tgt_r.original,
                        translation=fallback,
                        context=tgt_r.context,
                    ))

        else:
            raise ValueError(f"Unknown strategy: '{strategy}'. Choose from: 'index', 'offset'.")

        if output_csv:
            CsvHandler.export_csv(output_csv, ported)

        return ported, report

    # ------------------------------------------------------------------
    # Binary-Level Cross-Region Migration
    # ------------------------------------------------------------------

    def port_binary(
        self,
        source_data: Union[bytes, bytearray],
        target_data: Union[bytes, bytearray],
        translated_strings: List[str],
        target_table_offset: Optional[int] = None,
        target_pool_offset: Optional[int] = None,
        stride: int = 4,
        endian: str = ">",
        encoding: str = "utf-16-be",
        align: int = 4,
    ) -> Tuple[bytes, PortReport]:
        """
        Port an array of translated strings directly into target_data.
        Locates or uses the target pointer table, constructs a new string pool,
        updates the pointer table, and returns the modified target binary.

        Returns:
            (patched_target_bytes, port_report)
        """
        src_bytes = bytes(source_data)
        tgt_buf = bytearray(target_data)

        # Setup mapper if not present
        if not self.diff_mapper:
            self.diff_mapper = BinaryDiffMapper(src_bytes, bytes(tgt_buf))
            self.diff_mapper.find_matching_blocks()

        report = PortReport(
            strategy="binary_relocate",
            total_source_strings=len(translated_strings),
            total_target_strings=len(translated_strings),
            migrated_strings=len(translated_strings),
        )

        if self.diff_mapper.matches:
            report.shifted_offset_delta = self.diff_mapper.matches[0].delta

        # Find or use target pointer table
        if target_table_offset is None or target_pool_offset is None:
            # Auto-detect target text and pointers
            tgt_strings = StringScanner.scan_strings(bytes(tgt_buf), encoding=encoding, min_length=2)
            tgt_offsets = [s.offset for s in tgt_strings]
            tables = PointerScanner.find_pointer_tables(
                bytes(tgt_buf), tgt_offsets, stride=stride, endian=endian, min_pointers=min(4, len(translated_strings))
            )
            if not tables:
                raise RuntimeError("Could not automatically locate pointer table in target binary. Please provide target_table_offset.")
            best_table = tables[0]
            target_table_offset = best_table.table_offset
            # Estimate pool start as first referenced target offset
            target_pool_offset = min(tgt for _, tgt in best_table.entries)

        # Build new string pool
        pool_builder = StringPoolBuilder(
            encoding=encoding,
            endian=endian,
            stride=stride,
            base_offset=target_pool_offset,
            align=align,
            deduplicate=True,
        )
        pool_builder.add_many(translated_strings)

        new_table_bytes, new_pool_bytes = pool_builder.build()

        # Write new pointer table
        table_len = len(new_table_bytes)
        tgt_buf[target_table_offset:target_table_offset + table_len] = new_table_bytes

        # Relocate string pool
        reloc = BinaryRelocator(tgt_buf, endian=endian)
        # Check old pool size if detectable, or replace range
        old_pool_size = len(new_pool_bytes)  # safe default if expanding
        reloc.replace_range(target_pool_offset, len(new_pool_bytes), new_pool_bytes)

        return reloc.to_bytes(), report
