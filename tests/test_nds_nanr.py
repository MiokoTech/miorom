"""
Unit tests for Nintendo DS NANR (Nitro Animation Resource) animation sequences.
"""

import pytest
from miorom.platforms.nds.nanr import NANRFile, NANRSequence, NANRFrame
from miorom.errors import ParseError


def test_nanr_roundtrip():
    # Sequence 0: 2 frames (idle)
    f0 = NANRFrame(cell_index=0, delay=10)
    f1 = NANRFrame(cell_index=1, delay=12)
    seq0 = NANRSequence(frames=[f0, f1], play_mode=0, name="idle")

    # Sequence 1: 1 frame (attack)
    f2 = NANRFrame(cell_index=2, delay=5)
    seq1 = NANRSequence(frames=[f2], play_mode=1, name="attack")

    nanr = NANRFile(sequences=[seq0, seq1])
    assert nanr.sequence_count == 2
    assert nanr.total_frames == 3
    assert seq0.total_duration == 22
    assert seq1.total_duration == 5

    raw = nanr.to_bytes()
    assert raw[:4] == b"RNAN"

    reloaded = NANRFile.from_bytes(raw)
    assert reloaded.sequence_count == 2
    assert reloaded.total_frames == 3

    r_s0 = reloaded.sequences[0]
    assert r_s0.frame_count == 2
    assert r_s0.play_mode == 0
    assert r_s0.frames[0].cell_index == 0
    assert r_s0.frames[0].delay == 10
    assert r_s0.frames[1].cell_index == 1
    assert r_s0.frames[1].delay == 12

    r_s1 = reloaded.sequences[1]
    assert r_s1.frame_count == 1
    assert r_s1.play_mode == 1
    assert r_s1.frames[0].cell_index == 2
    assert r_s1.frames[0].delay == 5


def test_nanr_invalid_magic():
    with pytest.raises(ParseError):
        NANRFile.from_bytes(b"BAD!\x00\x00\x00\x00" * 4)

    with pytest.raises(ParseError):
        NANRFile.from_bytes(b"")
