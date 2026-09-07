"""
miorom.scanner.inspector
~~~~~~~~~~~~~~~~~~~~~~~~
Unified Smart Binary Inspector and Reverse Engineering Assistant.
Combines format fingerprinting, entropy profiling, multi-encoding probing,
pointer array detection, and actionable heuristic suggestions into a single report.
"""

import math
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from miorom.core.scanner import StringScanner, PointerScanner, FoundString, CandidatePointerTable
from miorom.scanner.deep import DeepScanner, BinaryFingerprint, calculate_entropy, calculate_block_entropy


@dataclass
class EncodingCandidate:
    encoding: str
    confidence: float  # 0.0 to 1.0
    string_count: int
    printable_ratio: float
    sample_strings: List[str] = field(default_factory=list)


@dataclass
class InspectionReport:
    filepath: Optional[str]
    size: int
    overall_entropy: float
    entropy_profile: str  # "compressed", "executable", "text", "sparse"
    fingerprints: List[BinaryFingerprint]
    best_encoding: Optional[EncodingCandidate]
    all_encodings: List[EncodingCandidate]
    pointer_tables: List[CandidatePointerTable]
    footer_tables: List[CandidatePointerTable]
    orphans: List[FoundString]
    suggestions: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=" * 78,
            f"MIOROM SMART BINARY INSPECTION REPORT",
            f"Target:   {self.filepath or '<in-memory buffer>'}",
            f"Size:     {self.size:,} bytes (0x{self.size:X})",
            f"Entropy:  {self.overall_entropy:.2f} / 8.00  [{self.entropy_profile.upper()}]",
            "=" * 78,
        ]

        # 1. Format Fingerprints
        lines.append("\n[1] IDENTIFIED CONTAINER & FORMAT FINGERPRINTS:")
        if self.fingerprints:
            for fp in self.fingerprints:
                off_hex = f"0x{fp.offset:08X}"
                conf = f"{int(fp.confidence * 100)}%"
                lines.append(f"  - [{off_hex}] {fp.format_name:<16} ({conf:>4}) : {fp.description}")
        else:
            lines.append("  - No known container or format signatures detected.")

        # 2. Encoding Probing
        lines.append("\n[2] ENCODING AUTO-PROBING & RANKING:")
        if self.best_encoding and self.best_encoding.string_count > 0:
            lines.append(
                f"  ★ Recommended Encoding: '{self.best_encoding.encoding}' "
                f"({int(self.best_encoding.confidence * 100)}% confidence, {self.best_encoding.string_count} strings)"
            )
            for cand in self.all_encodings:
                mark = "✓" if cand == self.best_encoding else " "
                lines.append(
                    f"    [{mark}] {cand.encoding:<12}: {cand.string_count:>5} strings "
                    f"(printable: {cand.printable_ratio*100:>5.1f}%, score: {cand.confidence*100:>5.1f}%)"
                )
            if self.best_encoding.sample_strings:
                lines.append("    Samples:")
                for s in self.best_encoding.sample_strings[:5]:
                    preview = s[:60].replace("\n", "\\n")
                    lines.append(f"      • \"{preview}\"")
        else:
            lines.append("  - No obvious plain text found with tested encodings.")

        # 3. Pointer Tables
        lines.append("\n[3] POINTER TABLES:")
        all_tables = self.pointer_tables + self.footer_tables
        if all_tables:
            for t in self.pointer_tables[:5]:
                lines.append(
                    f"  - Forward Table @ {t.table_offset_hex}: count={t.count}, "
                    f"stride={t.stride}, endian='{t.endian}', confidence={t.confidence:.2f}"
                )
            for t in self.footer_tables[:3]:
                lines.append(
                    f"  - ⚠ Footer Table  @ {t.table_offset_hex}: count={t.count}, "
                    f"stride={t.stride}, endian='{t.endian}' (Secondary Dual-Table Candidate)"
                )
        else:
            lines.append("  - No obvious contiguous pointer tables detected.")

        # 4. Orphans
        if self.orphans:
            lines.append(f"\n[4] ⚠ ORPHANED STRINGS ({len(self.orphans)} detected):")
            for s in self.orphans[:6]:
                preview = s.text[:50].replace("\n", "\\n")
                lines.append(f"  - 0x{s.offset:06X}: \"{preview}\"")
            if len(self.orphans) > 6:
                lines.append(f"  ... and {len(self.orphans) - 6} more orphaned strings.")

        # 5. Actionable Suggestions
        lines.append("\n[5] ACTIONABLE RECOMMENDATIONS:")
        if self.suggestions:
            for s in self.suggestions:
                lines.append(f"  💡 {s}")
        else:
            lines.append("  💡 Binary has standard structure.")

        lines.append("=" * 78)
        return "\n".join(lines)


class SmartInspector:
    """
    Automated inspector that evaluates binary data across all miorom diagnostic engines.
    """

    CANDIDATE_ENCODINGS = ("utf-16-be", "utf-8", "ascii", "utf-16-le", "shift_jis", "cp1252")

    @classmethod
    def inspect(cls, data: bytes, filepath: Optional[str] = None) -> InspectionReport:
        sz = len(data)
        if sz == 0:
            return InspectionReport(
                filepath=filepath, size=0, overall_entropy=0.0,
                entropy_profile="empty", fingerprints=[], best_encoding=None,
                all_encodings=[], pointer_tables=[], footer_tables=[],
                orphans=[], suggestions=["File is empty (0 bytes)."]
            )

        # 1. Deep Format Fingerprints
        deep_report = DeepScanner().scan(data, min_confidence=0.5)
        fingerprints = deep_report.fingerprints

        # 2. Entropy Analysis
        ent = deep_report.overall_entropy
        if ent >= 7.2:
            entropy_profile = "compressed / encrypted"
        elif ent >= 4.5:
            entropy_profile = "executable / bytecode"
        elif ent >= 2.0:
            entropy_profile = "text / mixed structures"
        else:
            entropy_profile = "sparse / mostly zeroes"

        # 3. Encoding Probing
        encoding_candidates = cls._probe_encodings(data)
        best_enc = encoding_candidates[0] if encoding_candidates and encoding_candidates[0].string_count > 0 else None

        # 4. Pointer Table Scanning with best encoding
        pointer_tables: List[CandidatePointerTable] = []
        footer_tables: List[CandidatePointerTable] = []
        orphans: List[FoundString] = []

        if best_enc and best_enc.string_count >= 2:
            used_enc = best_enc.encoding
            found_strings = StringScanner.scan_strings(data, min_length=4, encoding=used_enc)
            offsets = [s.offset for s in found_strings]

            pointer_tables = PointerScanner.find_pointer_tables(data, offsets)
            footer_tables = PointerScanner.find_footer_pointer_tables(data, offsets)

            # Filter duplicate table offsets
            t1_offsets = {t.table_offset for t in pointer_tables}
            footer_tables = [t for t in footer_tables if t.table_offset not in t1_offsets]

            # Orphan calculation
            ref_offsets = set()
            for t in pointer_tables + footer_tables:
                for _, tgt in t.entries:
                    ref_offsets.add(tgt)
            orphans = [s for s in found_strings if s.offset not in ref_offsets]

        # 5. Formulate Suggestions
        suggestions = cls._generate_suggestions(
            sz, entropy_profile, fingerprints, best_enc, pointer_tables, footer_tables, orphans
        )

        return InspectionReport(
            filepath=filepath,
            size=sz,
            overall_entropy=ent,
            entropy_profile=entropy_profile,
            fingerprints=fingerprints,
            best_encoding=best_enc,
            all_encodings=encoding_candidates,
            pointer_tables=pointer_tables,
            footer_tables=footer_tables,
            orphans=orphans,
            suggestions=suggestions,
        )

    @classmethod
    def _probe_encodings(cls, data: bytes) -> List[EncodingCandidate]:
        results: List[EncodingCandidate] = []
        # Sample first 256KB to keep probing fast even on massive 500MB payloads
        sample = data[:256 * 1024]

        # Common English/natural character frequency test
        vowel_regex = re.compile(r"[aeiouyAEIOUY]")

        for enc in cls.CANDIDATE_ENCODINGS:
            try:
                strings = StringScanner.scan_strings(sample, min_length=4, encoding=enc)
            except Exception:
                continue

            if not strings:
                results.append(EncodingCandidate(encoding=enc, confidence=0.0, string_count=0, printable_ratio=0.0))
                continue

            # Calculate natural readability score
            total_chars = sum(len(s.text) for s in strings)
            total_vowels = sum(len(vowel_regex.findall(s.text)) for s in strings)
            vowel_ratio = (total_vowels / total_chars) if total_chars > 0 else 0.0

            # Natural human text typically has 25% - 45% vowels
            natural_penalty = 1.0 - min(1.0, abs(vowel_ratio - 0.35) * 2.0)

            # High density of strings boosts score
            count_factor = min(1.0, len(strings) / 50.0)
            score = (count_factor * 0.5) + (natural_penalty * 0.5)

            results.append(EncodingCandidate(
                encoding=enc,
                confidence=round(score, 2),
                string_count=len(strings),
                printable_ratio=round(vowel_ratio, 2),
                sample_strings=[s.text for s in strings[:5]]
            ))

        results.sort(key=lambda c: (c.confidence, c.string_count), reverse=True)
        return results

    @classmethod
    def _generate_suggestions(
        cls,
        sz: int,
        entropy_profile: str,
        fingerprints: List[BinaryFingerprint],
        best_enc: Optional[EncodingCandidate],
        pointer_tables: List[CandidatePointerTable],
        footer_tables: List[CandidatePointerTable],
        orphans: List[FoundString],
    ) -> List[str]:
        suggestions: List[str] = []

        fp_names = {fp.format_name for fp in fingerprints}

        if "Neverland_NLCM" in fp_names:
            suggestions.append("Detected Neverland TOC Archive (NLCM). Use 'miorom toc <bin> <dat> list' to inspect contents.")
        elif "Neverland_FEFE" in fp_names or footer_tables:
            suggestions.append("Detected Dual-Table Text Container. Must preserve footer metadata and Table 2 pointers during repack.")
        elif "Neverland_Script" in fp_names:
            suggestions.append("Detected Multi-Section Script Module. Section offsets and EOF relocation table must be shifted on repack.")
        elif "U8" in fp_names or "NARC" in fp_names:
            fmt = "u8" if "U8" in fp_names else "narc"
            suggestions.append(f"Detected {fmt.upper()} container. Unpack with 'miorom unpack <file> -f {fmt}'.")

        if entropy_profile == "compressed / encrypted":
            suggestions.append("High entropy detected (>7.2). Data is likely compressed (LZ10/LZ11/Yaz0) or encrypted.")

        if orphans:
            suggestions.append(
                f"Found {len(orphans)} unreferenced strings. Check footer for secondary pointer tables or hardcoded references."
            )

        if best_enc and best_enc.confidence >= 0.5:
            suggestions.append(f"Extract text using: miorom scan <file> -e {best_enc.encoding} -p --orphans -o dialogue.csv")

        return suggestions
