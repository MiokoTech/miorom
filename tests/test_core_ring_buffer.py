import pytest
from miorom.core.ring_buffer import RingBuffer, LzssMatchFinder


def test_ring_buffer_basic():
    rb = RingBuffer(capacity=8, fill_byte=0x00)
    assert rb.capacity == 8
    assert rb.head == 0

    rb.write_bytes(b"\x01\x02\x03\x04")
    assert rb.head == 4
    assert rb.total_written == 4
    assert rb.read_relative(1) == 0x04
    assert rb.read_relative(4) == 0x01

    # Overwrite buffer to test wrap-around
    rb.write_bytes(b"\x05\x06\x07\x08\x09")
    # Total written = 9. Head = 1.
    assert rb.head == 1
    assert rb.total_written == 9
    assert rb.read_relative(1) == 0x09
    assert rb.get_chronological_window() == b"\x02\x03\x04\x05\x06\x07\x08\x09"


def test_ring_buffer_lz_overlapping_copy():
    rb = RingBuffer(capacity=16)
    rb.write_byte(ord("A"))

    # RLE repeat: distance_back=1, length=5 -> should write "AAAAA"
    copied = rb.copy_lz_match(distance_back=1, length=5)
    assert copied == b"AAAAA"
    assert rb.get_chronological_window() == b"AAAAAA"

    # Pattern repeat: "ABC"
    rb.write_bytes(b"BC")
    # Buffer now has "...AAAAAABC", head is at 8
    # Copy "ABC" 4 times (distance_back=3, length=12)
    copied_pat = rb.copy_lz_match(distance_back=3, length=6)
    assert copied_pat == b"ABCABC"


def test_lzss_match_finder():
    finder = LzssMatchFinder(window_size=32, min_match=3, max_match=10)
    data = b"ABCDEFG_ABCDEFG_123456"

    # Register first occurrence "ABCDEFG_"
    for i in range(8):
        finder.register_position(data, i)

    # At pos 8, data is "ABCDEFG_"
    dist, length = finder.find_longest_match(data, pos=8)
    assert dist == 8  # 8 bytes back
    assert length == 8  # "ABCDEFG_" is 8 bytes long

    # At pos 16, data is "_123456", no match
    dist2, length2 = finder.find_longest_match(data, pos=16)
    assert dist2 == 0
    assert length2 == 0


def test_lzss_match_finder_window_pruning():
    finder = LzssMatchFinder(window_size=10, min_match=3, max_match=10)
    data = b"ABC_0123456789_ABC"

    # Register "ABC_" at 0..3
    for i in range(4):
        finder.register_position(data, i)

    # Pos 15 ("ABC") is > window_size (10) away from pos 0
    dist, length = finder.find_longest_match(data, pos=15)
    # Match at pos 0 has expired from the 10-byte window
    assert dist == 0
    assert length == 0
