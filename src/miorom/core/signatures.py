import re
from typing import List, Optional, Union, Tuple


class SignaturePattern:
    """
    Byte pattern matcher with wildcard support (similar to Ghidra / IDA Pro / YARA).
    Format: Hex bytes separated by spaces, with '??' or '?' representing wildcards.
    Example: '55 8B EC 83 EC ?? 53 ?? ?? FF'
    """

    def __init__(self, pattern_str: str):
        self.pattern_str = pattern_str.strip()
        self.regex = self._compile_pattern(self.pattern_str)
        self.length = len(self.pattern_str.split())

    def _compile_pattern(self, pattern: str) -> re.Pattern:
        tokens = pattern.split()
        regex_parts = []

        for tok in tokens:
            tok = tok.strip()
            if tok in ("??", "?", "**", "*"):
                regex_parts.append(b".")
            elif len(tok) == 2 and "?" in tok:
                # Half-byte wildcard like "4?" or "?A"
                hi, lo = tok[0], tok[1]
                pattern_bytes = []
                for b in range(256):
                    b_hex = f"{b:02X}"
                    hi_match = (hi == "?") or (b_hex[0].upper() == hi.upper())
                    lo_match = (lo == "?") or (b_hex[1].upper() == lo.upper())
                    if hi_match and lo_match:
                        pattern_bytes.append(re.escape(bytes([b])))
                regex_parts.append(b"(?:" + b"|".join(pattern_bytes) + b")")
            else:
                try:
                    val = int(tok, 16)
                    regex_parts.append(re.escape(bytes([val])))
                except ValueError:
                    raise ValueError(f"Invalid byte token in signature pattern: '{tok}'")

        regex_bytes = b"".join(regex_parts)
        return re.compile(regex_bytes, re.DOTALL)

    def find_first(self, data: bytes, start: int = 0, end: Optional[int] = None) -> Optional[int]:
        """Finds the first occurrence of the signature in data. Returns offset or None."""
        if end is None:
            end = len(data)
        match = self.regex.search(data, start, end)
        return match.start() if match else None

    def find_all(self, data: bytes, start: int = 0, end: Optional[int] = None) -> List[int]:
        """Finds all matching offsets of the signature in data."""
        if end is None:
            end = len(data)
        return [m.start() for m in self.regex.finditer(data, start, end)]


class SignatureScanner:
    """Convenience scanner for pattern matching across binary ROMs."""

    @classmethod
    def find(cls, data: bytes, pattern: str, start: int = 0, end: Optional[int] = None) -> Optional[int]:
        return SignaturePattern(pattern).find_first(data, start=start, end=end)

    @classmethod
    def find_all(cls, data: bytes, pattern: str, start: int = 0, end: Optional[int] = None) -> List[int]:
        return SignaturePattern(pattern).find_all(data, start=start, end=end)
