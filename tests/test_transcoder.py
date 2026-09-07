import pytest
from miorom.text import TrieTranscoder


def test_trie_transcoder_basic():
    tt = TrieTranscoder()
    tt.add_mapping(b"\x01", "A")
    tt.add_mapping(b"\x02", "B")
    tt.add_mapping(b"\x81\x40", " ")
    tt.add_mapping(b"\xFE", "[HERO]")

    # Decode test
    raw = b"\x01\x02\x81\x40\xFE\x01"
    decoded = tt.decode(raw)
    assert decoded == "AB [HERO]A"

    # Encode test
    encoded = tt.encode("AB [HERO]A")
    assert encoded == raw


def test_trie_transcoder_greedy_longest_match():
    tt = TrieTranscoder()
    # Ambiguous mappings: "A", "AB", "ABC"
    tt.add_mapping(b"\x10", "A")
    tt.add_mapping(b"\x20", "AB")
    tt.add_mapping(b"\x30", "ABC")

    # Greedy match: "ABC" should encode to \x30, not \x10 + \x20 or \x10 * 3
    assert tt.encode("ABC") == b"\x30"
    assert tt.encode("AB") == b"\x20"
    assert tt.encode("A") == b"\x10"

    # Bytes greedy match
    tt.add_mapping(b"\xAA", "1")
    tt.add_mapping(b"\xAA\xBB", "2")
    tt.add_mapping(b"\xAA\xBB\xCC", "3")

    assert tt.decode(b"\xAA\xBB\xCC") == "3"
    assert tt.decode(b"\xAA\xBB") == "2"
    assert tt.decode(b"\xAA") == "1"


def test_trie_transcoder_load_table():
    tbl_text = """
    # Comment line
    00=<END>
    0A=\\n
    30=0
    31=1
    8260=Ａ
    88=[BUTTON_A]
    """
    tt = TrieTranscoder()
    tt.load_table(tbl_text)

    assert tt.entry_count == 6
    assert tt.decode(b"\x30\x31\x88\x00") == "01[BUTTON_A]<END>"
    assert tt.encode("01[BUTTON_A]<END>") == b"\x30\x31\x88\x00"


def test_trie_transcoder_fallback():
    tt = TrieTranscoder()
    tt.add_mapping(b"\x01", "X")

    # Byte 0xFF is unmapped
    decoded = tt.decode(b"\x01\xFF", fallback_format="[{:02X}]")
    assert decoded == "X[FF]"

    # Char 'Z' is unmapped
    encoded = tt.encode("XZ", fallback_bytes=b"?")
    assert encoded == b"\x01?"
