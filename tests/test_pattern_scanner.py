import os
import tempfile
import pytest

from miorom.scanner.pattern import AOBPatternScanner, CompiledPattern, PatternMatch


def test_aob_pattern_compile_and_find_first():
    # Buffer with ARM stack push and comparison
    buf = b"\x00\x00\x00\x00\x1F\x40\x2D\xE9\x12\x34\x56\x78\x00\x00\x50\xE3\xFF\xFF"

    pattern = "1F 40 2D E9 ?? ?? ?? ?? 00 00 50 E3"
    match = AOBPatternScanner.find_first(buf, pattern, base_address=0x02000000)

    assert match is not None
    assert match.offset == 4
    assert match.address == 0x02000004
    assert match.size == 12
    assert match.data == b"\x1F\x40\x2D\xE9\x12\x34\x56\x78\x00\x00\x50\xE3"


def test_aob_pattern_find_all_and_limit():
    pat = "AA ?? BB"
    buf = b"\x00\xAA\x10\xBB\x00\x00\xAA\x20\xBB\x00\xAA\x30\xBB\xFF"

    matches = AOBPatternScanner.find_all(buf, pat)
    assert len(matches) == 3
    assert matches[0].offset == 1
    assert matches[1].offset == 6
    assert matches[2].offset == 10

    # Test max_matches
    limited = AOBPatternScanner.find_all(buf, pat, max_matches=2)
    assert len(limited) == 2
    assert limited[0].offset == 1
    assert limited[1].offset == 6


def test_aob_scan_file_across_chunk_boundary():
    # Create file with pattern split across 64-byte chunk boundary
    with tempfile.NamedTemporaryFile(delete=False) as f:
        tmp_path = f.name
        f.write(b"X" * 60)
        f.write(b"\xDE\xAD\xBE\xEF\xCA\xFE")  # Straddles boundary 60-66
        f.write(b"Y" * 100)

    try:
        pat = "DE AD ?? EF CA FE"
        matches = AOBPatternScanner.scan_file(tmp_path, pat, chunk_size=64)
        assert len(matches) == 1
        assert matches[0].offset == 60
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def test_aob_replace_preserving_wildcards():
    buf = bytearray(b"\x11\x22\x33\x44\x55\x00\x11\x22\x99\x44\x55")

    # Replace 11 22 ?? 44 55 with AA BB ?? CC DD
    # The middle byte (0x33, 0x99) should be preserved!
    count = AOBPatternScanner.replace(
        buf,
        pattern="11 22 ?? 44 55",
        replacement="AA BB ?? CC DD",
    )

    assert count == 2
    assert buf[0:5] == b"\xAA\xBB\x33\xCC\xDD"
    assert buf[6:11] == b"\xAA\xBB\x99\xCC\xDD"


def test_aob_create_pattern():
    data = b"\x01\x02\x03\x04\x05"
    pat = AOBPatternScanner.create_pattern(data, wildcard_indices=[1, 3])
    assert pat == "01 ?? 03 ?? 05"
