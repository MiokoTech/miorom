"""Tests for miorom.script.extractor."""

import csv
import io
import pytest

from miorom.text.charmap import CharMap
from miorom.script.extractor import (
    ScriptExtractor,
    ExtractedEntry,
    ExtractionResult,
    InsertionReport,
)


def make_charmap() -> CharMap:
    """Build a simple ASCII-like CharMap for testing."""
    cm = CharMap()
    for i in range(32, 127):
        cm.add_mapping(bytes([i]), chr(i))
    return cm


def make_rom(*strings: str) -> bytes:
    """Pack strings separated by null bytes into a byte buffer."""
    parts = []
    offsets = []
    pos = 0
    for s in strings:
        offsets.append(pos)
        encoded = s.encode("ascii") + b"\x00"
        parts.append(encoded)
        pos += len(encoded)
    return b"".join(parts), offsets


class TestExtract:
    def test_reads_strings_by_offset(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        rom_bytes = b"Hello\x00World\x00"
        result = extractor.extract(rom_bytes, [0, 6])
        assert result.entries[0].decoded_text == "Hello"
        assert result.entries[1].decoded_text == "World"

    def test_entry_count_matches_offsets(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        rom_bytes = b"Abc\x00Def\x00Ghi\x00"
        result = extractor.extract(rom_bytes, [0, 4, 8])
        assert len(result.entries) == 3

    def test_entry_indices_are_sequential(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        rom_bytes = b"Abc\x00Def\x00"
        result = extractor.extract(rom_bytes, [0, 4])
        assert result.entries[0].index == 0
        assert result.entries[1].index == 1

    def test_entry_offset_stored(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        rom_bytes = b"\x00Hello\x00"
        result = extractor.extract(rom_bytes, [1])
        assert result.entries[0].offset == 1

    def test_total_bytes_accumulates(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        rom_bytes = b"Hi\x00Bye\x00"
        result = extractor.extract(rom_bytes, [0, 3])
        assert result.total_bytes == 5

    def test_raw_bytes_stored(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        rom_bytes = b"AB\x00"
        result = extractor.extract(rom_bytes, [0])
        assert result.entries[0].raw_bytes == b"AB"

    def test_control_codes_tagged(self):
        cm = make_charmap()
        control_codes = {b"\xff": "[END]", b"\xfe": "[NL]"}
        extractor = ScriptExtractor(cm, end_token=b"\x00", control_codes=control_codes)
        rom_bytes = b"Hi\xfe\xff\x00"
        result = extractor.extract(rom_bytes, [0])
        assert "[NL]" in result.entries[0].control_codes
        assert "[END]" in result.entries[0].control_codes

    def test_empty_offsets(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        result = extractor.extract(b"Hello\x00", [])
        assert result.entries == []
        assert result.total_bytes == 0

    def test_charmap_name_set(self):
        cm = make_charmap()
        extractor = ScriptExtractor(cm)
        result = extractor.extract(b"X\x00", [0])
        assert result.charmap_name == "CharMap"


class TestToTxt:
    def setup_method(self):
        self.cm = make_charmap()
        self.extractor = ScriptExtractor(self.cm)

    def test_contains_index_header(self):
        result = self.extractor.extract(b"Hello\x00", [0])
        txt = self.extractor.to_txt(result)
        assert "[0000]" in txt

    def test_contains_offset_hex(self):
        result = self.extractor.extract(b"\x00Hello\x00", [1])
        txt = self.extractor.to_txt(result)
        assert "Offset=0x0001" in txt

    def test_contains_text(self):
        result = self.extractor.extract(b"Hello\x00", [0])
        txt = self.extractor.to_txt(result)
        assert "Hello" in txt

    def test_contains_separator(self):
        result = self.extractor.extract(b"Hello\x00", [0])
        txt = self.extractor.to_txt(result)
        assert "---" in txt


class TestFromTxt:
    def setup_method(self):
        self.cm = make_charmap()
        self.extractor = ScriptExtractor(self.cm)

    def test_roundtrip_single_entry(self):
        result = self.extractor.extract(b"Hello\x00", [0])
        txt = self.extractor.to_txt(result)
        pairs = self.extractor.from_txt(txt)
        assert len(pairs) == 1
        assert pairs[0] == (0, "Hello")

    def test_roundtrip_multiple_entries(self):
        result = self.extractor.extract(b"Hi\x00Bye\x00", [0, 3])
        txt = self.extractor.to_txt(result)
        pairs = self.extractor.from_txt(txt)
        assert len(pairs) == 2
        assert pairs[0][1] == "Hi"
        assert pairs[1][1] == "Bye"

    def test_index_correct(self):
        result = self.extractor.extract(b"A\x00B\x00C\x00", [0, 2, 4])
        txt = self.extractor.to_txt(result)
        pairs = self.extractor.from_txt(txt)
        indices = [p[0] for p in pairs]
        assert indices == [0, 1, 2]

    def test_empty_txt_returns_empty(self):
        pairs = self.extractor.from_txt("")
        assert pairs == []


class TestToCsv:
    def setup_method(self):
        self.cm = make_charmap()
        self.extractor = ScriptExtractor(self.cm)

    def test_valid_csv_with_header(self):
        result = self.extractor.extract(b"Hello\x00", [0])
        csv_str = self.extractor.to_csv(result)
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert rows[0]["source"] == "Hello"
        assert "index" in reader.fieldnames
        assert "translation" in reader.fieldnames

    def test_csv_row_count_matches_entries(self):
        result = self.extractor.extract(b"A\x00B\x00C\x00", [0, 2, 4])
        csv_str = self.extractor.to_csv(result)
        reader = csv.DictReader(io.StringIO(csv_str))
        rows = list(reader)
        assert len(rows) == 3

    def test_translation_column_empty(self):
        result = self.extractor.extract(b"Hello\x00", [0])
        csv_str = self.extractor.to_csv(result)
        reader = csv.DictReader(io.StringIO(csv_str))
        row = next(reader)
        assert row["translation"] == ""


class TestInsert:
    def setup_method(self):
        self.cm = make_charmap()
        self.extractor = ScriptExtractor(self.cm)

    def test_writes_encoded_bytes(self):
        rom = bytearray(b"Hello\x00World\x00")
        result, report = self.extractor.insert(rom, [0, 6], ["Hola", "Mundo"])
        assert result[0:4] == b"Hola"

    def test_preserves_other_data(self):
        rom = bytearray(b"Hi\x00World\x00")
        result, report = self.extractor.insert(rom, [0], ["Hi"])
        assert result[3:8] == b"World"

    def test_report_inserted_count(self):
        rom = bytearray(b"Hello\x00World\x00")
        _, report = self.extractor.insert(rom, [0, 6], ["Hola", "Mundo"])
        assert report.inserted == 2

    def test_report_total_entries(self):
        rom = bytearray(b"Hello\x00World\x00")
        _, report = self.extractor.insert(rom, [0, 6], ["Hola", "Mundo"])
        assert report.total_entries == 2

    def test_dry_run_does_not_modify_rom(self):
        rom = bytearray(b"Hello\x00")
        original = bytes(rom)
        result, report = self.extractor.insert(rom, [0], ["Hola"], dry_run=True)
        assert bytes(result) == original

    def test_dry_run_report_has_correct_counts(self):
        rom = bytearray(b"Hello\x00")
        _, report = self.extractor.insert(rom, [0], ["Hola"], dry_run=True)
        assert report.inserted == 1

    def test_overflow_detection(self):
        rom = bytearray(b"Hi\x00")
        _, report = self.extractor.insert(rom, [0], ["Overflow text here"])
        assert len(report.overflow_warnings) == 1
        assert "overflow" in report.overflow_warnings[0].lower()

    def test_no_overflow_warning_when_fits(self):
        rom = bytearray(b"Hello\x00")
        _, report = self.extractor.insert(rom, [0], ["Hi"])
        assert report.overflow_warnings == []

    def test_insert_bytes_only_writes_bytes_target_accepts(self):
        rom = bytearray(b"Hello\x00")
        result, _ = self.extractor.insert(rom, [0], ["Hi"])
        assert result[2] == ord("\x00")
