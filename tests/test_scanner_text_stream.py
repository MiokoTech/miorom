import pytest
from miorom.scanner.text_stream import TextStreamScanner, TextStreamSpan


def test_scan_sjis_text():
    scanner = TextStreamScanner(min_length=3, min_confidence=0.6)

    # Shift-JIS text: "勇者の剣" (Sword of the Hero) + null terminator
    sjis_text = "勇者の剣".encode("shift_jis") + b"\x00"

    # Embedded in pseudo-ROM binary padding
    rom_blob = b"\xFF\xFF\x01\x02\x03\x04" + sjis_text + b"\xFF\xEE\xDD"
    spans = scanner.scan(rom_blob, encodings=["sjis"])

    assert len(spans) == 1
    span = spans[0]
    assert span.start == 6
    assert span.encoding == "sjis"
    assert span.text == "勇者の剣"
    assert span.kanji_count >= 2
    assert span.is_null_terminated is True
    assert span.confidence >= 0.8


def test_scan_euc_jp_text():
    scanner = TextStreamScanner(min_length=3, min_confidence=0.6)

    # EUC-JP text: "ドラゴンクエスト" (Dragon Quest in Katakana) + null terminator
    euc_text = "ドラゴンクエスト".encode("euc_jp") + b"\x00"
    rom_blob = b"\x00\x00\x00" + euc_text + b"\x12\x34"

    spans = scanner.scan(rom_blob, encodings=["euc_jp"])
    assert len(spans) == 1
    span = spans[0]
    assert span.encoding == "euc_jp"
    assert span.text == "ドラゴンクエスト"
    assert span.kana_count >= 4


def test_scan_utf16_text():
    scanner = TextStreamScanner(min_length=3, min_confidence=0.6)

    # UTF-16LE text: "Item Shop"
    utf16_text = "Item Shop".encode("utf-16le") + b"\x00\x00"
    rom_blob = b"\xAA\xBB\xCC\xDD" + utf16_text + b"\x00\x00"

    spans = scanner.scan(rom_blob, encodings=["utf-16le"])
    assert len(spans) == 1
    assert spans[0].text == "Item Shop"
    assert spans[0].encoding == "utf-16le"


def test_rejection_of_random_noise():
    scanner = TextStreamScanner(min_length=4, min_confidence=0.7)

    # Random binary bytes that do not form valid Japanese characters or ASCII strings
    noise = bytes([0x81, 0x01, 0x82, 0x02, 0x90, 0x10, 0x40, 0x05, 0x12, 0x34])
    spans = scanner.scan(noise, encodings=["sjis"])
    assert len(spans) == 0


def test_scan_string_table():
    scanner = TextStreamScanner(min_length=2, min_confidence=0.5)

    # Table of 3 items in Shift-JIS separated by single null bytes
    items = ["ポーション", "エーテル", "エリクサー"]
    table_bytes = b"".join(item.encode("shift_jis") + b"\x00" for item in items)
    rom_blob = b"\x00" * 16 + table_bytes + b"\x00" * 16

    tables = scanner.scan_string_table(rom_blob, encodings=["sjis"], min_strings=3, max_gap=1)
    assert len(tables) == 1
    table = tables[0]
    assert table["count"] == 3
    assert [s.text for s in table["spans"]] == items
