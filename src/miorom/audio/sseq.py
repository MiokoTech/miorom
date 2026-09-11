"""
sseq.py - Nintendo DS Nitro Sound Sequence (SSEQ) Parser, Compiler, and MIDI Transpiler.

Supports:
- Parsing and disassembling single-track and polyphonic multi-track Nitro SSEQ bytecodes (0xFE track allocation, 0x93 track routing, 0x94 branching).
- Transpiling multi-track SSEQ sequences into Standard MIDI (.mid) Format 1 files with tempo, program changes, pitch bend, pan, volume, and expression.
- Compiling Standard MIDI (Format 0 and Format 1) into valid Nintendo DS SSEQ binary containers.
"""

from __future__ import annotations

import io
import math
import os
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from miorom.errors import ParseError
from miorom.result import MioRomResult


def read_vlq(data: bytes, pos: int) -> Tuple[int, int]:
    """Reads a Variable-Length Quantity (VLQ) from data at pos. Returns (value, new_pos)."""
    val = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return val, pos


def write_vlq(val: int) -> bytes:
    """Encodes an integer as a Variable-Length Quantity (VLQ)."""
    buf = bytearray([val & 0x7F])
    val >>= 7
    while val > 0:
        buf.append((val & 0x7F) | 0x80)
        val >>= 7
    return bytes(reversed(buf))


@dataclass
class SSEQEvent(MioRomResult):
    """Represents a discrete musical or control event in an SSEQ track.

    event_type values:
        "note"           — pitched note-on with duration
        "rest"           — silent wait (delta accumulation)
        "tempo"          — BPM change (value = BPM)
        "program_change" — instrument patch select (value = patch 0..127)
        "pan"            — stereo pan CC10 (value = 0..127, center=64)
        "volume"         — channel volume CC7 (value = 0..127)
        "expression"     — expression CC11 (value = 0..127)
        "pitch_bend"     — signed pitch bend (value = signed int8, maps to ±100 cents)
        "pitch_bend_range" — pitch bend sensitivity in semitones (value = semitones, emitted as MIDI RPN 0)
        "attack"         — ADSR attack rate (value = 0..127, MIDI CC73)
        "decay"          — ADSR decay rate (value = 0..127, MIDI CC75)
        "sustain"        — ADSR sustain level (value = 0..127, MIDI CC70)
        "release"        — ADSR release rate (value = 0..127, MIDI CC72)
        "loop_start"     — loop start marker (MIDI Marker 'LOOPSTART')
        "loop_end"       — loop end marker (MIDI Marker 'LOOPEND')
        "end"            — end of track (0xFF)
    """

    delta_ticks: int
    event_type: str
    channel: int = 0
    note: int = 60
    velocity: int = 100
    duration: int = 48
    value: int = 0


def _inject_loop_start(events: List["SSEQEvent"], loop_target_offset: int, channel: int) -> None:
    """Retroactively inserts a loop_start marker into an events list.

    The loop target byte offset corresponds to the start of a bytecode loop body.
    We track cumulative byte offsets via the '_byte_offset' attribute stored on
    events during parsing, and insert the marker immediately before the first event
    whose byte offset meets or exceeds the target. If no such attribute is present
    (synthetic events), we fall back to inserting at the beginning of the list.
    """
    insert_idx = 0
    for i, ev in enumerate(events):
        offset = getattr(ev, "_byte_offset", None)
        if offset is not None and offset >= loop_target_offset:
            insert_idx = i
            break

    marker = SSEQEvent(delta_ticks=0, event_type="loop_start", channel=channel)
    events.insert(insert_idx, marker)


@dataclass
class SSEQTrack:
    """Individual musical track within a multi-track SSEQ sequence."""

    track_id: int
    channel: int
    events: List[SSEQEvent] = field(default_factory=list)

    def to_midi_track(self, division: int = 48) -> bytes:
        """Serializes track events into a standard 'MTrk' MIDI chunk."""
        trk_events = bytearray()
        active_notes: List[Tuple[int, int, int]] = []  # (release_tick, note, ch)
        current_tick = 0
        last_event_tick = 0
        ch = max(0, min(15, self.channel))

        for ev in self.events:
            current_tick += ev.delta_ticks

            # Release any active notes whose duration expired before this event
            active_notes.sort(key=lambda x: x[0])
            while active_notes and active_notes[0][0] <= current_tick:
                rel_tick, rel_note, rel_ch = active_notes.pop(0)
                d_time = max(0, rel_tick - last_event_tick)
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0x80 | rel_ch, rel_note, 0x40]))
                last_event_tick = rel_tick

            d_time = max(0, current_tick - last_event_tick)

            if ev.event_type == "note":
                trk_events.extend(write_vlq(d_time))
                # Clamp MIDI velocity (1..127)
                vel = max(1, min(127, ev.velocity))
                trk_events.extend(bytes([0x90 | ch, ev.note & 0x7F, vel]))
                last_event_tick = current_tick
                active_notes.append((current_tick + max(1, ev.duration), ev.note & 0x7F, ch))

            elif ev.event_type == "tempo":
                trk_events.extend(write_vlq(d_time))
                bpm = max(1, ev.value)
                us_per_beat = int(60_000_000 / bpm)
                trk_events.extend(bytes([0xFF, 0x51, 0x03]))
                trk_events.extend(struct.pack(">I", us_per_beat)[1:])  # 3-byte tempo
                last_event_tick = current_tick

            elif ev.event_type == "program_change":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xC0 | ch, ev.value & 0x7F]))
                last_event_tick = current_tick

            elif ev.event_type == "pan":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 10, ev.value & 0x7F]))
                last_event_tick = current_tick

            elif ev.event_type == "volume":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 7, ev.value & 0x7F]))
                last_event_tick = current_tick

            elif ev.event_type == "expression":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 11, ev.value & 0x7F]))
                last_event_tick = current_tick

            elif ev.event_type == "pitch_bend":
                trk_events.extend(write_vlq(d_time))
                # Map signed int8 [-128..127] to 14-bit unsigned MIDI pitch bend
                midi_val = max(0, min(16383, 8192 + ev.value * 64))
                lsb = midi_val & 0x7F
                msb = (midi_val >> 7) & 0x7F
                trk_events.extend(bytes([0xE0 | ch, lsb, msb]))
                last_event_tick = current_tick

            elif ev.event_type == "pitch_bend_range":
                # RPN 0 pitch bend sensitivity
                trk_events.extend(write_vlq(d_time))
                semitones = max(0, min(127, ev.value))
                trk_events.extend(bytes([
                    0xB0 | ch, 101, 0,       # RPN MSB = 0
                    0xB0 | ch, 100, 0,       # RPN LSB = 0 (RPN #0 = pitch bend range)
                    0xB0 | ch, 6, semitones, # Data Entry MSB = semitones
                    0xB0 | ch, 38, 0,        # Data Entry LSB = 0 cents
                ]))
                last_event_tick = current_tick

            elif ev.event_type == "attack":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 73, ev.value & 0x7F]))  # CC73 Attack Time
                last_event_tick = current_tick

            elif ev.event_type == "decay":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 75, ev.value & 0x7F]))  # CC75 Decay Time
                last_event_tick = current_tick

            elif ev.event_type == "sustain":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 70, ev.value & 0x7F]))  # CC70 Sound Variation (sustain level)
                last_event_tick = current_tick

            elif ev.event_type == "release":
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0xB0 | ch, 72, ev.value & 0x7F]))  # CC72 Release Time
                last_event_tick = current_tick

            elif ev.event_type == "loop_start":
                # MIDI Marker meta-event: 0xFF 0x06 <len> <text>
                trk_events.extend(write_vlq(d_time))
                marker = b"LOOPSTART"
                trk_events.extend(bytes([0xFF, 0x06]))
                trk_events.extend(write_vlq(len(marker)))
                trk_events.extend(marker)
                last_event_tick = current_tick

            elif ev.event_type == "loop_end":
                trk_events.extend(write_vlq(d_time))
                marker = b"LOOPEND"
                trk_events.extend(bytes([0xFF, 0x06]))
                trk_events.extend(write_vlq(len(marker)))
                trk_events.extend(marker)
                last_event_tick = current_tick

        # Flush remaining active notes
        active_notes.sort(key=lambda x: x[0])
        while active_notes:
            rel_tick, rel_note, rel_ch = active_notes.pop(0)
            d_time = max(0, rel_tick - last_event_tick)
            trk_events.extend(write_vlq(d_time))
            trk_events.extend(bytes([0x80 | rel_ch, rel_note, 0x40]))
            last_event_tick = rel_tick

        # End of Track meta-event
        trk_events.extend(write_vlq(0))
        trk_events.extend(bytes([0xFF, 0x2F, 0x00]))

        header = bytearray(b"MTrk")
        header.extend(struct.pack(">I", len(trk_events)))
        return bytes(header + trk_events)


class SSEQSequence:
    """
    Nintendo DS SSEQ (Sound Sequence) Parser and Standard MIDI Transpiler.
    Bidirectionally converts between Nintendo DS SSEQ bytecode and Standard MIDI (.mid) files.
    """

    MAGIC = b"SSEQ"

    def __init__(
        self,
        tracks: Optional[List[SSEQTrack]] = None,
        events: Optional[List[SSEQEvent]] = None,
        division: int = 48,
    ) -> None:
        self.division = division
        if tracks is not None:
            self.tracks = tracks
        elif events is not None:
            self.tracks = [SSEQTrack(track_id=0, channel=0, events=events)]
        else:
            self.tracks = []

    @property
    def events(self) -> List[SSEQEvent]:
        """Provides backward-compatibility for single-track access."""
        if self.tracks:
            return self.tracks[0].events
        return []

    @classmethod
    def from_file(cls, path: str) -> "SSEQSequence":
        """Disassembles an SSEQ binary from disk into an SSEQSequence object."""
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    @classmethod
    def from_bytes(cls, data: bytes) -> "SSEQSequence":
        """Disassembles SSEQ binary into an SSEQSequence object with full multi-track support."""
        if len(data) < 32 or data[:4] != cls.MAGIC:
            raise ParseError("Invalid SSEQ binary: missing 'SSEQ' magic.")

        data_magic = data[16:20]
        if data_magic != b"DATA":
            raise ParseError("Invalid SSEQ binary: missing 'DATA' block.")

        base_offset = struct.unpack_from("<I", data, 24)[0]
        seq_start = base_offset if base_offset >= 16 else (16 + base_offset)
        payload = data[seq_start:]
        payload_len = len(payload)

        # Check for multi-track allocation (0xFE opcode)
        if len(payload) > 3 and payload[0] == 0xFE:
            track_mask = struct.unpack_from("<H", payload, 1)[0]
            pos = 3
            track_ptrs: Dict[int, int] = {}

            # Read all 0x93 (OPEN_TRACK) commands
            while pos + 5 <= payload_len and payload[pos] == 0x93:
                trk_num = payload[pos + 1]
                trk_off = payload[pos + 2] | (payload[pos + 3] << 8) | (payload[pos + 4] << 16)
                track_ptrs[trk_num] = trk_off
                pos += 5

            master_start = pos
            tracks: List[SSEQTrack] = []

            # Master track (Track 0)
            master_events = cls._parse_track_bytecode(payload, master_start, channel=0)
            tracks.append(SSEQTrack(track_id=0, channel=0, events=master_events))

            # Sub-tracks
            for trk_num in sorted(track_ptrs.keys()):
                trk_off = track_ptrs[trk_num]
                ch = trk_num % 16
                trk_events = cls._parse_track_bytecode(payload, trk_off, channel=ch)
                tracks.append(SSEQTrack(track_id=trk_num, channel=ch, events=trk_events))

            return cls(tracks=tracks)

        else:
            # Single-track sequence
            events = cls._parse_track_bytecode(payload, 0, channel=0)
            return cls(tracks=[SSEQTrack(track_id=0, channel=0, events=events)])

    @classmethod
    def _parse_track_bytecode(cls, payload: bytes, start_pos: int, channel: int = 0) -> List[SSEQEvent]:
        """Parses an individual track opcode bytecode stream into discrete events."""

        def _make_event(offset: int, **kwargs) -> SSEQEvent:
            """Creates an SSEQEvent and stamps it with its source byte offset for loop injection."""
            ev = SSEQEvent(**kwargs)
            ev._byte_offset = offset  # type: ignore[attr-defined]
            return ev

        events: List[SSEQEvent] = []
        cur_delta = 0
        pos = start_pos
        payload_len = len(payload)

        # Protection against infinite loops
        visited_jumps = set()

        while pos < payload_len:
            event_offset = pos  # byte offset of this opcode relative to payload start
            cmd = payload[pos]
            pos += 1

            if cmd == 0xFF:
                # End of track
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="end", channel=channel))
                break

            elif cmd < 0x80:
                # Note on: cmd = note (0..127)
                note = cmd
                vel = 100
                dur = 48
                if pos < payload_len:
                    vel = payload[pos]
                    pos += 1
                if pos < payload_len:
                    dur, pos = read_vlq(payload, pos)

                events.append(_make_event(
                    event_offset,
                    delta_ticks=cur_delta,
                    event_type="note",
                    channel=channel,
                    note=note,
                    velocity=vel,
                    duration=dur,
                ))
                cur_delta = 0

            elif cmd == 0x80:
                # Wait / Rest
                if pos < payload_len:
                    wait_ticks, pos = read_vlq(payload, pos)
                    cur_delta += wait_ticks

            elif cmd == 0x81:
                # Program change
                prog = payload[pos] if pos < payload_len else 0
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="program_change", channel=channel, value=prog))
                cur_delta = 0

            elif cmd == 0xC0:
                # Pan
                pan = payload[pos] if pos < payload_len else 64
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="pan", channel=channel, value=pan))
                cur_delta = 0

            elif cmd == 0xC1:
                # Volume
                vol = payload[pos] if pos < payload_len else 100
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="volume", channel=channel, value=vol))
                cur_delta = 0

            elif cmd == 0xD5:
                # Expression
                expr = payload[pos] if pos < payload_len else 127
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="expression", channel=channel, value=expr))
                cur_delta = 0

            elif cmd == 0xC4:
                # Pitch bend (signed int8)
                bend = struct.unpack_from("<b", payload, pos)[0] if pos < payload_len else 0
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="pitch_bend", channel=channel, value=bend))
                cur_delta = 0

            elif cmd == 0xE0:
                # Tempo
                if pos + 2 <= payload_len:
                    bpm = struct.unpack_from(">H", payload, pos)[0]
                    pos += 2
                else:
                    bpm = 120
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="tempo", channel=channel, value=bpm))
                cur_delta = 0

            elif cmd == 0xC5:
                # Pitch bend range in semitones (0x00..0x7F)
                pbr = payload[pos] if pos < payload_len else 2
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="pitch_bend_range", channel=channel, value=pbr))
                cur_delta = 0

            elif cmd == 0xD0:
                # ADSR Attack rate
                val = payload[pos] if pos < payload_len else 127
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="attack", channel=channel, value=val))
                cur_delta = 0

            elif cmd == 0xD1:
                # ADSR Decay rate
                val = payload[pos] if pos < payload_len else 127
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="decay", channel=channel, value=val))
                cur_delta = 0

            elif cmd == 0xD2:
                # ADSR Sustain level
                val = payload[pos] if pos < payload_len else 127
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="sustain", channel=channel, value=val))
                cur_delta = 0

            elif cmd == 0xD3:
                # ADSR Release rate
                val = payload[pos] if pos < payload_len else 127
                pos += 1
                events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="release", channel=channel, value=val))
                cur_delta = 0

            elif cmd in (0xC2, 0xC3, 0xC6, 0xC7, 0xC8, 0xC9, 0xCA, 0xCB, 0xCC, 0xCD, 0xCE, 0xCF, 0xD4):
                # 1-byte control commands (skip operand)
                pos += 1

            elif cmd in (0xE1, 0xE3):
                # 2-byte control commands (skip operands)
                pos += 2

            elif cmd == 0x94:
                # Jump (Loop)
                if pos + 3 <= payload_len:
                    target = payload[pos] | (payload[pos + 1] << 8) | (payload[pos + 2] << 16)
                    pos += 3
                    if target in visited_jumps or target <= start_pos:
                        # Handle backward loop
                        events.append(_make_event(event_offset, delta_ticks=cur_delta, event_type="loop_end", channel=channel))
                        _inject_loop_start(events, target, channel)
                        events.append(_make_event(event_offset, delta_ticks=0, event_type="end", channel=channel))
                        break
                    visited_jumps.add(target)
                    pos = target
                else:
                    break

            elif cmd == 0x95:
                # Call subroutine (skip pointer)
                pos += 3

            elif cmd in (0xFC, 0xFD):
                # Loop end / Return
                pass

        return events

    def to_midi(self, division: int = 48) -> bytes:
        """
        Transpiles SSEQ multi-track events into a Standard MIDI (.mid) Format 1 container.
        """
        div = division or self.division or 48
        ntracks = len(self.tracks) if self.tracks else 1
        fmt = 1 if ntracks > 1 else 0

        header = bytearray(b"MThd")
        header.extend(struct.pack(">IHHH", 6, fmt, ntracks, div))

        track_chunks = bytearray()
        if self.tracks:
            for trk in self.tracks:
                track_chunks.extend(trk.to_midi_track(division=div))
        else:
            # Empty track
            dummy = SSEQTrack(track_id=0, channel=0, events=[])
            track_chunks.extend(dummy.to_midi_track(division=div))

        return bytes(header + track_chunks)

    def save_midi(self, output_path: str) -> None:
        """Transpiles SSEQ to MIDI and writes to file on disk."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(self.to_midi())

    def to_file(self, output_path: str) -> None:
        """Serializes SSEQ to binary and writes to file on disk."""
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(self.to_bytes())

    @classmethod
    def from_midi_file(cls, path: str) -> "SSEQSequence":
        """Parses a Standard MIDI (.mid) file from disk and compiles it into an SSEQSequence."""
        with open(path, "rb") as f:
            return cls.from_midi(f.read())

    @classmethod
    def from_midi(cls, midi_bytes: bytes) -> "SSEQSequence":
        """
        Parses a Standard MIDI (Format 0 or 1) binary and compiles it into an SSEQSequence.
        """
        if len(midi_bytes) < 14 or midi_bytes[:4] != b"MThd":
            raise ValueError("Invalid MIDI container: missing 'MThd' header.")

        hdr_len, fmt, ntracks, division = struct.unpack_from(">IHHH", midi_bytes, 4)
        pos = 8 + hdr_len

        tracks: List[SSEQTrack] = []
        for trk_idx in range(ntracks):
            if pos + 8 > len(midi_bytes):
                break
            trk_magic, trk_len = struct.unpack_from(">4sI", midi_bytes, pos)
            pos += 8
            trk_data = midi_bytes[pos : pos + trk_len]
            pos += trk_len

            if trk_magic != b"MTrk":
                continue

            events: List[SSEQEvent] = []
            t_pos = 0
            cur_delta = 0
            last_status = 0

            while t_pos < len(trk_data):
                delta, t_pos = read_vlq(trk_data, t_pos)
                cur_delta += delta

                if t_pos >= len(trk_data):
                    break

                status = trk_data[t_pos]
                if status & 0x80:
                    last_status = status
                    t_pos += 1
                else:
                    status = last_status

                ev_type_high = status & 0xF0
                ch = status & 0x0F

                if ev_type_high == 0x90:
                    # Note On
                    note = trk_data[t_pos]
                    vel = trk_data[t_pos + 1]
                    t_pos += 2
                    if vel > 0:
                        events.append(
                            SSEQEvent(
                                delta_ticks=cur_delta,
                                event_type="note",
                                channel=ch,
                                note=note,
                                velocity=vel,
                                duration=division,
                            )
                        )
                        cur_delta = 0

                elif ev_type_high == 0x80:
                    # Note off
                    t_pos += 2

                elif ev_type_high == 0xC0:
                    # Program Change
                    patch = trk_data[t_pos]
                    t_pos += 1
                    events.append(SSEQEvent(delta_ticks=cur_delta, event_type="program_change", channel=ch, value=patch))
                    cur_delta = 0

                elif ev_type_high == 0xB0:
                    # Control Change
                    ctrl = trk_data[t_pos]
                    val = trk_data[t_pos + 1]
                    t_pos += 2
                    if ctrl == 7:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="volume", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 10:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="pan", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 11:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="expression", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 73:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="attack", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 75:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="decay", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 70:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="sustain", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 72:
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="release", channel=ch, value=val))
                        cur_delta = 0
                    elif ctrl == 6:
                        # CC6 Data Entry MSB for pitch bend range
                        is_rpn0 = False
                        recent = events[-4:] if len(events) >= 4 else events
                        for rev_ev in reversed(recent):
                            if getattr(rev_ev, "_rpn_msb", None) == 0 and getattr(rev_ev, "_rpn_lsb", None) == 0:
                                is_rpn0 = True
                                break
                        if is_rpn0:
                            events.append(SSEQEvent(delta_ticks=cur_delta, event_type="pitch_bend_range", channel=ch, value=val))
                            cur_delta = 0
                    elif ctrl in (100, 101):
                        # RPN LSB/MSB — tag for pitch_bend_range detection on CC6
                        dummy = SSEQEvent(delta_ticks=0, event_type="end", channel=ch)
                        if ctrl == 101:
                            dummy._rpn_msb = val  # type: ignore[attr-defined]
                        else:
                            dummy._rpn_lsb = val  # type: ignore[attr-defined]
                        # Not emitted — just tracked as state; skip

                elif ev_type_high == 0xE0:
                    # Pitch Bend
                    lsb = trk_data[t_pos]
                    msb = trk_data[t_pos + 1]
                    t_pos += 2
                    raw_val = (msb << 7) | lsb
                    bend_signed = int((raw_val - 8192) / 64)
                    events.append(SSEQEvent(delta_ticks=cur_delta, event_type="pitch_bend", channel=ch, value=bend_signed))
                    cur_delta = 0

                elif status == 0xFF:
                    # Meta Event
                    meta_type = trk_data[t_pos]
                    t_pos += 1
                    m_len, t_pos = read_vlq(trk_data, t_pos)
                    m_data = trk_data[t_pos : t_pos + m_len]
                    t_pos += m_len

                    if meta_type == 0x51 and m_len == 3:
                        # Set Tempo
                        us_per_beat = (m_data[0] << 16) | (m_data[1] << 8) | m_data[2]
                        bpm = max(1, int(60_000_000 / us_per_beat)) if us_per_beat > 0 else 120
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="tempo", channel=ch, value=bpm))
                        cur_delta = 0
                    elif meta_type == 0x06:
                        # Marker — detect LOOPSTART / LOOPEND
                        marker_text = m_data.decode("ascii", errors="ignore").upper()
                        if "LOOPSTART" in marker_text:
                            events.append(SSEQEvent(delta_ticks=cur_delta, event_type="loop_start", channel=ch))
                            cur_delta = 0
                        elif "LOOPEND" in marker_text:
                            events.append(SSEQEvent(delta_ticks=cur_delta, event_type="loop_end", channel=ch))
                            cur_delta = 0
                    elif meta_type == 0x2F:
                        # End of Track
                        events.append(SSEQEvent(delta_ticks=cur_delta, event_type="end", channel=ch))
                        break

            tracks.append(SSEQTrack(track_id=trk_idx, channel=trk_idx % 16, events=events))

        return cls(tracks=tracks, division=division)

    def to_bytes(self) -> bytes:
        """Compiles SSEQSequence into compliant Nintendo DS SSEQ binary bytes."""
        if not self.tracks:
            dummy_trk = SSEQTrack(track_id=0, channel=0, events=[SSEQEvent(delta_ticks=0, event_type="end")])
            tracks_to_compile = [dummy_trk]
        else:
            tracks_to_compile = self.tracks

        if len(tracks_to_compile) == 1:
            # Single-track encoding
            payload = self._compile_track_events(tracks_to_compile[0].events)
        else:
            # Multi-track encoding: Master track + subtracks
            master_track = tracks_to_compile[0]
            sub_tracks = tracks_to_compile[1:]

            # Track allocation bitmask (e.g. 1 << 0 | 1 << 1 ...)
            alloc_mask = 1
            for trk in sub_tracks:
                alloc_mask |= (1 << trk.track_id)

            preamble = bytearray()
            preamble.append(0xFE)
            preamble.extend(struct.pack("<H", alloc_mask & 0xFFFF))

            # Placeholder for OPEN_TRACK commands
            # 0x93 <trk_num: uint8> <ptr: uint24>
            open_track_len = len(sub_tracks) * 5
            master_start = len(preamble) + open_track_len

            master_bytes = self._compile_track_events(master_track.events)

            # Compile subtracks
            cur_ptr = master_start + len(master_bytes)
            subtrack_bytes = bytearray()
            open_commands = bytearray()

            for trk in sub_tracks:
                open_commands.append(0x93)
                open_commands.append(trk.track_id & 0xFF)
                # 24-bit pointer little endian
                open_commands.extend(bytes([cur_ptr & 0xFF, (cur_ptr >> 8) & 0xFF, (cur_ptr >> 16) & 0xFF]))

                trk_b = self._compile_track_events(trk.events)
                subtrack_bytes.extend(trk_b)
                cur_ptr += len(trk_b)

            payload = preamble + open_commands + master_bytes + subtrack_bytes

        # Build DATA block
        data_base_offset = 0x001C
        data_block_len = 12 + len(payload)
        pad = (4 - (data_block_len % 4)) % 4
        data_block_len += pad

        data_block = bytearray()
        data_block.extend(b"DATA")
        data_block.extend(struct.pack("<II", data_block_len, data_base_offset))
        data_block.extend(payload)
        data_block.extend(b"\x00" * pad)

        # Build SSEQ Header (16 bytes)
        total_file_len = 16 + len(data_block)
        header = struct.pack(
            "<4sHHIHH",
            self.MAGIC,
            0xFEFF,
            0x0100,
            total_file_len,
            16,
            1,
        )

        return header + bytes(data_block)

    @staticmethod
    def _compile_track_events(events: List[SSEQEvent]) -> bytes:
        """Serializes list of events into SSEQ bytecode."""
        payload = bytearray()
        for ev in events:
            if ev.delta_ticks > 0:
                payload.append(0x80)
                payload.extend(write_vlq(ev.delta_ticks))

            if ev.event_type == "note":
                payload.append(ev.note & 0x7F)
                payload.append(ev.velocity & 0x7F)
                payload.extend(write_vlq(ev.duration))
            elif ev.event_type == "program_change":
                payload.append(0x81)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "pan":
                payload.append(0xC0)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "volume":
                payload.append(0xC1)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "expression":
                payload.append(0xD5)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "pitch_bend":
                payload.append(0xC4)
                payload.extend(struct.pack("<b", max(-128, min(127, ev.value))))
            elif ev.event_type == "tempo":
                payload.append(0xE0)
                payload.extend(struct.pack(">H", ev.value & 0xFFFF))
            elif ev.event_type == "pitch_bend_range":
                payload.append(0xC5)
                payload.append(max(0, min(127, ev.value)))
            elif ev.event_type == "attack":
                payload.append(0xD0)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "decay":
                payload.append(0xD1)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "sustain":
                payload.append(0xD2)
                payload.append(ev.value & 0x7F)
            elif ev.event_type == "release":
                payload.append(0xD3)
                payload.append(ev.value & 0x7F)
            elif ev.event_type in ("loop_start", "loop_end"):
                # Informational loop marker
                pass
            elif ev.event_type == "end":
                payload.append(0xFF)

        if not payload or payload[-1] != 0xFF:
            payload.append(0xFF)

        return bytes(payload)
