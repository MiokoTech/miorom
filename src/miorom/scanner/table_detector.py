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
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


@dataclass
class TableCandidate:
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


class HeuristicTableDetector:
    """
    Automated statistical detector for binary pointer tables and record tables.
    """

    @classmethod
    def _is_printable_ascii(cls, data: bytes, start: int, max_len: int = 64) -> Tuple[bool, str]:
        """Checks if bytes at start form a printable null-terminated string."""
        if start >= len(data):
            return False, ""
        cur = start
        chars = bytearray()
        while cur < len(data) and cur - start < max_len:
            b = data[cur]
            if b == 0:
                break
            if 0x20 <= b <= 0x7E or b in (0x0A, 0x0D, 0x09):
                chars.append(b)
                cur += 1
            else:
                return False, ""

        if len(chars) >= 2:
            return True, chars.decode("ascii", "replace")
        return False, ""

    @classmethod
    def detect_pointer_tables(
        cls,
        data: bytes,
        min_entries: int = 4,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
    ) -> List[TableCandidate]:
        """
        Scans binary buffer for contiguous arrays of pointers pointing to valid strings.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        step = pointer_size
        limit = len(data) - (min_entries * pointer_size)
        candidates: List[TableCandidate] = []

        cur_pos = 0
        while cur_pos <= limit:
            # Check candidate sequence starting at cur_pos
            valid_targets: List[int] = []
            samples: List[str] = []

            check_pos = cur_pos
            while check_pos + pointer_size <= len(data):
                val = struct.unpack_from(fmt, data, check_pos)[0]
                target_offset = val - base_address

                # Pointer must point forward within data bounds
                if not (0 <= target_offset < len(data)):
                    break

                # Pointer must not point inside the table itself
                if cur_pos <= target_offset < check_pos + pointer_size:
                    break

                # Target should point to printable string
                is_text, text = cls._is_printable_ascii(data, target_offset)
                if not is_text:
                    break

                valid_targets.append(target_offset)
                if len(samples) < 5:
                    samples.append(text)

                check_pos += step

            count = len(valid_targets)
            if count >= min_entries:
                # Calculate monotonicity (strictly non-decreasing offsets)
                is_monotonic = all(valid_targets[i] <= valid_targets[i + 1] for i in range(count - 1))
                confidence = 0.95 if is_monotonic else 0.80

                candidates.append(
                    TableCandidate(
                        offset=cur_pos,
                        count=count,
                        stride=pointer_size,
                        pointer_offset_in_entry=0,
                        pointer_size=pointer_size,
                        endian=endian,
                        target_min=min(valid_targets),
                        target_max=max(valid_targets),
                        sample_strings=samples,
                        confidence=confidence,
                    )
                )
                cur_pos = check_pos
            else:
                cur_pos += step

        return candidates

    @classmethod
    def detect_stride_records(
        cls,
        data: bytes,
        candidate_strides: Sequence[int] = (8, 12, 16, 20, 24, 32),
        min_records: int = 4,
        pointer_size: int = 4,
        endian: str = "<",
        base_address: int = 0,
    ) -> List[TableCandidate]:
        """
        Scans for structured record arrays where a fixed field within each record
        contains a pointer to text data.
        """
        fmt = f"{endian}{'I' if pointer_size == 4 else 'H'}"
        results: List[TableCandidate] = []

        for stride in candidate_strides:
            for ptr_offset in range(0, stride - pointer_size + 1, pointer_size):
                cur_pos = 0
                max_pos = len(data) - (min_records * stride)

                while cur_pos <= max_pos:
                    valid_targets: List[int] = []
                    samples: List[str] = []

                    rec_pos = cur_pos
                    while rec_pos + stride <= len(data):
                        val = struct.unpack_from(fmt, data, rec_pos + ptr_offset)[0]
                        target_offset = val - base_address

                        if not (0 <= target_offset < len(data)):
                            break

                        is_text, text = cls._is_printable_ascii(data, target_offset)
                        if not is_text:
                            break

                        valid_targets.append(target_offset)
                        if len(samples) < 5:
                            samples.append(text)

                        rec_pos += stride

                    count = len(valid_targets)
                    if count >= min_records:
                        results.append(
                            TableCandidate(
                                offset=cur_pos,
                                count=count,
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
                        cur_pos = rec_pos
                    else:
                        cur_pos += stride

        return results

    @classmethod
    def extract_strings(
        cls,
        data: bytes,
        candidate: TableCandidate,
        base_address: int = 0,
    ) -> List[Tuple[int, str]]:
        """
        Extracts all strings addressed by the candidate table.
        """
        fmt = f"{candidate.endian}{'I' if candidate.pointer_size == 4 else 'H'}"
        extracted: List[Tuple[int, str]] = []

        for i in range(candidate.count):
            rec_off = candidate.offset + (i * candidate.stride) + candidate.pointer_offset_in_entry
            target = struct.unpack_from(fmt, data, rec_off)[0] - base_address

            # Read null-terminated string
            end = data.find(b"\x00", target)
            if end != -1:
                s = data[target:end].decode("utf-8", "replace")
            else:
                s = data[target : target + 32].decode("utf-8", "replace")

            extracted.append((i, s))

        return extracted
