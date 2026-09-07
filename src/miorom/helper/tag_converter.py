"""
miorom.helper.tag_converter
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Helper for converting between binary control codes / hex tags and human-readable tags.
Handles multi-byte game control sequences and generic [0xXXXX] hex escapes.
"""

import struct
from typing import Dict, List, Optional, Union


class TagConverter:
    """
    Two-way converter for game control codes, markup tags, and [0xXXXX] hex escapes.

    Example:
        tc = TagConverter({
            "<WARNA>": "[0xff20]",
            "<PLAYER>": "[0x30e9][0x30b0][0x30ca]",
            "<ENTER>": "\\n",
        })

        clean = tc.apply("Hello [0x30e9][0x30b0][0x30ca]!\\nHow are you?")
        # -> "Hello <PLAYER>!<ENTER>How are you?"

        raw_bytes = tc.encode_utf16(clean)
    """

    def __init__(self, tag_map: Optional[Dict[str, str]] = None):
        # tag_map: {human_tag: raw_representation}
        # e.g. {"<WARNA>": "[0xff20]", "<ENTER>": "\n"}
        self.tag_to_raw: Dict[str, str] = dict(tag_map) if tag_map else {}
        self.raw_to_tag: Dict[str, str] = {v: k for k, v in self.tag_to_raw.items()}

    def add_tag(self, human_tag: str, raw_code: str) -> "TagConverter":
        """Register a new tag mapping."""
        self.tag_to_raw[human_tag] = raw_code
        self.raw_to_tag[raw_code] = human_tag
        return self

    def apply(self, text: str) -> str:
        """Convert raw strings / codes into clean human-readable tags."""
        out = text
        for raw, tag in self.raw_to_tag.items():
            out = out.replace(raw, tag)
        return out

    def revert(self, text: str) -> str:
        """Convert human-readable tags back into raw codes."""
        out = text
        for tag, raw in self.tag_to_raw.items():
            out = out.replace(tag, raw)
        return out

    def decode_utf16(
        self,
        data: bytes,
        endian: str = ">",
        escape_non_ascii: bool = True,
        stop_on_null: bool = True,
        max_length: Optional[int] = None,
        strip: bool = False,
        replace_newlines: Optional[str] = None,
    ) -> str:
        """
        Decode UTF-16 bytes into human-readable text, converting unprintable/control
        characters to [0xXXXX] escapes, and then applying defined tag mappings.

        Keyword Args:
            endian: Byte order ('>' for big-endian, '<' for little-endian).
            escape_non_ascii: Convert non-ASCII code units to [0xXXXX].
            stop_on_null: Halt decoding at first 0x0000 null terminator (default: True).
            max_length: Maximum number of 16-bit code units to decode.
            strip: Strip leading and trailing whitespace from decoded string.
            replace_newlines: Replace '\\n' with a custom tag or token (e.g. '<BR>').
        """
        chars: List[str] = []
        p = 0
        limit = len(data) - (len(data) % 2)
        fmt = f"{endian}H"

        while p < limit:
            if max_length is not None and len(chars) >= max_length:
                break
            val = struct.unpack_from(fmt, data, p)[0]
            if val == 0:
                if stop_on_null:
                    break
                else:
                    chars.append("[0x0000]")
                    p += 2
                    continue
            if 0x20 <= val <= 0x7E:
                chars.append(chr(val))
            elif val == 0x0A:
                chars.append("\n")
            elif escape_non_ascii:
                chars.append(f"[0x{val:x}]")
            else:
                chars.append(chr(val))
            p += 2

        raw_str = "".join(chars)
        if replace_newlines is not None:
            raw_str = raw_str.replace("\n", replace_newlines)

        applied = self.apply(raw_str)
        return applied.strip() if strip else applied

    def encode_utf16(
        self,
        text: str,
        endian: str = ">",
        null_terminate: bool = True,
        pad_to: Optional[int] = None,
        pad_byte: bytes = b"\x00",
        max_bytes: Optional[int] = None,
    ) -> bytes:
        """
        Revert tags in text, parse any [0xXXXX] hex escapes into 16-bit integers,
        and encode to UTF-16 bytes.

        Keyword Args:
            endian: Byte order ('>' for big-endian, '<' for little-endian).
            null_terminate: Append 0x0000 null terminator (default: True).
            pad_to: Pad output bytes to the specified total length.
            pad_byte: Byte used for padding when pad_to is set (default: b"\\x00").
            max_bytes: Truncate output bytes if exceeding max_bytes.
        """
        reverted = self.revert(text)
        out = bytearray()
        fmt = f"{endian}H"

        i = 0
        n = len(reverted)
        while i < n:
            if reverted[i] == '[' and reverted.startswith("[0x", i):
                end_tag = reverted.find(']', i)
                if end_tag != -1:
                    try:
                        val = int(reverted[i + 3:end_tag], 16)
                        out.extend(struct.pack(fmt, val))
                        i = end_tag + 1
                        continue
                    except ValueError:
                        pass
            out.extend(struct.pack(fmt, ord(reverted[i])))
            i += 1

        if null_terminate:
            out.extend(b"\x00\x00")

        if pad_to is not None and len(out) < pad_to:
            out.extend(pad_byte * (pad_to - len(out)))

        if max_bytes is not None and len(out) > max_bytes:
            out = out[:max_bytes]

        return bytes(out)
