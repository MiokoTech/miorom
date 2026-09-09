"""
miorom.scanner.table_detector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Heuristic Binary Table, Pointer Array & Stride Detector.
Reverse-engineers unknown binary data blobs by automatically discovering
pointer tables, record strides, string pools, and terminator delimiters
without manual hex guessing.
"""

from dataclasses import dataclass, field
import struct
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class TableCandidate(MioRomResult):
    """Discovered candidate pointer or record table."""
    offset: int
    count: int
    stride: int
    pointer_offset_in_entry: int
    pointer_size: int
    endian: str
    target_min: int
    target_max: int
    sample_strings: List[str] = field(default_factory=list)
    confidence: float = 0.0

    def __repr__(self) -> str:
        return (
            f"TableCandidate(offset=0x{self.offset:06X}, count={self.count}, "
            f"stride={self.stride}, conf={self.confidence:.2f})"
        )


class HeuristicTableDetector:
    """
    Automated statistical detector for binary pointer tables and record tables.
    """

    @classmethod
    def _is_printable_text(
        cls,
        data: bytes,
        start: int,
        max_len: int = 256,
        terminators: Sequence[int] = (0x00,),
        encoding: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Checks if bytes at start form a printable terminated string.
        Supports ASCII, UTF-8, Shift-JIS, CP1252, and custom terminators.
        """
        if start >= len(data):
            return False, ""
        cur = start
        chars = bytearray()
        while cur < len(data) and cur - start < max_len:
            b = data[cur]
            if b in terminators:
                break
            chars.append(b)
            cur += 1

        if len(chars) < 1:
            return False, ""

        encs = [encoding] if encoding else ["utf-8", "ascii", "shift_jis", "cp1252"]
        for enc in encs:
            try:
                decoded = chars.decode(enc)
                if all(c.isprintable() or c in ("\n", "\r", "\t") for c in decoded):
                    return True, decoded
            except (UnicodeDecodeError, LookupError):
                continue

        return False, ""

    @classmethod
    def _is_printable_ascii(cls, data: bytes, start: int, max_len: int = 64) -> Tuple[bool, str]:
        """Checks if bytes at start form a printable ASCII string (backward compatibility)."""
        return cls._is_printable_text(data, start, max_len=max_len, terminators=(0x00,), encoding="ascii")

    @classmethod
    def detect_pointer_tables(
        cls,
        data: bytes,
        min_entries: int = 4,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        terminators: Sequence[int] = (0x00,),
        encoding: Optional[str] = None,
        allow_null: bool = False,
        max_null_streak: int = 3,
        max_scan_bytes: Optional[int] = None,
    ) -> List[TableCandidate]:
        return list(cls.iter_pointer_tables(
            data=data,
            min_entries=min_entries,
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            terminators=terminators,
            encoding=encoding,
            allow_null=allow_null,
            max_null_streak=max_null_streak,
            max_scan_bytes=max_scan_bytes,
        ))

    @classmethod
    def iter_pointer_tables(
        cls,
        data: bytes,
        min_entries: int = 4,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        terminators: Sequence[int] = (0x00,),
        encoding: Optional[str] = None,
        allow_null: bool = False,
        max_null_streak: int = 3,
        max_scan_bytes: Optional[int] = None,
    ) -> Iterator[TableCandidate]:
        """
        Scans binary buffer for contiguous arrays of pointers pointing to valid strings.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        step = pointer_size
        limit = len(data) - (min_entries * pointer_size)
        sentinel_vals = {0, 0xFFFF if pointer_size == 2 else 0xFFFFFFFF}

        cur_pos = 0
        while cur_pos <= limit:
            entries: List[Optional[int]] = []
            samples: List[str] = []
            check_pos = cur_pos
            consecutive_nulls = 0

            while check_pos + pointer_size <= len(data):
                val = struct.unpack_from(fmt, data, check_pos)[0]
                if allow_null and val in sentinel_vals:
                    consecutive_nulls += 1
                    if consecutive_nulls > max_null_streak:
                        break
                    entries.append(None)
                    check_pos += step
                    continue

                consecutive_nulls = 0
                target_offset = val - base_address

                if not (0 <= target_offset < len(data)):
                    break

                if cur_pos <= target_offset < check_pos + pointer_size:
                    break

                is_text, text = cls._is_printable_text(
                    data, target_offset, terminators=terminators, encoding=encoding
                )
                if not is_text:
                    break

                entries.append(target_offset)
                if len(samples) < 5:
                    samples.append(text)

                check_pos += step

            while entries and entries[-1] is None:
                entries.pop()

            valid_targets = [e for e in entries if e is not None]
            if len(valid_targets) >= min_entries:
                is_monotonic = all(valid_targets[i] <= valid_targets[i + 1] for i in range(len(valid_targets) - 1))
                confidence = 0.95 if is_monotonic else 0.80

                yield TableCandidate(
                    offset=cur_pos,
                    count=len(entries),
                    stride=pointer_size,
                    pointer_offset_in_entry=0,
                    pointer_size=pointer_size,
                    endian=endian,
                    target_min=min(valid_targets),
                    target_max=max(valid_targets),
                    sample_strings=samples,
                    confidence=confidence,
                )
                cur_pos = cur_pos + (len(entries) * step)
            else:
                cur_pos += step

        return

    @classmethod
    def detect_stride_records(
        cls,
        data: bytes,
        candidate_strides: Sequence[int] = (8, 12, 16, 20, 24, 32),
        min_records: int = 4,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        terminators: Sequence[int] = (0x00,),
        encoding: Optional[str] = None,
        allow_null: bool = False,
        max_null_streak: int = 3,
        max_scan_bytes: Optional[int] = None,
    ) -> List[TableCandidate]:
        """
        Scans for structured record arrays where a fixed field within each record
        contains a pointer to text data.
        """
        return list(cls.iter_stride_records(
            data=data,
            candidate_strides=candidate_strides,
            min_records=min_records,
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            terminators=terminators,
            encoding=encoding,
            allow_null=allow_null,
            max_null_streak=max_null_streak,
            max_scan_bytes=max_scan_bytes,
        ))

    @classmethod
    def _iter_stride_records_impl(
        cls,
        data: bytes,
        candidate_strides: Sequence[int],
        min_records: int,
        pointer_size: int,
        endian: str,
        base_address: int,
        terminators: Sequence[int],
        encoding: Optional[str],
        allow_null: bool,
        max_null_streak: int,
        max_scan_bytes: Optional[int] = None,
    ) -> Iterator[TableCandidate]:
        """Yield stride-record candidates progressively."""
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        sentinel_vals = {0, 0xFFFF if pointer_size == 2 else 0xFFFFFFFF}
        scan_limit = len(data) if max_scan_bytes is None else min(len(data), max_scan_bytes)

        for stride in candidate_strides:
            for ptr_offset in range(0, stride - pointer_size + 1, pointer_size):
                cur_pos = 0
                max_pos = min(
                    len(data) - (min_records * stride),
                    scan_limit - (min_records * stride),
                )

                while cur_pos <= max_pos:
                    entries: List[Optional[int]] = []
                    samples: List[str] = []
                    rec_pos = cur_pos
                    consecutive_nulls = 0

                    while rec_pos + stride <= len(data):
                        val = struct.unpack_from(fmt, data, rec_pos + ptr_offset)[0]
                        if allow_null and val in sentinel_vals:
                            consecutive_nulls += 1
                            if consecutive_nulls > max_null_streak:
                                break
                            entries.append(None)
                            rec_pos += stride
                            continue

                        consecutive_nulls = 0
                        target_offset = val - base_address

                        if not (0 <= target_offset < len(data)):
                            break

                        is_text, text = cls._is_printable_text(
                            data, target_offset, terminators=terminators, encoding=encoding
                        )
                        if not is_text:
                            break

                        entries.append(target_offset)
                        if len(samples) < 5:
                            samples.append(text)

                        rec_pos += stride

                    while entries and entries[-1] is None:
                        entries.pop()

                    valid_targets = [e for e in entries if e is not None]
                    if len(valid_targets) >= min_records:
                        yield (
                            TableCandidate(
                                offset=cur_pos,
                                count=len(entries),
                                stride=stride,
                                pointer_offset_in_entry=ptr_offset,
                                pointer_size=pointer_size,
                                endian=endian,
                                target_min=min(valid_targets),
                                target_max=max(valid_targets),
                                sample_strings=samples,
                                confidence=0.85,
                            )
                        )
                        cur_pos = cur_pos + (len(entries) * stride)
                    else:
                        cur_pos += stride

        return

    @classmethod
    def iter_stride_records(
        cls,
        data: bytes,
        candidate_strides: Sequence[int] = (8, 12, 16, 20, 24, 32),
        min_records: int = 4,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
        terminators: Sequence[int] = (0x00,),
        encoding: Optional[str] = None,
        allow_null: bool = False,
        max_null_streak: int = 3,
        max_scan_bytes: Optional[int] = None,
    ) -> Iterator[TableCandidate]:
        """Yield stride-record candidates progressively."""
        yield from cls._iter_stride_records_impl(
            data=data,
            candidate_strides=candidate_strides,
            min_records=min_records,
            pointer_size=pointer_size,
            endian=endian,
            base_address=base_address,
            terminators=terminators,
            encoding=encoding,
            allow_null=allow_null,
            max_null_streak=max_null_streak,
            max_scan_bytes=max_scan_bytes,
        )

    @classmethod
    def iter_length_offset_tables(
        cls,
        data: bytes,
        candidate_strides: Sequence[int] = (8, 12, 16, 20, 24, 32),
        min_records: int = 2,
        endian: str = "<",
        terminators: Sequence[int] = (0x00, 0x03),
        encoding: Optional[str] = None,
    ) -> Iterator[TableCandidate]:
        """Yield length/offset table candidates from the existing detector."""
        yield from cls.detect_length_offset_tables(
            data=data,
            candidate_strides=candidate_strides,
            min_records=min_records,
            endian=endian,
            terminators=terminators,
            encoding=encoding,
        )

    @classmethod
    def detect_length_offset_tables(
        cls,
        data: bytes,
        candidate_strides: Sequence[int] = (8, 12, 16, 20, 24, 32),
        min_records: int = 2,
        endian: str = "<",
        terminators: Sequence[int] = (0x00, 0x03),
        encoding: Optional[str] = None,
    ) -> List[TableCandidate]:
        """
        Discovers tables where records contain pointers to a following string pool
        bounded by the Table-Payload Boundary Invariant (payload_start = min(valid_pointers)).
        """
        results: List[TableCandidate] = []
        for ptr_size in (4, 2):
            fmt = f"{endian}{'I' if ptr_size == 4 else 'H'}"
            for stride in candidate_strides:
                if stride < ptr_size:
                    continue
                for ptr_off in range(0, stride - ptr_size + 1, ptr_size):
                    if len(data) < stride * min_records:
                        continue
                    first_ptr = struct.unpack_from(fmt, data, ptr_off)[0]
                    if not (stride <= first_ptr < len(data)):
                        continue
                    if first_ptr % stride == 0:
                        count = first_ptr // stride
                        if count < min_records:
                            continue

                        valid = True
                        targets: List[int] = []
                        samples: List[str] = []

                        for k in range(min(count, 32)):
                            ptr_val = struct.unpack_from(fmt, data, (k * stride) + ptr_off)[0]
                            if not (first_ptr <= ptr_val < len(data)):
                                valid = False
                                break
                            targets.append(ptr_val)
                            is_txt, s = cls._is_printable_text(
                                data, ptr_val, terminators=terminators, encoding=encoding
                            )
                            if is_txt and len(samples) < 5:
                                samples.append(s)

                        if valid and targets:
                            results.append(
                                TableCandidate(
                                    offset=0,
                                    count=count,
                                    stride=stride,
                                    pointer_offset_in_entry=ptr_off,
                                    pointer_size=ptr_size,
                                    endian=endian,
                                    target_min=min(targets),
                                    target_max=max(targets),
                                    sample_strings=samples,
                                    confidence=0.98 if samples else 0.85,
                                )
                            )

        # Sort by count descending (preferring finer fundamental strides)
        results.sort(key=lambda c: (c.confidence, c.count), reverse=True)
        filtered: List[TableCandidate] = []
        for cand in results:
            is_harmonic = False
            for existing in filtered:
                if (
                    existing.pointer_offset_in_entry == cand.pointer_offset_in_entry
                    and cand.stride % existing.stride == 0
                    and cand.offset == existing.offset
                ):
                    is_harmonic = True
                    break
            if not is_harmonic:
                filtered.append(cand)

        return filtered

    @classmethod
    def iter_strings(
        cls,
        data: bytes,
        candidate: TableCandidate,
        base_address: int = 0,
        terminators: Sequence[int] = (0x00,),
        encoding: str = "utf-8",
    ) -> Iterator[Tuple[int, str]]:
        """
        Extracts all strings addressed by the candidate table.
        """
        fmt = f"{candidate.endian}{'I' if candidate.pointer_size == 4 else 'H'}"

        for i in range(candidate.count):
            rec_off = candidate.offset + (i * candidate.stride) + candidate.pointer_offset_in_entry
            target = struct.unpack_from(fmt, data, rec_off)[0] - base_address

            if not (0 <= target < len(data)):
                yield (i, "")
                continue

            end = target
            while end < len(data) and data[end] not in terminators:
                end += 1

            s = data[target:end].decode(encoding, "replace")
            yield (i, s)

    @classmethod
    def extract_strings(
        cls,
        data: bytes,
        candidate: TableCandidate,
        base_address: int = 0,
        terminators: Sequence[int] = (0x00,),
        encoding: str = "utf-8",
    ) -> List[Tuple[int, str]]:
        """Backward-compatible materialized string extraction."""
        return list(cls.iter_strings(
            data=data,
            candidate=candidate,
            base_address=base_address,
            terminators=terminators,
            encoding=encoding,
        ))

        return extracted
