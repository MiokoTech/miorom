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
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from miorom.result import MioRomResult


@dataclass
class ControlCodeDef(MioRomResult):
    """Specification of a binary control code sequence."""
    byte_id: int
    name: str
    arg_bytes: int = 0
    description: str = ""
    arg_endian: str = "<"
    bracket: str = "<>"


class ControlCodeSchema:
    """Declarative registry of game-specific control code definitions."""

    def __init__(self, codes: Optional[List[ControlCodeDef]] = None, terminator: bytes = b"\x00"):
        self.codes_by_byte: Dict[int, ControlCodeDef] = {}
        self.codes_by_name: Dict[str, ControlCodeDef] = {}
        self.terminator = terminator

        if codes:
            for c in codes:
                self.register(c)

    def register(self, code_def: ControlCodeDef) -> ControlCodeSchema:
        self.codes_by_byte[code_def.byte_id] = code_def
        self.codes_by_name[code_def.name.upper()] = code_def
        return self


class ControlCodeTokenizer:
    """
    Universal encoder/decoder between binary dialogue byte buffers and markup text.
    """

    _HEX_TAG_RE = re.compile(r"[<\[]([0-9a-fA-F]{2})[>\]]")
    _NAMED_TAG_RE = re.compile(r"[<\[]([A-Za-z0-9_]+)(?::([^>\]]+))?[>\]]")

    @classmethod
    def _decode_text_chunk(
        cls,
        data: bytes,
        charmap: Optional[Any] = None,
        encoding: str = "ascii",
    ) -> str:
        # Decode non-control byte sequence using charmap or encoding
        if not data:
            return ""
        if charmap is not None:
            return charmap.decode(data)
        if encoding == "ascii":
            out = []
            for b in data:
                out.append(chr(b) if 32 <= b < 127 else f"<{b:02X}>")
            return "".join(out)
        return data.decode(encoding, errors="replace")

    @classmethod
    def _encode_text_chunk(
        cls,
        text: str,
        charmap: Optional[Any] = None,
        encoding: str = "ascii",
    ) -> bytes:
        # Encode string segment using charmap or encoding
        if not text:
            return b""
        if charmap is not None:
            return charmap.encode(text)
        if encoding == "ascii":
            out = bytearray()
            for ch in text:
                code = ord(ch)
                out.append(code if code < 128 else 0x3F)
            return bytes(out)
        return text.encode(encoding, errors="replace")

    @classmethod
    def decode(
        cls,
        data: bytes,
        schema: Optional[ControlCodeSchema] = None,
        encoding: str = "ascii",
        charmap: Optional[Any] = None,
        strip_terminator: bool = True,
    ) -> str:
        """
        Decodes binary text into human-readable string with control code tags.
        """
        out: List[str] = []
        i = 0
        length = len(data)
        sch = schema or ControlCodeSchema()
        text_buf = bytearray()

        while i < length:
            # Check terminator sequence
            if strip_terminator and sch.terminator and data[i : i + len(sch.terminator)] == sch.terminator:
                break

            b = data[i]

            # Check registered control code
            if b in sch.codes_by_byte:
                if text_buf:
                    out.append(cls._decode_text_chunk(bytes(text_buf), charmap, encoding))
                    text_buf.clear()

                cdef = sch.codes_by_byte[b]
                i += 1
                open_b, close_b = ("[", "]") if cdef.bracket == "[]" else ("<", ">")

                if cdef.arg_bytes > 0:
                    args = data[i : i + cdef.arg_bytes]
                    i += cdef.arg_bytes
                    arg_hex = args.hex().upper()
                    out.append(f"{open_b}{cdef.name}:{arg_hex}{close_b}")
                else:
                    out.append(f"{open_b}{cdef.name}{close_b}")
                continue

            text_buf.append(b)
            i += 1

        if text_buf:
            out.append(cls._decode_text_chunk(bytes(text_buf), charmap, encoding))

        return "".join(out)

    @classmethod
    def encode(
        cls,
        text: str,
        schema: Optional[ControlCodeSchema] = None,
        encoding: str = "ascii",
        charmap: Optional[Any] = None,
        append_terminator: bool = True,
    ) -> bytes:
        """
        Encodes markup text into binary bytes according to control code schema.
        """
        sch = schema or ControlCodeSchema()
        out = bytearray()
        pos = 0
        length = len(text)
        text_buf: List[str] = []

        while pos < length:
            ch = text[pos]
            if ch in ("<", "["):
                # Check hex byte tag
                m_hex = cls._HEX_TAG_RE.match(text, pos)
                if m_hex:
                    if text_buf:
                        out.extend(cls._encode_text_chunk("".join(text_buf), charmap, encoding))
                        text_buf.clear()
                    out.append(int(m_hex.group(1), 16))
                    pos = m_hex.end()
                    continue

                # Check named control code tag
                m_named = cls._NAMED_TAG_RE.match(text, pos)
                if m_named:
                    tag_name = m_named.group(1).upper()
                    arg_str = m_named.group(2)

                    if tag_name in sch.codes_by_name:
                        if text_buf:
                            out.extend(cls._encode_text_chunk("".join(text_buf), charmap, encoding))
                            text_buf.clear()

                        cdef = sch.codes_by_name[tag_name]
                        out.append(cdef.byte_id)

                        if cdef.arg_bytes > 0 and arg_str:
                            arg_endian = "little" if cdef.arg_endian == "<" else "big"
                            if arg_str.startswith(("0x", "0X")):
                                val = int(arg_str, 16)
                                out.extend(val.to_bytes(cdef.arg_bytes, arg_endian))
                            elif arg_str.isdigit():
                                val = int(arg_str)
                                out.extend(val.to_bytes(cdef.arg_bytes, arg_endian))
                            else:
                                out.extend(bytes.fromhex(arg_str))

                        pos = m_named.end()
                        continue

            text_buf.append(ch)
            pos += 1

        if text_buf:
            out.extend(cls._encode_text_chunk("".join(text_buf), charmap, encoding))

        if append_terminator and sch.terminator:
            out.extend(sch.terminator)

        return bytes(out)

    @classmethod
    def validate(cls, text: str, schema: Optional[ControlCodeSchema] = None) -> List[str]:
        """
        Validates markup text syntax against control code schema.
        """
        errors: List[str] = []
        sch = schema or ControlCodeSchema()
        pos = 0
        length = len(text)

        while pos < length:
            ch = text[pos]
            if ch in ("<", "["):
                end_ch = ">" if ch == "<" else "]"
                end_pos = text.find(end_ch, pos)
                if end_pos == -1:
                    errors.append(f"Unclosed tag starting at character index {pos}")
                    break

                m_hex = cls._HEX_TAG_RE.match(text, pos)
                m_named = cls._NAMED_TAG_RE.match(text, pos)

                if not m_hex and not m_named:
                    errors.append(f"Malformed tag syntax: {text[pos : end_pos + 1]}")
                elif m_named:
                    name = m_named.group(1).upper()
                    if name not in sch.codes_by_name:
                        errors.append(f"Unknown control code tag: {name}")

                pos = end_pos + 1
                continue
            pos += 1

        return errors
