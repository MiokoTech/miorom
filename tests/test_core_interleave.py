import pytest
from miorom.core.interleave import (
    combine_split_words,
    split_words,
    deinterleave_channels,
    interleave_channels,
)


def test_combine_split_words_16bit():
    # NES pointer table split: Low bytes and High bytes
    lows = [0x10, 0x20, 0x30]
    highs = [0x80, 0x81, 0x82]

    words_le = combine_split_words(lows, highs, endian="<")
    assert words_le == [0x8010, 0x8120, 0x8230]

    words_be = combine_split_words(lows, highs, endian=">")
    assert words_be == [0x1080, 0x2081, 0x3082]

    # Length mismatch
    with pytest.raises(ValueError):
        combine_split_words([0x10], [0x80, 0x81])


def test_combine_split_words_24bit_bank():
    # SNES 24-bit pointer: Low, High, Bank
    lows = [0x00, 0x50]
    highs = [0x80, 0x90]
    banks = [0x01, 0x02]

    words = combine_split_words(lows, highs, bank_bytes=banks, endian="<")
    assert words == [0x018000, 0x029050]


def test_split_words_roundtrip():
    original = [0x8010, 0x8120, 0x8230, 0xFFFF]
    lanes = split_words(original, word_size=2, endian="<")
    assert len(lanes) == 2

    recombined = combine_split_words(lanes[0], lanes[1], endian="<")
    assert recombined == original


def test_channel_interleave_roundtrip():
    # Simulate even/odd byte interleave
    even = b"\x00\x02\x04\x06"
    odd = b"\x01\x03\x05\x07"

    interleaved = interleave_channels([even, odd], word_size=1)
    assert interleaved == b"\x00\x01\x02\x03\x04\x05\x06\x07"

    deinterleaved = deinterleave_channels(interleaved, num_channels=2, word_size=1)
    assert deinterleaved[0] == even
    assert deinterleaved[1] == odd

    # Word size = 2 (e.g. 16-bit stereo PCM)
    left_16 = b"\x10\x00\x20\x00"
    right_16 = b"\x30\x00\x40\x00"

    stereo = interleave_channels([left_16, right_16], word_size=2)
    assert stereo == b"\x10\x00\x30\x00\x20\x00\x40\x00"

    chans = deinterleave_channels(stereo, num_channels=2, word_size=2)
    assert chans[0] == left_16
    assert chans[1] == right_16
