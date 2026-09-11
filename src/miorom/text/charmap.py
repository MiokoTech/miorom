from typing import Dict, Tuple, Optional
import os


class CharMap:
    """
    Handles custom ROM character encodings (.tbl format used by Thingy / WindHex / ABCDE).
    Supports 1-byte, 2-byte, and multi-byte character tables.
    """

    def __init__(self, mappings: Optional[Dict[bytes, str]] = None):
        self.byte_to_char: Dict[bytes, str] = {}
        self.char_to_byte: Dict[str, bytes] = {}
        self.max_byte_len = 1
        self.max_char_len = 1
        if mappings:
            for b, c in mappings.items():
                self.add_mapping(b, c)

    @classmethod
    def from_file(cls, filepath: str, encoding: str = "utf-8") -> "CharMap":
        """Alias for from_tbl_file."""
        return cls.from_tbl_file(filepath, encoding)

    @classmethod
    def from_tbl_file(cls, filepath: str, encoding: str = "utf-8") -> "CharMap":
        """Load a standard .tbl file (format: HEX=CHAR)."""
        cm = cls()
        with open(filepath, "r", encoding=encoding, errors="replace") as f:
            for line in f:
                line = line.rstrip("\r\n")
                if not line or line.startswith("#") or line.startswith("//"):
                    continue
                if "=" in line:
                    hex_part, char_part = line.split("=", 1)
                    hex_part = hex_part.strip()
                    try:
                        b = bytes.fromhex(hex_part)
                        cm.add_mapping(b, char_part)
                    except ValueError:
                        continue
        return cm

    def add_mapping(self, b: bytes, char: str) -> "CharMap":
        self.byte_to_char[b] = char
        self.char_to_byte[char] = b
        self.max_byte_len = max(self.max_byte_len, len(b))
        self.max_char_len = max(self.max_char_len, len(char))
        return self

    def decode(self, data: bytes, end_bytes: Optional[bytes] = None) -> str:
        """Decode a byte buffer into a string using the character table."""
        if not isinstance(data, bytes):
            data = bytes(data)
        chars = []
        i = 0
        data_len = len(data)

        while i < data_len:
            if end_bytes and data.startswith(end_bytes, i):
                break

            matched = False
            # Try longest byte match first
            for length in range(min(self.max_byte_len, data_len - i), 0, -1):
                chunk = data[i:i+length]
                if chunk in self.byte_to_char:
                    chars.append(self.byte_to_char[chunk])
                    i += length
                    matched = True
                    break

            if not matched:
                # Fallback to hex representation for unknown bytes
                chars.append(f"[{data[i]:02x}]")
                i += 1

        return "".join(chars)

    def encode(self, text: str, strict: bool = False) -> bytes:
        """Encode a string into bytes using the character table.

        Args:
            text: The text string to encode.
            strict: If True, raises ValueError on any unmapped character instead of
                falling back to single-byte truncation.
        """
        out = bytearray()
        i = 0
        text_len = len(text)

        while i < text_len:
            # Check for hex tag [XX] or [XXXX]
            if text[i] == "[":
                closing = text.find("]", i)
                if closing != -1:
                    hex_str = text[i+1:closing]
                    try:
                        raw = bytes.fromhex(hex_str)
                        out.extend(raw)
                        i = closing + 1
                        continue
                    except ValueError:
                        pass

            matched = False
            for length in range(min(self.max_char_len, text_len - i), 0, -1):
                chunk = text[i:i+length]
                if chunk in self.char_to_byte:
                    out.extend(self.char_to_byte[chunk])
                    i += length
                    matched = True
                    break

            if not matched:
                if strict:
                    raise ValueError(f"Unmapped character {text[i]!r} (U+{ord(text[i]):04X}) at index {i}")
                # Fallback to ascii/utf-8 single byte if possible
                out.append(ord(text[i]) & 0xFF)
                i += 1

        return bytes(out)
