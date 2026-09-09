import re
import string
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Tuple, Dict, Any, Set, Sequence, Union

from miorom.text.charmap import CharMap
from miorom.result import MioRomResult


@dataclass
class FoundString(MioRomResult):
    offset: int
    length: int  # Byte length in file
    text: str
    raw_bytes: bytes

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:06X}"

    def __repr__(self) -> str:
        preview = self.text if len(self.text) <= 30 else self.text[:27] + "..."
        return f"<FoundString {self.offset_hex}: {preview!r}>"


@dataclass
class TextBlock(MioRomResult):
    start_offset: int
    end_offset: int
    strings: List[FoundString] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.strings)

    @property
    def total_bytes(self) -> int:
        return self.end_offset - self.start_offset

    def __repr__(self) -> str:
        return (f"<TextBlock 0x{self.start_offset:06X}-0x{self.end_offset:06X} "
                f"({self.count} strings, {self.total_bytes} bytes)>")


@dataclass
class CandidatePointerTable(MioRomResult):
    table_offset: int
    count: int
    stride: int
    endian: str
    base_offset: int
    entries: List[Tuple[int, int]] = field(default_factory=list)  # (table_entry_offset, resolved_target_offset)
    confidence: float = 0.0

    @property
    def table_offset_hex(self) -> str:
        return f"0x{self.table_offset:06X}"

    @property
    def base_offset_hex(self) -> str:
        return f"0x{self.base_offset:08X}"

    def __repr__(self) -> str:
        return (f"<CandidatePointerTable {self.table_offset_hex} count={self.count} "
                f"stride={self.stride} endian='{self.endian}' base={self.base_offset_hex} "
                f"confidence={self.confidence:.2f}>")


class StringScanner:
    """
    Scanner for detecting strings in binary ROMs and game archives.
    Supports ASCII, UTF-8, Shift-JIS, UTF-16, and custom .tbl character maps.
    """

    @classmethod
    def scan_strings(
        cls,
        data: bytes,
        min_length: int = 4,
        encoding: str = "ascii",
        charmap: Optional[CharMap] = None,
        null_terminated: bool = True,
        allow_control_chars: bool = True,
        start_offset: int = 0,
        end_offset: Optional[int] = None,
        pattern: Optional[str] = None,
        regex: Optional[str] = None,
        alignment: int = 1,
        max_strings: Optional[int] = None,
        strip_whitespace: bool = False,
        case_sensitive: bool = True,
    ) -> List[FoundString]:
        """
        Scans data for contiguous strings meeting length and encoding requirements.

        Keyword Args:
            pattern: Substring filter for matching text.
            regex: Regex pattern to filter matching text.
            alignment: Only return strings whose start offset is a multiple of alignment.
            max_strings: Limit the maximum number of returned FoundString entries.
            strip_whitespace: Strip leading/trailing whitespace from detected strings.
            case_sensitive: Whether pattern matching is case-sensitive (default: True).
        """
        if end_offset is None:
            end_offset = len(data)

        return list(cls.iter_strings(
            data=data,
            min_length=min_length,
            encoding=encoding,
            charmap=charmap,
            null_terminated=null_terminated,
            allow_control_chars=allow_control_chars,
            start_offset=start_offset,
            end_offset=end_offset,
            pattern=pattern,
            regex=regex,
            alignment=alignment,
            max_strings=max_strings,
            strip_whitespace=strip_whitespace,
            case_sensitive=case_sensitive,
        ))

    @classmethod
    def iter_strings(
        cls,
        data: bytes,
        min_length: int = 4,
        encoding: str = "ascii",
        charmap: Optional[CharMap] = None,
        null_terminated: bool = True,
        allow_control_chars: bool = True,
        start_offset: int = 0,
        end_offset: Optional[int] = None,
        pattern: Optional[str] = None,
        regex: Optional[str] = None,
        alignment: int = 1,
        max_strings: Optional[int] = None,
        strip_whitespace: bool = False,
        case_sensitive: bool = True,
    ):
        """Yield filtered strings progressively; stop early when the consumer stops."""
        if end_offset is None:
            end_offset = len(data)
        count = 0
        if charmap is not None:
            candidates = cls._iter_charmap(data, charmap, min_length, start_offset, end_offset)
        elif encoding.lower() in ("utf-16", "utf-16-le", "utf-16-be"):
            candidates = cls._iter_utf16(data, encoding, min_length, start_offset, end_offset)
        else:
            candidates = cls._iter_standard(data, encoding, min_length, allow_control_chars, start_offset, end_offset)

        for found in candidates:
            if alignment > 1 and found.offset % alignment:
                continue
            if strip_whitespace:
                text = found.text.strip()
                if len(text) < min_length:
                    continue
                found = FoundString(offset=found.offset, length=found.length, text=text, raw_bytes=found.raw_bytes)
            if pattern:
                if case_sensitive and pattern not in found.text:
                    continue
                if not case_sensitive and pattern.lower() not in found.text.lower():
                    continue
            if regex and not re.compile(regex).search(found.text):
                continue
            if max_strings is not None and max_strings > 0 and count >= max_strings:
                return
            count += 1
            yield found

    @classmethod
    def _is_printable_byte(cls, b: int, allow_control: bool) -> bool:
        if 0x20 <= b <= 0x7E:
            return True
        if allow_control and b in (0x09, 0x0A, 0x0D):  # \t, \n, \r
            return True
        return False

    @classmethod
    def _iter_standard(
        cls,
        data: bytes,
        encoding: str,
        min_length: int,
        allow_control: bool,
        start_offset: int,
        end_offset: int
    ) -> Iterator[FoundString]:
        in_pos = start_offset
        is_ascii = encoding.lower() in ("ascii", "latin1", "iso-8859-1")

        while in_pos < end_offset:
            # Skip unprintable bytes and nulls
            if is_ascii:
                while in_pos < end_offset and not cls._is_printable_byte(data[in_pos], allow_control):
                    in_pos += 1
            else:
                while in_pos < end_offset and data[in_pos] == 0:
                    in_pos += 1

            if in_pos >= end_offset:
                break

            start = in_pos
            if is_ascii:
                while in_pos < end_offset and cls._is_printable_byte(data[in_pos], allow_control):
                    in_pos += 1
            else:
                while in_pos < end_offset and data[in_pos] != 0:
                    in_pos += 1

            chunk = data[start:in_pos]
            has_null = in_pos < end_offset and data[in_pos] == 0
            full_len = (in_pos - start) + (1 if has_null else 0)

            if len(chunk) >= min_length:
                try:
                    text = chunk.decode(encoding)
                    if cls._is_valid_text(text, allow_control):
                        yield FoundString(
                            offset=start,
                            length=full_len,
                            text=text,
                            raw_bytes=chunk
                        )
                except (UnicodeDecodeError, ValueError):
                    pass

            if has_null:
                in_pos += 1

        return

    @classmethod
    def _is_valid_text(cls, text: str, allow_control_chars: bool) -> bool:
        if not text:
            return False
        printable_count = 0
        for char in text:
            if char.isprintable() or (allow_control_chars and char in "\n\r\t"):
                printable_count += 1
        return (printable_count / len(text)) >= 0.85

    @classmethod
    def _iter_utf16(cls, data: bytes, encoding: str, min_length: int, start_offset: int, end_offset: int) -> Iterator[FoundString]:
        in_pos = start_offset & ~1

        while in_pos + 1 < end_offset:
            start = in_pos
            while in_pos + 1 < end_offset:
                w = data[in_pos:in_pos+2]
                if w == b"\x00\x00":
                    break
                in_pos += 2

            chunk_len = in_pos - start
            if chunk_len >= (min_length * 2):
                raw = data[start:in_pos]
                try:
                    text = raw.decode(encoding)
                    if cls._is_valid_text(text, allow_control_chars=True):
                        yield FoundString(
                            offset=start,
                            length=chunk_len + 2,
                            text=text,
                            raw_bytes=raw
                        )
                except (UnicodeDecodeError, ValueError):
                    pass

            while in_pos + 1 < end_offset and data[in_pos:in_pos+2] == b"\x00\x00":
                in_pos += 2

        return

    @classmethod
    def _iter_charmap(cls, data: bytes, charmap: CharMap, min_length: int, start_offset: int, end_offset: int) -> Iterator[FoundString]:
        in_pos = start_offset

        while in_pos < end_offset:
            start = in_pos
            curr_str = []
            curr_bytes = bytearray()

            while in_pos < end_offset:
                matched = False
                if in_pos + 1 < end_offset:
                    two_bytes = data[in_pos:in_pos+2]
                    if two_bytes in charmap.byte_to_char:
                        curr_str.append(charmap.byte_to_char[two_bytes])
                        curr_bytes.extend(two_bytes)
                        in_pos += 2
                        matched = True

                if not matched:
                    one_byte = data[in_pos:in_pos+1]
                    if one_byte in charmap.byte_to_char:
                        curr_str.append(charmap.byte_to_char[one_byte])
                        curr_bytes.extend(one_byte)
                        in_pos += 1
                        matched = True

                if not matched:
                    break

            if len(curr_str) >= min_length:
                yield FoundString(
                    offset=start,
                    length=len(curr_bytes),
                    text="".join(curr_str),
                    raw_bytes=bytes(curr_bytes)
                )

            in_pos = max(in_pos + 1, start + 1)

        return

    @classmethod
    def group_into_blocks(cls, strings: List[FoundString], max_gap: int = 64) -> List[TextBlock]:
        """
        Groups detected strings into contiguous text blocks.
        """
        if not strings:
            return []

        sorted_strings = sorted(strings, key=lambda s: s.offset)
        blocks: List[TextBlock] = []

        current_block = TextBlock(
            start_offset=sorted_strings[0].offset,
            end_offset=sorted_strings[0].offset + sorted_strings[0].length,
            strings=[sorted_strings[0]]
        )

        for s in sorted_strings[1:]:
            prev_end = current_block.end_offset
            if s.offset - prev_end <= max_gap:
                current_block.end_offset = max(current_block.end_offset, s.offset + s.length)
                current_block.strings.append(s)
            else:
                blocks.append(current_block)
                current_block = TextBlock(
                    start_offset=s.offset,
                    end_offset=s.offset + s.length,
                    strings=[s]
                )

        blocks.append(current_block)
        return blocks


class PointerScanner:
    """
    Scanner for detecting pointer tables that reference string offsets or text blocks.
    Identifies 16-bit, 32-bit, and 64-bit flagged/strided pointer arrays.
    """

    @classmethod
    def find_pointer_tables(
        cls,
        data: bytes,
        target_offsets: List[int],
        strides: Union[int, Sequence[int]] = (4, 2, 8),
        endians: Union[str, Sequence[str]] = ("<", ">"),
        min_pointers: int = 4,
        base_offsets: Optional[List[int]] = None,
        max_search_offset: Optional[int] = None,
        stride: Optional[Union[int, Sequence[int]]] = None,
        endian: Optional[Union[str, Sequence[str]]] = None,
        min_confidence: float = 0.0,
        max_tables: Optional[int] = None,
        start_offset: int = 0,
    ) -> List[CandidatePointerTable]:
        return list(cls.iter_pointer_tables(
            data=data,
            target_offsets=target_offsets,
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
        ))

    @classmethod
    def iter_pointer_tables(
        cls,
        data: bytes,
        target_offsets: List[int],
        strides: Union[int, Sequence[int]] = (4, 2, 8),
        endians: Union[str, Sequence[str]] = ("<", ">"),
        min_pointers: int = 4,
        base_offsets: Optional[List[int]] = None,
        max_search_offset: Optional[int] = None,
        stride: Optional[Union[int, Sequence[int]]] = None,
        endian: Optional[Union[str, Sequence[str]]] = None,
        min_confidence: float = 0.0,
        max_tables: Optional[int] = None,
        start_offset: int = 0,
    ):
        """
        Finds arrays of pointers pointing to the given target string offsets.

        Keyword Args:
            strides / stride: Stride length(s) to check (e.g. 4, 2, 8, or (4, 2)).
            endians / endian: Endianness to test (e.g. "<", ">", or ("<", ">")).
            min_pointers: Minimum consecutive pointers to qualify as a table.
            base_offsets: Known base offsets to check against.
            max_search_offset: Stop scanning at this file offset.
            start_offset: Offset to start scanning from (default: 0).
            min_confidence: Filter candidate tables by minimum confidence score (0.0 to 1.0).
            max_tables: Maximum number of tables to return.
        """
        if not target_offsets:
            return iter([])

        if stride is not None:
            active_strides = (stride,) if isinstance(stride, int) else tuple(stride)
        elif isinstance(strides, int):
            active_strides = (strides,)
        else:
            active_strides = tuple(strides)

        if endian is not None:
            active_endians = (endian,) if isinstance(endian, str) else tuple(endian)
        elif isinstance(endians, str):
            active_endians = (endians,)
        else:
            active_endians = tuple(endians)

        target_set = set(target_offsets)
        yielded = 0
        data_len = len(data)
        if max_search_offset is None:
            max_search_offset = data_len

        bases_to_check = set(base_offsets if base_offsets is not None else [0])
        if not base_offsets:
            auto_bases = cls._detect_candidate_bases(data, target_offsets, endians=active_endians)
            bases_to_check.update(auto_bases)

        for end_val in active_endians:
            for strd in active_strides:
                for base in bases_to_check:
                    tables = cls._scan_for_stride(
                        data=data,
                        target_set=target_set,
                        stride=strd,
                        endian=end_val,
                        base=base,
                        min_pointers=min_pointers,
                        max_search_offset=max_search_offset,
                        start_offset=start_offset,
                    )
                    for table in sorted(
                        tables,
                        key=lambda item: (item.confidence, item.count),
                        reverse=True,
                    ):
                        if min_confidence > 0.0 and table.confidence < min_confidence:
                            continue
                        if max_tables is not None and max_tables > 0 and yielded >= max_tables:
                            return
                        yielded += 1
                        yield table

    @classmethod
    def _scan_for_stride(
        cls,
        data: bytes,
        target_set: Set[int],
        stride: int,
        endian: str,
        base: int,
        min_pointers: int,
        max_search_offset: int,
        start_offset: int = 0,
    ) -> List[CandidatePointerTable]:
        results: List[CandidatePointerTable] = []
        fmt = f"{endian}{'H' if stride == 2 else 'I'}"
        read_bytes = 2 if stride == 2 else 4

        pos = start_offset
        limit = min(len(data) - stride, max_search_offset)

        while pos <= limit:
            curr_pos = pos
            run_entries: List[Tuple[int, int]] = []

            while curr_pos + stride <= len(data):
                raw = data[curr_pos:curr_pos + read_bytes]
                val = struct.unpack(fmt, raw)[0]
                target = val + base

                if target in target_set:
                    # Prevent zero-fill or identical padding from forming fake pointer runs
                    if (len(run_entries) >= 2 and
                        run_entries[-1][1] == target and
                        run_entries[-2][1] == target):
                        break
                    run_entries.append((curr_pos, target))
                    curr_pos += stride
                else:
                    break

            unique_targets = len(set(t for _, t in run_entries))
            # Require at least min_pointers and diversity of targets (prevents zero-fill false positives)
            min_unique = min(3, min_pointers)
            if len(run_entries) >= min_pointers and unique_targets >= min_unique:
                is_monotonic = True
                for i in range(1, len(run_entries)):
                    if run_entries[i][1] < run_entries[i-1][1]:
                        is_monotonic = False
                        break

                confidence = 0.5 + (0.3 if is_monotonic else 0.0) + min(0.2, len(run_entries) * 0.01)
                results.append(CandidatePointerTable(
                    table_offset=pos,
                    count=len(run_entries),
                    stride=stride,
                    endian=endian,
                    base_offset=base,
                    entries=run_entries,
                    confidence=min(1.0, confidence)
                ))
                pos = curr_pos
            else:
                pos += stride if stride in (2, 4) else 4

        return results

    @classmethod
    def find_footer_pointer_tables(
        cls,
        data: bytes,
        target_offsets: List[int],
        strides: Union[int, Sequence[int]] = (4, 2, 8),
        endians: Union[str, Sequence[str]] = ("<", ">"),
        min_pointers: int = 2,
        footer_scan_bytes: int = 256,
        stride: Optional[Union[int, Sequence[int]]] = None,
        endian: Optional[Union[str, Sequence[str]]] = None,
        min_confidence: float = 0.0,
        max_tables: Optional[int] = None,
    ) -> List["CandidatePointerTable"]:
        """
        Scans the footer region of a binary file for pointer tables that reference
        detected string offsets. Useful for dual-table formats (e.g., Neverland/Marvelous
        .fefe containers) where secondary pointer tables are placed at end-of-file.

        Unlike find_pointer_tables() which scans forward from offset 0,
        this method scans backward from the end of file in a configurable window.
        A lower min_pointers default (2) is used since footer tables tend to be small.
        """
        return list(cls.iter_footer_pointer_tables(
            data, target_offsets, strides=strides, endians=endians,
            min_pointers=min_pointers, footer_scan_bytes=footer_scan_bytes,
            stride=stride, endian=endian, min_confidence=min_confidence,
            max_tables=max_tables,
        ))

    @classmethod
    def iter_footer_pointer_tables(
        cls,
        data: bytes,
        target_offsets: List[int],
        strides: Union[int, Sequence[int]] = (4, 2, 8),
        endians: Union[str, Sequence[str]] = ("<", ">"),
        min_pointers: int = 2,
        footer_scan_bytes: int = 256,
        stride: Optional[Union[int, Sequence[int]]] = None,
        endian: Optional[Union[str, Sequence[int]]] = None,
        min_confidence: float = 0.0,
        max_tables: Optional[int] = None,
    ) -> Iterator["CandidatePointerTable"]:
        """Yield footer pointer-table candidates progressively."""
        if not target_offsets or len(data) < 16:
            return iter([])

        if stride is not None:
            active_strides = (stride,) if isinstance(stride, int) else tuple(stride)
        elif isinstance(strides, int):
            active_strides = (strides,)
        else:
            active_strides = tuple(strides)

        if endian is not None:
            active_endians = (endian,) if isinstance(endian, str) else tuple(endian)
        elif isinstance(endians, str):
            active_endians = (endians,)
        else:
            active_endians = tuple(endians)

        target_set = set(target_offsets)
        data_len = len(data)
        scan_start = max(0, data_len - footer_scan_bytes)

        candidate_tables: List[CandidatePointerTable] = []

        for end_val in active_endians:
            for strd in active_strides:
                read_bytes = 2 if strd == 2 else 4
                fmt = f"{end_val}{'H' if strd == 2 else 'I'}"

                pos = scan_start
                limit = data_len - strd
                while pos <= limit:
                    curr_pos = pos
                    run_entries: List[Tuple[int, int]] = []

                    while curr_pos + strd <= data_len:
                        raw = data[curr_pos:curr_pos + read_bytes]
                        if len(raw) < read_bytes:
                            break
                        val = struct.unpack(fmt, raw)[0]
                        if val in target_set:
                            run_entries.append((curr_pos, val))
                            curr_pos += strd
                        else:
                            break

                    if len(run_entries) >= min_pointers:
                        unique_targets = len(set(t for _, t in run_entries))
                        if unique_targets >= max(1, min_pointers - 1):
                            confidence = 0.6 + min(0.3, len(run_entries) * 0.05)
                            candidate_tables.append(CandidatePointerTable(
                                table_offset=pos,
                                count=len(run_entries),
                                stride=strd,
                                endian=end_val,
                                base_offset=0,
                                entries=run_entries,
                                confidence=min(0.95, confidence)
                            ))
                            pos = curr_pos
                            continue
                    pos += strd if strd in (2, 4) else 4

        # Deduplicate: keep highest confidence per table_offset
        seen: Dict[int, CandidatePointerTable] = {}
        for t in candidate_tables:
            if t.table_offset not in seen or t.confidence > seen[t.table_offset].confidence:
                seen[t.table_offset] = t

        sorted_tables = sorted(seen.values(), key=lambda t: (t.confidence, t.count), reverse=True)
        if min_confidence > 0.0:
            sorted_tables = [t for t in sorted_tables if t.confidence >= min_confidence]
        if max_tables is not None and max_tables > 0:
            sorted_tables = sorted_tables[:max_tables]

        return sorted_tables

    @classmethod
    def _detect_candidate_bases(
        cls,
        data: bytes,
        target_offsets: List[int],
        endians: Tuple[str, ...] = ("<", ">")
    ) -> List[int]:
        first_few = sorted(target_offsets)[:10]
        if not first_few:
            return [0]

        deltas: Counter = Counter()
        step = 4
        limit = min(len(data) - 4, 0x100000)
        for endian in endians:
            fmt = f"{endian}I"
            for pos in range(0, limit, step):
                val = struct.unpack(fmt, data[pos:pos+4])[0]
                for target in first_few:
                    delta = val - target
                    if delta >= 0 and (delta % 0x1000 == 0 or delta < 0x10000):
                        deltas[delta] += 1

        common = [delta for delta, count in deltas.most_common(5) if count >= 3]
        return common if common else [0]
