"""
Unit tests for miorom.script.boundary_detector.
"""

import pytest

from miorom.script.boundary_detector import (
    DelimiterCandidate,
    ControlCodeCandidate,
    ScriptBoundaryReport,
    detect_delimiters,
    detect_control_codes,
    analyze_script_boundaries,
    slice_script_entries,
)


def test_detect_delimiters_single_byte():
    # Build a simulated ROM buffer with 0xFF terminated strings
    buf = bytearray()
    targets = []

    strings = [b"HELLO", b"WARRIOR", b"DEFEND", b"ATTACK", b"VICTORY"]
    for s in strings:
        targets.append(len(buf))
        buf.extend(s)
        buf.append(0xFF)

    candidates = detect_delimiters(bytes(buf), targets)
    assert len(candidates) >= 1
    best = candidates[0]
    assert best.byte_sequence == b"\xFF"
    assert best.hex_representation == "FF"
    assert best.ratio == 1.0
    assert best.confidence == 1.0


def test_detect_delimiters_multi_byte():
    # 2-byte terminator: 0xFE 0x00
    buf = bytearray()
    targets = []

    dialogues = [b"Welcome traveler", b"Beware the cave", b"Take this sword", b"Good luck"]
    for d in dialogues:
        targets.append(len(buf))
        buf.extend(d)
        buf.extend(b"\xFE\x00")

    candidates = detect_delimiters(bytes(buf), targets, max_delimiter_len=2)
    # The 0x00 byte is at boundary-1, and 0xFE 0x00 is at boundary-2..boundary
    found_2byte = any(c.byte_sequence == b"\xFE\x00" for c in candidates)
    assert found_2byte is True


def test_detect_control_codes_with_args():
    # Opcode 0x05 followed by 1 byte argument (e.g. <COLOR:X>)
    # Opcode 0x02 with 0 args (e.g. <WAIT>)
    buf = bytearray()
    targets = []

    lines = [
        b"Hi \x05\x01Hero\x02",
        b"Go \x05\x02North\x02",
        b"Find \x05\x03Key\x02",
        b"Open \x05\x01Gate\x02",
    ]

    for line in lines:
        targets.append(len(buf))
        buf.extend(line)
        buf.append(0x00)

    cc_list = detect_control_codes(bytes(buf), targets, terminator=b"\x00")
    opcodes = {c.opcode: c for c in cc_list}

    assert 0x05 in opcodes
    assert opcodes[0x05].estimated_arg_length == 1
    assert 0x02 in opcodes
    assert opcodes[0x02].is_trailing is True


def test_analyze_script_boundaries_report():
    buf = bytearray()
    targets = []
    for word in [b"FIRST", b"SECOND", b"THIRD", b"FOURTH"]:
        targets.append(len(buf))
        buf.extend(word)
        buf.append(0x00)

    report = analyze_script_boundaries(bytes(buf), targets)
    assert report.total_strings == 4
    assert report.primary_terminator == b"\x00"
    assert report.min_length > 0
    assert report.max_length > 0
    assert report.average_length > 0
    assert len(report.delimiter_candidates) > 0


def test_slice_script_entries():
    buf = bytearray()
    targets = []
    for s in [b"APPLE\x00", b"BANANA\x00", b"CHERRY\x00"]:
        targets.append(len(buf))
        buf.extend(s)

    with_term = slice_script_entries(bytes(buf), targets, terminator=b"\x00", strip_terminator=False)
    assert with_term == [b"APPLE\x00", b"BANANA\x00", b"CHERRY\x00"]

    stripped = slice_script_entries(bytes(buf), targets, terminator=b"\x00", strip_terminator=True)
    assert stripped == [b"APPLE", b"BANANA", b"CHERRY"]
