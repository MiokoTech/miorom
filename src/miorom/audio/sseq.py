from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


from miorom.errors import ParseError
def read_vlq(data: bytes, pos: int) -> Tuple[int, int]:
    """Read a Variable-Length Quantity (VLQ) from data at pos. Returns (value, new_pos)."""
    val = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return val, pos


def write_vlq(val: int) -> bytes:
    """Encode an integer as a Variable-Length Quantity (VLQ)."""
    buf = bytearray([val & 0x7F])
    val >>= 7
    while val > 0:
        buf.append((val & 0x7F) | 0x80)
        val >>= 7
    return bytes(reversed(buf))


@dataclass
class SSEQEvent(MioRomResult):
    """Represents a discrete musical or control event in an SSEQ track."""
    delta_ticks: int
    event_type: str  # "note", "rest", "tempo", "program_change", "pan", "volume", "pitch_bend", "end"
    channel: int = 0
    note: int = 60
    velocity: int = 100
    duration: int = 48
    value: int = 0


class SSEQSequence:
    """
    Nintendo DS SSEQ (Sound Sequence) Parser and Compiler.
    Bidirectionally converts between Nintendo DS SSEQ bytecode and Standard MIDI (.mid) files.
    """

    MAGIC = b"SSEQ"

    def __init__(self, events: Optional[List[SSEQEvent]] = None):
        self.events: List[SSEQEvent] = events or []

    @classmethod
    def from_bytes(cls, data: bytes) -> "SSEQSequence":
        """Disassemble SSEQ binary into an SSEQSequence object."""
        if len(data) < 32 or data[:4] != b"SSEQ":
            raise ParseError("Invalid SSEQ binary: missing 'SSEQ' magic.")

        data_magic = data[16:20]
        if data_magic != b"DATA":
            raise ParseError("Invalid SSEQ binary: missing 'DATA' block.")

        base_offset = struct.unpack_from("<I", data, 24)[0]
        seq_start = base_offset if base_offset >= 16 else (16 + base_offset)
        pos = seq_start
        end_pos = len(data)

        events: List[SSEQEvent] = []
        cur_channel = 0
        cur_delta = 0

        while pos < end_pos:
            cmd = data[pos]
            pos += 1

            if cmd == 0xFF:
                # End of sequence
                events.append(SSEQEvent(delta_ticks=cur_delta, event_type="end", channel=cur_channel))
                break

            elif cmd < 0x80:
                # Note command: cmd = note (0..127)
                note = cmd
                vel = 100
                dur = 48
                if pos < end_pos:
                    vel = data[pos]
                    pos += 1
                if pos < end_pos:
                    dur, pos = read_vlq(data, pos)

                events.append(
                    SSEQEvent(
                        delta_ticks=cur_delta,
                        event_type="note",
                        channel=cur_channel,
                        note=note,
                        velocity=vel,
                        duration=dur,
                    )
                )
                cur_delta = 0

            elif cmd == 0x80:
                # Rest / Wait
                wait_ticks, pos = read_vlq(data, pos)
                cur_delta += wait_ticks

            elif cmd == 0x81:
                # Program change
                prog = data[pos] if pos < end_pos else 0
                pos += 1
                events.append(
                    SSEQEvent(
                        delta_ticks=cur_delta,
                        event_type="program_change",
                        channel=cur_channel,
                        value=prog,
                    )
                )
                cur_delta = 0

            elif cmd == 0xC0:
                # Pan
                pan = data[pos] if pos < end_pos else 64
                pos += 1
                events.append(
                    SSEQEvent(
                        delta_ticks=cur_delta,
                        event_type="pan",
                        channel=cur_channel,
                        value=pan,
                    )
                )
                cur_delta = 0

            elif cmd == 0xC1:
                # Volume
                vol = data[pos] if pos < end_pos else 100
                pos += 1
                events.append(
                    SSEQEvent(
                        delta_ticks=cur_delta,
                        event_type="volume",
                        channel=cur_channel,
                        value=vol,
                    )
                )
                cur_delta = 0

            elif cmd == 0xE0:
                # Tempo
                if pos + 2 <= end_pos:
                    bpm = struct.unpack_from(">H", data, pos)[0]
                    pos += 2
                else:
                    bpm = 120
                events.append(
                    SSEQEvent(
                        delta_ticks=cur_delta,
                        event_type="tempo",
                        channel=cur_channel,
                        value=bpm,
                    )
                )
                cur_delta = 0

        return cls(events=events)

    def to_bytes(self) -> bytes:
        """Compile SSEQSequence into compliant Nintendo DS SSEQ binary bytes."""
        payload = bytearray()

        for ev in self.events:
            # Emit wait ticks before event if any
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

            elif ev.event_type == "tempo":
                payload.append(0xE0)
                payload.extend(struct.pack(">H", ev.value & 0xFFFF))

            elif ev.event_type == "end":
                payload.append(0xFF)

        if not payload or payload[-1] != 0xFF:
            payload.append(0xFF)

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

        # Build SSEQ File Header (16 bytes)
        total_file_len = 16 + len(data_block)
        header = struct.pack(
            "<4sHHIHH",
            self.MAGIC,
            0xFEFF,  # Endian BOM
            0x0100,  # Version 1.0
            total_file_len,
            16,      # Header size
            1,       # Block count
        )

        return header + bytes(data_block)

    def to_midi(self, division: int = 96) -> bytes:
        """
        Convert SSEQ events into a standard MIDI format 0 file (.mid).
        """
        trk_events = bytearray()

        active_notes: List[Tuple[int, int, int]] = []  # (release_tick, note, ch)
        current_tick = 0
        last_event_tick = 0

        for ev in self.events:
            current_tick += ev.delta_ticks

            # Check if any active notes should end before this event
            while active_notes and active_notes[0][0] <= current_tick:
                rel_tick, rel_note, rel_ch = active_notes.pop(0)
                d_time = rel_tick - last_event_tick
                trk_events.extend(write_vlq(d_time))
                trk_events.extend(bytes([0x80 | (rel_ch & 0x0F), rel_note & 0x7F, 0]))
                last_event_tick = rel_tick

            delta = current_tick - last_event_tick
            last_event_tick = current_tick

            if ev.event_type == "note":
                trk_events.extend(write_vlq(delta))
                trk_events.extend(bytes([0x90 | (ev.channel & 0x0F), ev.note & 0x7F, ev.velocity & 0x7F]))
                # Register note off
                release_tick = current_tick + ev.duration
                active_notes.append((release_tick, ev.note, ev.channel))
                active_notes.sort(key=lambda x: x[0])

            elif ev.event_type == "program_change":
                trk_events.extend(write_vlq(delta))
                trk_events.extend(bytes([0xC0 | (ev.channel & 0x0F), ev.value & 0x7F]))

            elif ev.event_type == "tempo":
                trk_events.extend(write_vlq(delta))
                # Tempo in microseconds per quarter note = 60,000,000 / BPM
                bpm = max(1, ev.value)
                mpqn = int(60_000_000 / bpm)
                trk_events.extend(b"\xFF\x51\x03")
                trk_events.extend(struct.pack(">I", mpqn)[1:])  # 3 bytes

        # Flush remaining active notes
        while active_notes:
            rel_tick, rel_note, rel_ch = active_notes.pop(0)
            d_time = max(0, rel_tick - last_event_tick)
            trk_events.extend(write_vlq(d_time))
            trk_events.extend(bytes([0x80 | (rel_ch & 0x0F), rel_note & 0x7F, 0]))
            last_event_tick = rel_tick

        # End of track event
        trk_events.extend(write_vlq(0))
        trk_events.extend(b"\xFF\x2F\x00")

        # Build MThd header
        mthd = struct.pack(">4sIHHH", b"MThd", 6, 0, 1, division)
        # Build MTrk chunk
        mtrk = struct.pack(">4sI", b"MTrk", len(trk_events)) + bytes(trk_events)

        return mthd + mtrk

    @classmethod
    def from_midi(cls, midi_bytes: bytes) -> "SSEQSequence":
        """
        Parse Standard MIDI file bytes and compile into an SSEQSequence.
        """
        if len(midi_bytes) < 14 or midi_bytes[:4] != b"MThd":
            raise ParseError("Invalid MIDI file: missing 'MThd' header.")

        fmt, num_tracks, division = struct.unpack_from(">HHH", midi_bytes, 8)
        pos = 14
        events: List[SSEQEvent] = []

        while pos + 8 <= len(midi_bytes):
            chunk_id = midi_bytes[pos:pos + 4]
            chunk_len = struct.unpack_from(">I", midi_bytes, pos + 4)[0]
            pos += 8

            if chunk_id == b"MTrk":
                trk_data = midi_bytes[pos:pos + chunk_len]
                t_pos = 0
                running_status = 0

                while t_pos < len(trk_data):
                    delta, t_pos = read_vlq(trk_data, t_pos)
                    if t_pos >= len(trk_data):
                        break

                    status = trk_data[t_pos]
                    if status & 0x80:
                        t_pos += 1
                        running_status = status
                    else:
                        status = running_status

                    msg_type = status & 0xF0
                    channel = status & 0x0F

                    if msg_type == 0x90:  # Note On
                        note = trk_data[t_pos]
                        vel = trk_data[t_pos + 1]
                        t_pos += 2
                        if vel > 0:
                            events.append(
                                SSEQEvent(
                                    delta_ticks=delta,
                                    event_type="note",
                                    channel=channel,
                                    note=note,
                                    velocity=vel,
                                    duration=48,
                                )
                            )
                    elif msg_type == 0x80:  # Note Off
                        t_pos += 2
                    elif msg_type == 0xC0:  # Program Change
                        prog = trk_data[t_pos]
                        t_pos += 1
                        events.append(
                            SSEQEvent(
                                delta_ticks=delta,
                                event_type="program_change",
                                channel=channel,
                                value=prog,
                            )
                        )
                    elif status == 0xFF:  # Meta event
                        meta_type = trk_data[t_pos]
                        t_pos += 1
                        meta_len, t_pos = read_vlq(trk_data, t_pos)
                        meta_val = trk_data[t_pos:t_pos + meta_len]
                        t_pos += meta_len

                        if meta_type == 0x51 and meta_len == 3:
                            # Tempo
                            mpqn = (meta_val[0] << 16) | (meta_val[1] << 8) | meta_val[2]
                            bpm = int(60_000_000 / mpqn) if mpqn > 0 else 120
                            events.append(
                                SSEQEvent(
                                    delta_ticks=delta,
                                    event_type="tempo",
                                    value=bpm,
                                )
                            )
                        elif meta_type == 0x2F:
                            # End of track
                            events.append(SSEQEvent(delta_ticks=delta, event_type="end"))
                    else:
                        # Other channel messages (pitch bend, controller, etc.)
                        t_pos += 2

            pos += chunk_len

        return cls(events=events)
