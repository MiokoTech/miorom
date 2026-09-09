"""
miorom.text.tokenizer
~~~~~~~~~~~~~~~~~~~~~
Universal Bidirectional Dialogue Control Code Tokenizer.
Maps proprietary game binary byte tags (newlines, colors, waits, button symbols)
to clean markup tags (e.g. <COLOR:A>, <WAIT>, \n, or raw <XX>) and serializes
them back to raw byte payloads with automatic end-of-string termination.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class ControlCodeDef(MioRomResult):
    """Specification of a binary control code sequence."""
    byte_id: int
    name: str
    arg_bytes: int = 0
    description: str = ""


class ControlCodeSchema:
    """Declarative registry of game-specific control code definitions."""

    def __init__(self, codes: Optional[List[ControlCodeDef]] = None, terminator: bytes = b"\x00"):
        self.codes_by_byte: Dict[int, ControlCodeDef] = {}
        self.codes_by_name: Dict[str, ControlCodeDef] = {}
        self.terminator = terminator

        if codes:
            for c in codes:
                self.register(c)

    def register(self, code_def: ControlCodeDef) -> "ControlCodeSchema":
        self.codes_by_byte[code_def.byte_id] = code_def
        self.codes_by_name[code_def.name.upper()] = code_def
        return self


class ControlCodeTokenizer:
    """
    Universal encoder/decoder between binary dialogue byte buffers and markup text.
    """

    _HEX_TAG_RE = re.compile(r"<([0-9a-fA-F]{2})>")
    _NAMED_TAG_RE = re.compile(r"<([A-Za-z0-9_]+)(?::([0-9a-fA-F]+))?>")

    @classmethod
    def decode(
        cls,
        data: bytes,
        schema: Optional[ControlCodeSchema] = None,
        encoding: str = "ascii",
        strip_terminator: bool = True,
    ) -> str:
        """
        Decodes binary text into human-readable string with control code tags.
        """
        out: List[str] = []
        i = 0
        length = len(data)
        sch = schema or ControlCodeSchema()

        while i < length:
            b = data[i]

            # Check terminator
            if strip_terminator and sch.terminator and data[i : i + len(sch.terminator)] == sch.terminator:
                break

            # Check custom schema
            if b in sch.codes_by_byte:
                cdef = sch.codes_by_byte[b]
                i += 1
                if cdef.arg_bytes > 0:
                    args = data[i : i + cdef.arg_bytes]
                    i += cdef.arg_bytes
                    arg_hex = args.hex().upper()
                    out.append(f"<{cdef.name}:{arg_hex}>")
                else:
                    out.append(f"<{cdef.name}>")
                continue

            # Standard printable ASCII
            if 32 <= b < 127:
                out.append(chr(b))
                i += 1
            else:
                out.append(f"<{b:02X}>")
                i += 1

        return "".join(out)

    @classmethod
    def encode(
        cls,
        text: str,
        schema: Optional[ControlCodeSchema] = None,
        encoding: str = "ascii",
        append_terminator: bool = True,
    ) -> bytes:
        """
        Encodes markup text into binary bytes according to control code schema.
        """
        sch = schema or ControlCodeSchema()
        out = bytearray()
        pos = 0
        length = len(text)

        while pos < length:
            if text[pos] == "<":
                # Check hex tag <XX>
                m_hex = cls._HEX_TAG_RE.match(text, pos)
                if m_hex:
                    byte_val = int(m_hex.group(1), 16)
                    out.append(byte_val)
                    pos = m_hex.end()
                    continue

                # Check named tag <NAME> or <NAME:ARG>
                m_named = cls._NAMED_TAG_RE.match(text, pos)
                if m_named:
                    tag_name = m_named.group(1).upper()
                    arg_str = m_named.group(2)

                    if tag_name in sch.codes_by_name:
                        cdef = sch.codes_by_name[tag_name]
                        out.append(cdef.byte_id)
                        if cdef.arg_bytes > 0 and arg_str:
                            arg_bytes = bytes.fromhex(arg_str)
                            out.extend(arg_bytes)
                        pos = m_named.end()
                        continue

            # Regular character
            out.append(ord(text[pos]) if ord(text[pos]) < 128 else 0x3F)
            pos += 1

        if append_terminator and sch.terminator:
            out.extend(sch.terminator)

        return bytes(out)
