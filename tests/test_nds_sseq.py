"""
test_nds_sseq.py - Unit tests for Nintendo DS Nitro Sound Sequence (SSEQ)
multi-track parser, compiler, and MIDI transpiler in MioROM.
Zero external dependencies.
"""

import os
import struct
import pytest

from miorom.audio.sseq import SSEQEvent, SSEQSequence, SSEQTrack


def test_mock_sseq_multitrack_roundtrip():
    """Test synthetic multi-track SSEQ compilation, MIDI transpiling, and re-parsing."""
    # Track 0: Master tempo & volume
    t0_events = [
        SSEQEvent(delta_ticks=0, event_type="tempo", channel=0, value=140),
        SSEQEvent(delta_ticks=0, event_type="volume", channel=0, value=120),
        SSEQEvent(delta_ticks=48, event_type="end", channel=0),
    ]
    t0 = SSEQTrack(track_id=0, channel=0, events=t0_events)

    # Track 1: Melody
    t1_events = [
        SSEQEvent(delta_ticks=0, event_type="program_change", channel=1, value=5),
        SSEQEvent(delta_ticks=0, event_type="note", channel=1, note=60, velocity=100, duration=24),
        SSEQEvent(delta_ticks=24, event_type="note", channel=1, note=64, velocity=95, duration=24),
        SSEQEvent(delta_ticks=24, event_type="end", channel=1),
    ]
    t1 = SSEQTrack(track_id=1, channel=1, events=t1_events)

    # Track 2: Bass
    t2_events = [
        SSEQEvent(delta_ticks=0, event_type="program_change", channel=2, value=35),
        SSEQEvent(delta_ticks=0, event_type="note", channel=2, note=36, velocity=110, duration=48),
        SSEQEvent(delta_ticks=48, event_type="end", channel=2),
    ]
    t2 = SSEQTrack(track_id=2, channel=2, events=t2_events)

    seq = SSEQSequence(tracks=[t0, t1, t2], division=48)
    assert len(seq.tracks) == 3

    # Transpile to Standard MIDI Format 1
    midi_bytes = seq.to_midi()
    assert midi_bytes[:4] == b"MThd"
    fmt, ntracks, div = struct.unpack_from(">HHH", midi_bytes, 8)
    assert fmt == 1
    assert ntracks == 3
    assert div == 48

    # Parse MIDI back to SSEQSequence
    reloaded_midi = SSEQSequence.from_midi(midi_bytes)
    assert len(reloaded_midi.tracks) == 3

    # Compile to SSEQ binary
    sseq_bin = seq.to_bytes()
    assert sseq_bin[:4] == b"SSEQ"
    assert sseq_bin[16:20] == b"DATA"

    # Re-parse SSEQ binary
    reloaded_sseq = SSEQSequence.from_bytes(sseq_bin)
    assert len(reloaded_sseq.tracks) == 3


def test_real_rf1_sseq_dataset():
    """Test parsing and MIDI transpilation on actual Rune Factory 1 SSEQ tracks."""
    sseq_dir = "/mnt/sdcard/MiokoTech/Rune Factory 1 nds/workspace/audio/sseq"
    if not os.path.isdir(sseq_dir):
        pytest.skip("Rune Factory 1 SSEQ files not found in workspace/audio/sseq.")

    test_tracks = [
        "SEQ_OPENING.sseq",
        "SEQ_SPRING.sseq",
        "SEQ_SUMMER.sseq",
        "SEQ_FALL.sseq",
        "SEQ_WINTER.sseq",
        "SEQ_BOSS.sseq",
    ]

    for fname in test_tracks:
        fpath = os.path.join(sseq_dir, fname)
        if not os.path.isfile(fpath):
            continue

        with open(fpath, "rb") as f:
            raw_sseq = f.read()

        seq = SSEQSequence.from_bytes(raw_sseq)
        assert len(seq.tracks) > 1, f"Expected multi-track sequence for {fname}, got {len(seq.tracks)}"

        # Transpile to MIDI
        midi_data = seq.to_midi()
        assert midi_data[:4] == b"MThd"
        fmt, ntracks, div = struct.unpack_from(">HHH", midi_data, 8)
        assert fmt == 1
        assert ntracks == len(seq.tracks)
        assert len(midi_data) > 200, f"MIDI data too small for {fname}"
