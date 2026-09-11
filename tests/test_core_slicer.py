import pytest
from miorom.core.slicer import (
    align_up,
    align_down,
    pad_bytes,
    chunk_bytes,
    find_free_blocks,
    BinarySlicer,
)


def test_align_math():
    assert align_up(0, 16) == 0
    assert align_up(1, 16) == 16
    assert align_up(16, 16) == 16
    assert align_up(17, 16) == 32

    assert align_down(0, 16) == 0
    assert align_down(15, 16) == 0
    assert align_down(16, 16) == 16
    assert align_down(31, 16) == 16

    with pytest.raises(ValueError):
        align_up(10, 0)


def test_pad_bytes():
    data = b"\x01\x02\x03"
    padded = pad_bytes(data, alignment=4, pad_byte=0xFF)
    assert padded == b"\x01\x02\x03\xFF"
    assert len(padded) == 4

    already_aligned = pad_bytes(b"\x01\x02\x03\x04", alignment=4)
    assert already_aligned == b"\x01\x02\x03\x04"


def test_chunk_bytes():
    data = b"0123456789"
    chunks = list(chunk_bytes(data, chunk_size=3))
    assert len(chunks) == 4
    assert chunks[0] == b"012"
    assert chunks[1] == b"345"
    assert chunks[2] == b"678"
    assert chunks[3] == b"9"


def test_find_free_blocks():
    # Buffer with two 0xFF blocks
    data = bytearray(b"\x00" * 10)
    data.extend(b"\xFF" * 32)  # offset 10..42
    data.extend(b"\x00" * 20)
    data.extend(b"\xFF" * 16)  # offset 62..78

    blocks = find_free_blocks(data, fill_byte=0xFF, min_size=16)
    assert len(blocks) == 2
    assert blocks[0] == (10, 32)
    assert blocks[1] == (62, 16)

    # With alignment=16
    # Block 1 starts at 10, align_up to 16 -> start at 16, length 32 - 6 = 26 (>= 16)
    aligned_blocks = find_free_blocks(data, fill_byte=0xFF, min_size=16, alignment=16)
    assert len(aligned_blocks) == 1
    assert aligned_blocks[0] == (16, 26)


def test_binary_slicer():
    raw = b"HELLO_ROM_HACKING_WORLD_HELLO"
    slicer = BinarySlicer(raw)
    assert len(slicer) == len(raw)

    sl = slicer.slice(0, 5)
    assert bytes(sl) == b"HELLO"

    first = slicer.find(b"HELLO")
    assert first == 0
    all_occurrences = slicer.find_all(b"HELLO")
    assert all_occurrences == [0, 24]

    replaced = slicer.replace_slice(0, b"HOWDY")
    assert replaced.startswith(b"HOWDY_ROM")
