import pytest
from miorom.audio import SSEQSequence, SSEQEvent


def test_sseq_compile_and_disassemble():
    events = [
        SSEQEvent(delta_ticks=0, event_type="tempo", value=130),
        SSEQEvent(delta_ticks=0, event_type="program_change", channel=0, value=5),
        SSEQEvent(delta_ticks=0, event_type="volume", channel=0, value=90),
        SSEQEvent(delta_ticks=0, event_type="note", channel=0, note=60, velocity=100, duration=48),
        SSEQEvent(delta_ticks=48, event_type="note", channel=0, note=64, velocity=110, duration=48),
        SSEQEvent(delta_ticks=48, event_type="note", channel=0, note=67, velocity=120, duration=96),
        SSEQEvent(delta_ticks=96, event_type="end"),
    ]

    seq = SSEQSequence(events=events)
    sseq_bytes = seq.to_bytes()

    assert sseq_bytes[:4] == b"SSEQ"
    assert sseq_bytes[16:20] == b"DATA"

    # Disassemble back
    disassembled = SSEQSequence.from_bytes(sseq_bytes)
    assert len(disassembled.events) >= 5

    # Check tempo
    tempo_ev = next(e for e in disassembled.events if e.event_type == "tempo")
    assert tempo_ev.value == 130

    # Check notes
    notes = [e for e in disassembled.events if e.event_type == "note"]
    assert len(notes) == 3
    assert notes[0].note == 60
    assert notes[1].note == 64
    assert notes[2].note == 67


def test_sseq_to_midi_and_back():
    events = [
        SSEQEvent(delta_ticks=0, event_type="tempo", value=120),
        SSEQEvent(delta_ticks=0, event_type="program_change", channel=0, value=1),
        SSEQEvent(delta_ticks=0, event_type="note", channel=0, note=72, velocity=100, duration=24),
        SSEQEvent(delta_ticks=24, event_type="note", channel=0, note=74, velocity=100, duration=24),
        SSEQEvent(delta_ticks=24, event_type="end"),
    ]

    seq = SSEQSequence(events=events)
    midi_bytes = seq.to_midi(division=48)

    assert midi_bytes[:4] == b"MThd"
    assert b"MTrk" in midi_bytes

    # Parse back from MIDI
    parsed_seq = SSEQSequence.from_midi(midi_bytes)
    assert len(parsed_seq.events) >= 3

    parsed_notes = [e for e in parsed_seq.events if e.event_type == "note"]
    assert len(parsed_notes) == 2
    assert parsed_notes[0].note == 72
    assert parsed_notes[1].note == 74
