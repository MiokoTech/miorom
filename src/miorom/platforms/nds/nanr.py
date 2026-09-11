"""
miorom.platforms.nds.nanr
~~~~~~~~~~~~~~~~~~~~~~~~~
Nitro Animation Resource (NANR) Parser, Builder, and Sequence Engine.
Standard 2D sprite keyframe and animation sequence container for Nintendo DS games.
Pure Python, using MioROM declarative binary primitives.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, Padding, RawBytes, U16, U32
from miorom.errors import ParseError


class NANRHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"RNAN"
    byte_order = U16()   # 0xFEFF
    version = U16()      # 0x0100
    file_size = U32()
    header_size = U16()  # 0x0010
    section_count = U16()  # 1


class ABNKSectionStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"KNBA"
    size = U32()
    sequence_count = U16()
    frame_count = U16()
    seq_data_offset = U32()
    frame_data_offset = U32()


class NANRSequenceStruct(BinaryStruct):
    _endian = "<"
    frame_count = U16()
    play_mode = U16()
    frame_type = U16()
    _reserved = Padding(2)
    frame_start_index = U32()
    _pad = Padding(4)  # total 16 bytes


class NANRFrameStruct(BinaryStruct):
    _endian = "<"
    cell_index = U16()
    delay = U16()


@dataclass
class NANRFrame:
    """A single frame in a sprite animation sequence."""
    cell_index: int
    delay: int  # in frames (1/60s)


@dataclass
class NANRSequence:
    """An animation sequence consisting of ordered frames."""
    frames: List[NANRFrame] = field(default_factory=list)
    play_mode: int = 0  # 0=Forward, 1=Forward Loop, 2=Reverse Loop, etc.
    frame_type: int = 0
    name: str = ""

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def total_duration(self) -> int:
        return sum(f.delay for f in self.frames)

    def get_frame_at_tick(self, tick: int) -> Optional[NANRFrame]:
        if not self.frames:
            return None
        dur = self.total_duration
        if dur == 0:
            return self.frames[0]
        # Loop mode
        effective_tick = tick % dur
        accum = 0
        for f in self.frames:
            accum += f.delay
            if effective_tick < accum:
                return f
        return self.frames[-1]


class NANRFile:
    """
    Parser and Builder for Nintendo Nitro NANR animation containers.
    """

    MAGIC = b"RNAN"
    SECTION_MAGIC = b"KNBA"

    def __init__(self, sequences: Optional[List[NANRSequence]] = None):
        self.sequences: List[NANRSequence] = sequences or []

    @property
    def sequence_count(self) -> int:
        return len(self.sequences)

    @property
    def total_frames(self) -> int:
        return sum(s.frame_count for s in self.sequences)

    @classmethod
    def from_bytes(cls, data: bytes) -> "NANRFile":
        if len(data) < NANRHeaderStruct.sizeof():
            raise ParseError("Data too small for NANR header.")

        header = NANRHeaderStruct.from_bytes(data, offset=0)
        if header.magic not in (cls.MAGIC, b"NANR"):
            raise ParseError(f"Invalid NANR magic: {header.magic!r}")

        offset = header.header_size
        abnk = ABNKSectionStruct.from_bytes(data, offset=offset)
        if abnk.magic not in (cls.SECTION_MAGIC, b"ABNK"):
            raise ParseError(f"Invalid ABNK section magic: {abnk.magic!r}")

        reader = BinaryReader(data, endian="<")
        seq_base = offset + 8 + abnk.seq_data_offset
        frame_base = offset + 8 + abnk.frame_data_offset

        sequences: List[NANRSequence] = []
        for i in range(abnk.sequence_count):
            s_offset = seq_base + i * NANRSequenceStruct.sizeof()
            if s_offset + NANRSequenceStruct.sizeof() > len(data):
                break

            seq_rec = NANRSequenceStruct.from_bytes(data, offset=s_offset)
            frames: List[NANRFrame] = []
            f_offset = frame_base + seq_rec.frame_start_index * NANRFrameStruct.sizeof()

            for j in range(seq_rec.frame_count):
                cur_f_offset = f_offset + j * NANRFrameStruct.sizeof()
                if cur_f_offset + NANRFrameStruct.sizeof() <= len(data):
                    frame_rec = NANRFrameStruct.from_bytes(data, offset=cur_f_offset)
                    frames.append(NANRFrame(cell_index=frame_rec.cell_index, delay=frame_rec.delay))

            seq = NANRSequence(
                frames=frames,
                play_mode=seq_rec.play_mode,
                frame_type=seq_rec.frame_type,
            )
            sequences.append(seq)

        return cls(sequences=sequences)

    def to_bytes(self) -> bytes:
        """Serializes NANRFile back into Nitro Animation Resource binary format."""
        seq_count = len(self.sequences)
        total_frames = sum(s.frame_count for s in self.sequences)

        seq_data_offset = 0x18
        seq_table_size = seq_count * NANRSequenceStruct.sizeof()
        frame_data_offset = seq_data_offset + seq_table_size

        seq_writer = BinaryWriter(endian="<")
        frame_writer = BinaryWriter(endian="<")

        frame_idx_counter = 0
        for seq in self.sequences:
            seq_writer.write_bytes(
                NANRSequenceStruct(
                    frame_count=seq.frame_count,
                    play_mode=seq.play_mode,
                    frame_type=seq.frame_type,
                    frame_start_index=frame_idx_counter,
                ).to_bytes()
            )
            for f in seq.frames:
                frame_writer.write_bytes(
                    NANRFrameStruct(cell_index=f.cell_index, delay=f.delay).to_bytes()
                )
            frame_idx_counter += seq.frame_count

        abnk_body = BinaryWriter(endian="<")
        # ABNK header layout (seq_data_offset at 0x18 relative to body)
        abnk_body.write_u16(seq_count)
        abnk_body.write_u16(total_frames)
        abnk_body.write_u32(seq_data_offset)
        abnk_body.write_u32(frame_data_offset)
        abnk_body.pad(12)  # Pad to 0x18 (24 bytes)

        abnk_body.write_bytes(seq_writer.to_bytes())
        abnk_body.write_bytes(frame_writer.to_bytes())
        abnk_body.align(4)

        abnk_payload = abnk_body.to_bytes()
        abnk_size = 8 + len(abnk_payload)
        header_size = 0x10
        file_size = header_size + abnk_size

        out = BinaryWriter(endian="<")
        out.write_bytes(
            NANRHeaderStruct(
                magic=self.MAGIC,
                byte_order=0xFEFF,
                version=0x0100,
                file_size=file_size,
                header_size=header_size,
                section_count=1,
            ).to_bytes()
        )

        out.write_bytes(self.SECTION_MAGIC)
        out.write_u32(abnk_size)
        out.write_bytes(abnk_payload)

        return out.to_bytes()
