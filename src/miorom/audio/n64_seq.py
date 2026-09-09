"""
miorom.audio.n64_seq
~~~~~~~~~~~~~~~~~~~~
Nintendo 64 Audiobank (Audiotable/Audiobank) and M64 Sequence Parser.
Parses N64 Compact MIDI sequences (.m64) and audio sample bank structures.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from miorom.result import MioRomResult


@dataclass
class M64Command(MioRomResult):
    pc: int
    cmd_byte: int
    data: bytes
    name: str


class M64Sequence:
    """
    Parser and builder for Nintendo 64 sequence files (.m64 / Audioseq).
    """

    def __init__(self, commands: Optional[List[M64Command]] = None, raw_data: Optional[bytes] = None):
        self.commands = commands or []
        self.raw_data = raw_data or b""

    @classmethod
    def from_bytes(cls, data: bytes) -> "M64Sequence":
        cmds: List[M64Command] = []
        i = 0
        length = len(data)

        cmd_names = {
            0xFF: "END",
            0xFE: "DELAY_1",
            0xFD: "DELAY_VAR",
            0xFC: "CALL",
            0xFB: "JUMP",
            0xFA: "LOOP_START",
            0xF9: "LOOP_END",
            0xD3: "PITCH_BEND",
            0xD4: "EFFECT",
            0xDD: "PAN",
            0xDF: "VOLUME",
            0xE0: "INSTRUMENT",
        }

        while i < length:
            b = data[i]
            pc = i
            name = cmd_names.get(b, f"CMD_{b:02X}")
            arg_len = 0

            if b in (0xFC, 0xFB): # Call / Jump (2-byte target)
                arg_len = 2
            elif b in (0xD3, 0xD4, 0xDD, 0xDF, 0xE0):
                arg_len = 1
            elif b == 0xFD:
                arg_len = 1

            payload = data[i + 1 : min(length, i + 1 + arg_len)]
            cmds.append(M64Command(pc=pc, cmd_byte=b, data=payload, name=name))
            i += 1 + arg_len

            if b == 0xFF: # End of sequence
                break

        return cls(commands=cmds, raw_data=data)

    def to_bytes(self) -> bytes:
        if self.raw_data:
            return self.raw_data
        out = bytearray()
        for cmd in self.commands:
            out.append(cmd.cmd_byte)
            out.extend(cmd.data)
        return bytes(out)


class N64Audiobank:
    """
    Parser for N64 Audiobank instrument metadata (Audiotable / Audiobank).
    """

    def __init__(self, raw_bytes: bytes):
        self.raw_bytes = raw_bytes

    @classmethod
    def from_bytes(cls, data: bytes) -> "N64Audiobank":
        return cls(data)

    @property
    def sample_count(self) -> int:
        if len(self.raw_bytes) < 4:
            return 0
        return struct.unpack(">H", self.raw_bytes[:2])[0]
