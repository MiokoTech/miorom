"""
miorom.core.rom_view
~~~~~~~~~~~~~~~~~~~~
Fluent, high-level ROM and binary data analysis wrapper.
Provides a pythonic interface (inspired by pwntools / radare2) for interactive
reverse engineering, string querying, pointer scanning, and automated diagnosis.
"""

import os

from miorom.errors import ParseError
import re
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

from miorom.core.scanner import StringScanner, PointerScanner, FoundString, CandidatePointerTable
from miorom.scanner.inspector import SmartInspector, InspectionReport


class StringQuery:
    """Chainable query interface for strings found in binary data."""

    def __init__(self, data: bytes, default_encoding: str = "ascii"):
        self._data = data
        self._default_encoding = default_encoding
        self._cache: Dict[str, List[FoundString]] = {}

    def _get_strings(self, encoding: str, min_len: int = 4) -> List[FoundString]:
        cache_key = f"{encoding}:{min_len}"
        if cache_key not in self._cache:
            self._cache[cache_key] = StringScanner.scan_strings(
                self._data, min_length=min_len, encoding=encoding
            )
        return self._cache[cache_key]

    def all(self, encoding: Optional[str] = None, min_len: int = 4) -> List[FoundString]:
        enc = encoding or self._default_encoding
        return self._get_strings(enc, min_len)

    def filter(
        self,
        encoding: Optional[str] = None,
        min_len: int = 4,
        contains: Optional[str] = None,
        predicate: Optional[Callable[[FoundString], bool]] = None,
        regex: Optional[str] = None,
        alignment: int = 1,
        max_results: Optional[int] = None,
        start_offset: Optional[int] = None,
        end_offset: Optional[int] = None,
        case_sensitive: bool = False,
    ) -> List[FoundString]:
        """
        Filter strings from binary data matching specific conditions.

        Keyword Args:
            encoding: Text encoding to scan for (default: default_encoding).
            min_len: Minimum string length (default: 4).
            contains: Substring pattern that text must contain.
            predicate: Custom callable filter returning True for matching strings.
            regex: Regular expression pattern to search within text.
            alignment: Only include strings whose offset is a multiple of alignment.
            max_results: Maximum number of strings to return.
            start_offset: Minimum starting offset of strings.
            end_offset: Maximum ending offset of strings.
            case_sensitive: Whether `contains` check is case-sensitive (default: False).
        """
        enc = encoding or self._default_encoding
        strings = self._get_strings(enc, min_len)
        results = strings

        if start_offset is not None:
            results = [s for s in results if s.offset >= start_offset]
        if end_offset is not None:
            results = [s for s in results if s.offset < end_offset]
        if alignment > 1:
            results = [s for s in results if s.offset % alignment == 0]

        if contains:
            if case_sensitive:
                results = [s for s in results if contains in s.text]
            else:
                c_lower = contains.lower()
                results = [s for s in results if c_lower in s.text.lower()]

        if regex:
            rx = re.compile(regex) if isinstance(regex, str) else regex
            results = [s for s in results if rx.search(s.text)]

        if predicate:
            results = [s for s in results if predicate(s)]

        if max_results is not None and max_results > 0:
            results = results[:max_results]

        return results

    def __iter__(self) -> Iterator[FoundString]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self.all())

    def __repr__(self) -> str:
        return f"<StringQuery {len(self)} strings (encoding='{self._default_encoding}')>"


class ROM:
    """
    Fluent ROM / Binary analysis object.

    Usage:
        rom = ROM.open("game.iso")
        print(rom.diagnose().summary())

        for s in rom.strings.filter(contains="attack"):
            print(s.offset_hex, s.text)

        tables = rom.find_pointers()
    """

    def __init__(self, data: bytes, filepath: Optional[str] = None, name: Optional[str] = None):
        self._data = bytearray(data)
        self.filepath = filepath
        self.name = name or (os.path.basename(filepath) if filepath else "ROM")
        self._strings_proxy = StringQuery(bytes(self._data))

    # ------------------------------------------------------------------
    # Factory Loaders
    # ------------------------------------------------------------------

    @classmethod
    def open(cls, filepath: str) -> "ROM":
        """Open and read a ROM, ISO, or binary file from disk."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: '{filepath}'")
        with open(filepath, "rb") as f:
            data = f.read()
        return cls(data, filepath=filepath)

    @classmethod
    def from_bytes(cls, data: bytes, name: str = "Buffer") -> "ROM":
        """Create a ROM object directly from in-memory bytes."""
        return cls(data, name=name)

    # ------------------------------------------------------------------
    # Properties & Basic Info
    # ------------------------------------------------------------------

    @property
    def data(self) -> bytes:
        return bytes(self._data)

    @property
    def bytearray(self) -> bytearray:
        return self._data

    @property
    def size(self) -> int:
        return len(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __getitem__(self, key: Union[int, slice]) -> bytes:
        if isinstance(key, slice):
            return bytes(self._data[key])
        return bytes([self._data[key]])

    def slice(self, start: int, end: Optional[int] = None) -> "ROM":
        """Return a child ROM slice."""
        sub = self._data[start:end]
        return ROM(sub, name=f"{self.name}[0x{start:X}:{hex(end) if end else 'EOF'}]")

    # ------------------------------------------------------------------
    # Diagnostic & Inspection
    # ------------------------------------------------------------------

    def diagnose(self) -> InspectionReport:
        """Run the comprehensive SmartInspector across the entire binary."""
        return SmartInspector.inspect(bytes(self._data), filepath=self.filepath)

    @property
    def strings(self) -> StringQuery:
        """Queryable interface for strings."""
        return self._strings_proxy

    def find_pointers(
        self,
        targets: Optional[List[int]] = None,
        strides: Union[int, Sequence[int]] = (4, 2, 8),
        endians: Union[str, Sequence[str]] = ("<", ">"),
        min_pointers: int = 4,
        stride: Optional[Union[int, Sequence[int]]] = None,
        endian: Optional[Union[str, Sequence[str]]] = None,
        min_confidence: float = 0.0,
        max_tables: Optional[int] = None,
        base_offsets: Optional[List[int]] = None,
        max_search_offset: Optional[int] = None,
        start_offset: int = 0,
    ) -> List[CandidatePointerTable]:
        """Scan for pointer arrays referencing detected strings or given target offsets."""
        target_list = targets if targets is not None else [s.offset for s in self.strings.all()]
        return PointerScanner.find_pointer_tables(
            bytes(self._data),
            target_list,
            strides=strides,
            endians=endians,
            min_pointers=min_pointers,
            base_offsets=base_offsets,
            max_search_offset=max_search_offset,
            stride=stride,
            endian=endian,
            min_confidence=min_confidence,
            max_tables=max_tables,
            start_offset=start_offset,
        )

    def find_footer_pointers(
        self,
        targets: Optional[List[int]] = None,
        strides: Union[int, Sequence[int]] = (4, 2, 8),
        endians: Union[str, Sequence[str]] = ("<", ">"),
        min_pointers: int = 2,
        footer_bytes: int = 256,
        stride: Optional[Union[int, Sequence[int]]] = None,
        endian: Optional[Union[str, Sequence[str]]] = None,
        min_confidence: float = 0.0,
        max_tables: Optional[int] = None,
    ) -> List[CandidatePointerTable]:
        """Scan footer area for secondary pointer tables (e.g. dual-table containers)."""
        target_list = targets if targets is not None else [s.offset for s in self.strings.all()]
        return PointerScanner.find_footer_pointer_tables(
            bytes(self._data),
            target_list,
            strides=strides,
            endians=endians,
            min_pointers=min_pointers,
            footer_scan_bytes=footer_bytes,
            stride=stride,
            endian=endian,
            min_confidence=min_confidence,
            max_tables=max_tables,
        )

    @property
    def orphans(self) -> List[FoundString]:
        """Detect strings not referenced by any identified pointer table."""
        all_strings = self.strings.all()
        offsets = [s.offset for s in all_strings]
        tables = self.find_pointers(offsets) + self.find_footer_pointers(offsets)
        ref_offsets = {tgt for t in tables for _, tgt in t.entries}
        return [s for s in all_strings if s.offset not in ref_offsets]

    # ------------------------------------------------------------------
    # Mutation & Export
    # ------------------------------------------------------------------

    def write_at(self, offset: int, data: bytes) -> None:
        """Write raw bytes at offset in-place."""
        end = offset + len(data)
        if end > len(self._data):
            self._data.extend(b"\x00" * (end - len(self._data)))
        self._data[offset:end] = data

    def save(self, filepath: Optional[str] = None) -> None:
        """Save binary data to file."""
        dest = filepath or self.filepath
        if not dest:
            raise ParseError("No destination filepath specified.")
        with open(dest, "wb") as f:
            f.write(self._data)

    def __repr__(self) -> str:
        return f"<ROM '{self.name}' size={self.size:,} bytes (0x{self.size:X})>"
