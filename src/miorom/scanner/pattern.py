"""
from miorom.errors import ParseError
miorom.scanner.pattern
~~~~~~~~~~~~~~~~~~~~~~
Universal Array-of-Bytes (AOB) pattern scanner and signature engine.
Supports IDA Pro, Cheat Engine, and Ghidra signature patterns with wildcards ('??' or '?').
Provides fast multi-byte search, sliding-window chunked file scanning, and
wildcard-preserving binary patching.
"""

from miorom.result import MioRomResult
import os
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple, Union


@dataclass
class PatternMatch(MioRomResult):
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
            raise ParseError("Pattern string cannot be empty.")

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
                    raise ParseError(f"Invalid byte literal in pattern: '{token}'")
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
        return list(cls.iter_matches(buffer, pattern, start=start, base_address=base_address, max_matches=max_matches))

    @classmethod
    def iter_matches(
        cls,
        buffer: Union[bytes, bytearray, memoryview],
        pattern: Union[str, CompiledPattern],
        start: int = 0,
        base_address: int = 0,
        max_matches: Optional[int] = None,
    ) -> Iterator[PatternMatch]:
        """Yield pattern matches progressively so callers can stop early."""
        compiled = cls.compile(pattern)
        buf_bytes = bytes(buffer) if not isinstance(buffer, (bytes, bytearray, memoryview)) else buffer
        yielded = 0
        pos = start
        while pos < len(buf_bytes):
            m = compiled.regex.search(buf_bytes, pos)
            if m is None:
                break
            match_start = m.start()
            matched_data = bytes(m.group(0))
            yield PatternMatch(
                offset=match_start,
                address=base_address + match_start,
                size=len(matched_data),
                data=matched_data,
            )
            yielded += 1
            if max_matches is not None and yielded >= max_matches:
                break
            pos = match_start + 1

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
        if not os.path.isfile(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        return list(cls.iter_file(filepath, pattern, base_address=base_address, chunk_size=chunk_size))

    @classmethod
    def iter_file(
        cls,
        filepath: str,
        pattern: Union[str, CompiledPattern],
        base_address: int = 0,
        chunk_size: int = 65536,
    ) -> Iterator[PatternMatch]:
        """Stream matches from a large file while keeping boundary overlap correct."""
        compiled = cls.compile(pattern)
        pat_len = compiled.size
        overlap = pat_len - 1
        last_offset: Optional[int] = None

        with open(filepath, "rb") as file_obj:
            carry = b""
            current_file_offset = 0

            while True:
                chunk = file_obj.read(chunk_size)
                if not chunk:
                    break

                search_buf = carry + chunk
                search_base_offset = current_file_offset - len(carry)
                pos = 0

                while pos < len(search_buf):
                    match = compiled.regex.search(search_buf, pos)
                    if match is None:
                        break

                    match_in_buf = match.start()
                    abs_offset = search_base_offset + match_in_buf
                    if last_offset is None or last_offset != abs_offset:
                        last_offset = abs_offset
                        yield PatternMatch(
                            offset=abs_offset,
                            address=base_address + abs_offset,
                            size=pat_len,
                            data=bytes(match.group(0)),
                        )

                    pos = match_in_buf + 1

                current_file_offset += len(chunk)
                carry = search_buf[-overlap:] if overlap > 0 else b""

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
                raise ParseError(
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
                raise ParseError(
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
