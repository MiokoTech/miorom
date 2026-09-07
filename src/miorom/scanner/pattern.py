"""
miorom.scanner.pattern
~~~~~~~~~~~~~~~~~~~~~~
Universal Array-of-Bytes (AOB) pattern scanner and signature engine.
Supports IDA Pro, Cheat Engine, and Ghidra signature patterns with wildcards ('??' or '?').
Provides fast multi-byte search, sliding-window chunked file scanning, and
wildcard-preserving binary patching.
"""

import os
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union


@dataclass
class PatternMatch:
    """Represents a matched signature pattern in binary data."""
    offset: int
    address: int
    size: int
    data: bytes

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    @property
    def address_hex(self) -> str:
        return f"0x{self.address:08X}"

    def __repr__(self) -> str:
        return f"<PatternMatch offset=0x{self.offset:06X} addr=0x{self.address:08X} size={self.size}>"


class CompiledPattern:
    """
    Compiled AOB pattern using Python's optimized regex engine.
    """

    def __init__(self, raw_pattern: str):
        self.raw_pattern = raw_pattern.strip()
        self.pattern_bytes, self.mask, self.regex = self._compile(self.raw_pattern)
        self.size = len(self.pattern_bytes)

    @classmethod
    def _compile(cls, pattern_str: str) -> Tuple[bytes, bytes, re.Pattern]:
        tokens = pattern_str.split()
        if not tokens:
            raise ValueError("Pattern string cannot be empty.")

        regex_parts: List[bytes] = []
        pattern_bytes_list: List[int] = []
        mask_bytes_list: List[int] = []

        for token in tokens:
            if token in ("??", "?"):
                regex_parts.append(b".")
                pattern_bytes_list.append(0)
                mask_bytes_list.append(0)
            else:
                val = int(token, 16)
                if not (0 <= val <= 0xFF):
                    raise ValueError(f"Invalid byte literal in pattern: '{token}'")
                regex_parts.append(re.escape(bytes([val])))
                pattern_bytes_list.append(val)
                mask_bytes_list.append(0xFF)

        pattern_bytes = bytes(pattern_bytes_list)
        mask = bytes(mask_bytes_list)
        compiled_re = re.compile(b"".join(regex_parts), re.DOTALL)
        return pattern_bytes, mask, compiled_re


class AOBPatternScanner:
    """
    High-performance pattern scanner for IDA-style byte signatures with wildcards.
    """

    @staticmethod
    def compile(pattern: Union[str, CompiledPattern]) -> CompiledPattern:
        if isinstance(pattern, CompiledPattern):
            return pattern
        return CompiledPattern(pattern)

    @classmethod
    def find_first(
        cls,
        buffer: Union[bytes, bytearray, memoryview],
        pattern: Union[str, CompiledPattern],
        start: int = 0,
        base_address: int = 0,
    ) -> Optional[PatternMatch]:
        """
        Finds the first occurrence of pattern in buffer starting at start offset.
        """
        compiled = cls.compile(pattern)
        buf_bytes = bytes(buffer) if not isinstance(buffer, (bytes, bytearray, memoryview)) else buffer
        m = compiled.regex.search(buf_bytes, start)
        if m is None:
            return None
        match_start = m.start()
        matched_data = bytes(m.group(0))
        return PatternMatch(
            offset=match_start,
            address=base_address + match_start,
            size=len(matched_data),
            data=matched_data,
        )

    @classmethod
    def find_all(
        cls,
        buffer: Union[bytes, bytearray, memoryview],
        pattern: Union[str, CompiledPattern],
        start: int = 0,
        base_address: int = 0,
        max_matches: Optional[int] = None,
    ) -> List[PatternMatch]:
        """
        Finds all occurrences of pattern in buffer.
        """
        compiled = cls.compile(pattern)
        buf_bytes = bytes(buffer) if not isinstance(buffer, (bytes, bytearray, memoryview)) else buffer
        matches: List[PatternMatch] = []

        pos = start
        while pos < len(buf_bytes):
            m = compiled.regex.search(buf_bytes, pos)
            if m is None:
                break
            match_start = m.start()
            matched_data = bytes(m.group(0))
            matches.append(PatternMatch(
                offset=match_start,
                address=base_address + match_start,
                size=len(matched_data),
                data=matched_data,
            ))
            if max_matches is not None and len(matches) >= max_matches:
                break
            pos = match_start + 1

        return matches

    @classmethod
    def scan_file(
        cls,
        filepath: str,
        pattern: Union[str, CompiledPattern],
        base_address: int = 0,
        chunk_size: int = 65536,
    ) -> List[PatternMatch]:
        """
        Scans a large file on disk in chunks, properly detecting patterns that span chunk boundaries.
        """
        compiled = cls.compile(pattern)
        pat_len = compiled.size
        overlap = pat_len - 1
        matches: List[PatternMatch] = []

        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        with open(filepath, "rb") as f:
            carry = b""
            current_file_offset = 0

            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break

                search_buf = carry + chunk
                search_base_offset = current_file_offset - len(carry)

                pos = 0
                while pos < len(search_buf):
                    m = compiled.regex.search(search_buf, pos)
                    if m is None:
                        break
                    match_in_buf = m.start()
                    abs_offset = search_base_offset + match_in_buf

                    # Avoid recording duplicate matches that were already captured in the previous chunk
                    if not matches or matches[-1].offset != abs_offset:
                        matches.append(PatternMatch(
                            offset=abs_offset,
                            address=base_address + abs_offset,
                            size=pat_len,
                            data=bytes(m.group(0)),
                        ))

                    pos = match_in_buf + 1

                current_file_offset += len(chunk)
                if overlap > 0:
                    carry = search_buf[-overlap:]
                else:
                    carry = b""

        return matches

    @classmethod
    def replace(
        cls,
        buffer: bytearray,
        pattern: Union[str, CompiledPattern],
        replacement: Union[str, bytes],
        count: Optional[int] = None,
    ) -> int:
        """
        Replaces matched pattern in buffer in-place.
        If replacement is a string with wildcards ('??' or '?'), the original byte at that position
        is preserved, allowing surgical patching without clobbering dynamic bytes.
        Returns the number of matches replaced.
        """
        compiled = cls.compile(pattern)
        pat_len = compiled.size

        # Parse replacement bytes and replacement mask
        if isinstance(replacement, str):
            rep_tokens = replacement.strip().split()
            if len(rep_tokens) != pat_len:
                raise ValueError(
                    f"Replacement token count ({len(rep_tokens)}) must match pattern length ({pat_len})"
                )
            rep_bytes: List[int] = []
            rep_mask: List[bool] = []  # True = replace, False = preserve
            for t in rep_tokens:
                if t in ("??", "?"):
                    rep_bytes.append(0)
                    rep_mask.append(False)
                else:
                    val = int(t, 16)
                    rep_bytes.append(val)
                    rep_mask.append(True)
        else:
            if len(replacement) != pat_len:
                raise ValueError(
                    f"Replacement byte length ({len(replacement)}) must match pattern length ({pat_len})"
                )
            rep_bytes = list(replacement)
            rep_mask = [True] * pat_len

        matches = cls.find_all(buffer, compiled)
        if count is not None:
            matches = matches[:count]

        for m in matches:
            off = m.offset
            for idx in range(pat_len):
                if rep_mask[idx]:
                    buffer[off + idx] = rep_bytes[idx]

        return len(matches)

    @classmethod
    def create_pattern(cls, data: bytes, wildcard_indices: Optional[List[int]] = None) -> str:
        """
        Creates an IDA-style pattern string from raw bytes, marking specific indices as '??'.
        """
        wildcard_set = set(wildcard_indices or [])
        tokens = []
        for i, b in enumerate(data):
            if i in wildcard_set:
                tokens.append("??")
            else:
                tokens.append(f"{b:02X}")
        return " ".join(tokens)
