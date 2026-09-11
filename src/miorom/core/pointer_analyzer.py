"""
miorom.core.pointer_analyzer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Pointer table analysis, sequence validation, monotonicity metrics,
and candidate discovery for retro console binary reverse engineering.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union
import struct

from miorom.result import MioRomResult


@dataclass
class PointerSequenceMetrics(MioRomResult):
    """
    Statistical and ordering metrics for a sequence of pointer addresses.
    """
    count: int
    min_target: int
    max_target: int
    span: int
    mean_step: float
    monotonic_ratio: float
    strictly_monotonic_ratio: float
    duplicate_ratio: float
    confidence: float


@dataclass
class PointerTableCandidate(MioRomResult):
    """
    Candidate pointer table detected within binary data.
    """
    table_offset: int
    entry_count: int
    stride: int
    endian: str
    base_offset: int
    min_target: int
    max_target: int
    confidence: float
    is_monotonic: bool
    targets: List[int]

    def to_bytes(self) -> bytes:
        """Serialize candidate pointer targets back to binary data."""
        return pack_pointers(self.targets, stride=self.stride, endian=self.endian)

    def remap(
        self,
        offset_map: Optional[Dict[int, int]] = None,
        default_delta: int = 0,
    ) -> "PointerTableCandidate":
        """Return a new candidate with remapped targets."""
        new_targets = remap_pointers(self.targets, offset_map=offset_map, default_delta=default_delta)
        min_t = min(new_targets) if new_targets else 0
        max_t = max(new_targets) if new_targets else 0
        metrics = analyze_pointer_sequence(new_targets, min_target=min_t, max_target=max_t)
        return PointerTableCandidate(
            table_offset=self.table_offset,
            entry_count=len(new_targets),
            stride=self.stride,
            endian=self.endian,
            base_offset=self.base_offset,
            min_target=min_t,
            max_target=max_t,
            confidence=metrics.confidence,
            is_monotonic=metrics.monotonic_ratio == 1.0,
            targets=new_targets,
        )


def unpack_pointer(
    data: bytes,
    offset: int = 0,
    stride: int = 2,
    endian: str = "<",
) -> int:
    """
    Unpack a single pointer word from binary data.
    Supports 16-bit (2-byte), 24-bit (3-byte), and 32-bit (4-byte) integers.
    """
    if endian not in ("<", ">"):
        raise ValueError(f"Invalid endian {endian!r}, must be '<' or '>'")
    if offset < 0 or offset + stride > len(data):
        raise ValueError(
            f"Offset {offset} with stride {stride} exceeds data length {len(data)}"
        )

    if stride == 2:
        return struct.unpack_from(f"{endian}H", data, offset)[0]
    elif stride == 3:
        raw = data[offset : offset + 3]
        return int.from_bytes(raw, "little" if endian == "<" else "big")
    elif stride == 4:
        return struct.unpack_from(f"{endian}I", data, offset)[0]
    else:
        raise ValueError(f"Unsupported pointer stride {stride}, must be 2, 3, or 4")


def pack_pointer(
    target: int,
    stride: int = 2,
    endian: str = "<",
) -> bytes:
    """
    Pack a single pointer word into binary bytes.
    Supports 16-bit (2-byte), 24-bit (3-byte), and 32-bit (4-byte) integers.
    """
    if endian not in ("<", ">"):
        raise ValueError(f"Invalid endian {endian!r}, must be '<' or '>'")
    if stride not in (2, 3, 4):
        raise ValueError(f"Unsupported pointer stride {stride}, must be 2, 3, or 4")

    max_val = (1 << (8 * stride)) - 1
    if target < 0 or target > max_val:
        raise ValueError(
            f"Target {target:#x} exceeds range [0, {max_val:#x}] for stride {stride}"
        )

    if stride == 2:
        return struct.pack(f"{endian}H", target)
    elif stride == 3:
        return target.to_bytes(3, "little" if endian == "<" else "big")
    else:
        return struct.pack(f"{endian}I", target)


def unpack_pointers(
    data: bytes,
    offset: int = 0,
    count: int = -1,
    stride: int = 2,
    endian: str = "<",
) -> List[int]:
    """
    Unpack a sequence of pointers from binary data.
    If count is -1, unpacks until the end of data.
    """
    if offset < 0 or offset > len(data):
        raise ValueError(f"Offset {offset} out of bounds for data of length {len(data)}")
    if stride not in (2, 3, 4):
        raise ValueError(f"Unsupported pointer stride {stride}, must be 2, 3, or 4")

    available = len(data) - offset
    max_possible = available // stride

    if count < 0:
        count = max_possible
    elif count > max_possible:
        raise ValueError(
            f"Requested {count} pointers ({count * stride} bytes), "
            f"but only {available} bytes available"
        )

    result: List[int] = []
    current = offset
    for _ in range(count):
        val = unpack_pointer(data, current, stride=stride, endian=endian)
        result.append(val)
        current += stride

    return result


def pack_pointers(
    targets: Sequence[int],
    stride: int = 2,
    endian: str = "<",
) -> bytes:
    """
    Pack a sequence of pointer addresses into contiguous binary bytes.
    """
    chunks = [pack_pointer(t, stride=stride, endian=endian) for t in targets]
    return b"".join(chunks)


def verify_stride_monotonicity(
    targets: Sequence[int],
    allow_duplicates: bool = True,
) -> bool:
    """
    Check whether pointer targets form a monotonically non-decreasing sequence.
    """
    if len(targets) <= 1:
        return True

    if allow_duplicates:
        return all(b >= a for a, b in zip(targets[:-1], targets[1:]))
    return all(b > a for a, b in zip(targets[:-1], targets[1:]))


def calculate_monotonicity_ratio(
    targets: Sequence[int],
    strict: bool = False,
) -> float:
    """
    Calculate ratio of adjacent pairs that follow monotonic order.
    """
    if len(targets) <= 1:
        return 1.0

    pairs = len(targets) - 1
    if strict:
        valid = sum(1 for a, b in zip(targets[:-1], targets[1:]) if b > a)
    else:
        valid = sum(1 for a, b in zip(targets[:-1], targets[1:]) if b >= a)

    return valid / pairs


def analyze_pointer_sequence(
    targets: Sequence[int],
    min_target: Optional[int] = None,
    max_target: Optional[int] = None,
) -> PointerSequenceMetrics:
    """
    Compute comprehensive metrics and statistical confidence for a pointer sequence.
    """
    count = len(targets)
    if count == 0:
        return PointerSequenceMetrics(
            count=0,
            min_target=0,
            max_target=0,
            span=0,
            mean_step=0.0,
            monotonic_ratio=0.0,
            strictly_monotonic_ratio=0.0,
            duplicate_ratio=0.0,
            confidence=0.0,
        )

    min_t = min(targets)
    max_t = max(targets)
    span = max_t - min_t

    if count > 1:
        deltas = [b - a for a, b in zip(targets[:-1], targets[1:])]
        mean_step = sum(deltas) / len(deltas)
        mono_ratio = calculate_monotonicity_ratio(targets, strict=False)
        strict_mono_ratio = calculate_monotonicity_ratio(targets, strict=True)
    else:
        mean_step = 0.0
        mono_ratio = 1.0
        strict_mono_ratio = 1.0

    unique_count = len(set(targets))
    duplicate_ratio = 1.0 - (unique_count / count)

    if min_target is not None and max_target is not None:
        valid_count = sum(1 for t in targets if min_target <= t <= max_target)
        valid_ratio = valid_count / count
    elif min_target is not None:
        valid_count = sum(1 for t in targets if t >= min_target)
        valid_ratio = valid_count / count
    elif max_target is not None:
        valid_count = sum(1 for t in targets if t <= max_target)
        valid_ratio = valid_count / count
    else:
        valid_ratio = 1.0

    if count < 2 or unique_count <= 1 or valid_ratio == 0.0:
        confidence = 0.0
    else:
        valid_component = valid_ratio * 0.35
        monotonic_component = mono_ratio * 0.35
        diversity_ratio = unique_count / count
        diversity_component = min(0.15, diversity_ratio * 0.15)
        length_component = min(0.15, (count / 16.0) * 0.15)
        raw_score = valid_component + monotonic_component + diversity_component + length_component
        confidence = round(max(0.0, min(1.0, raw_score)), 4)

    return PointerSequenceMetrics(
        count=count,
        min_target=min_t,
        max_target=max_t,
        span=span,
        mean_step=round(mean_step, 4),
        monotonic_ratio=round(mono_ratio, 4),
        strictly_monotonic_ratio=round(strict_mono_ratio, 4),
        duplicate_ratio=round(duplicate_ratio, 4),
        confidence=confidence,
    )


def remap_pointers(
    targets: Sequence[int],
    offset_map: Optional[Dict[int, int]] = None,
    default_delta: int = 0,
) -> List[int]:
    """
    Remap pointer targets according to a lookup dictionary or uniform delta offset.
    """
    mapping = offset_map or {}
    return [mapping.get(t, t + default_delta) for t in targets]


def find_pointer_tables(
    data: bytes,
    min_target: int,
    max_target: int,
    strides: Union[int, Sequence[int]] = (2, 3, 4),
    endian: Union[str, Sequence[str]] = ("<", ">"),
    min_entries: int = 4,
    alignment: int = 1,
    base_offset: int = 0,
    min_confidence: float = 0.5,
) -> List[PointerTableCandidate]:
    """
    Scan binary data to discover candidate pointer tables pointing within bounds.
    """
    if isinstance(strides, int):
        active_strides = (strides,)
    else:
        active_strides = tuple(strides)

    if isinstance(endian, str):
        active_endians = (endian,)
    else:
        active_endians = tuple(endian)

    candidates: List[PointerTableCandidate] = []
    data_len = len(data)

    for st in active_strides:
        for end in active_endians:
            phase_step = max(1, alignment)
            for phase in range(0, st, phase_step):
                current_start = phase
                current_targets: List[int] = []

                pos = phase
                while pos + st <= data_len:
                    val = unpack_pointer(data, pos, stride=st, endian=end)
                    effective = val + base_offset
                    if min_target <= effective <= max_target:
                        if not current_targets:
                            current_start = pos
                        current_targets.append(effective)
                    else:
                        if len(current_targets) >= min_entries:
                            _evaluate_candidate(
                                candidates=candidates,
                                table_offset=current_start,
                                stride=st,
                                endian=end,
                                base_offset=base_offset,
                                targets=current_targets,
                                min_target_bound=min_target,
                                max_target_bound=max_target,
                                min_confidence=min_confidence,
                            )
                        current_targets = []
                    pos += st

                if len(current_targets) >= min_entries:
                    _evaluate_candidate(
                        candidates=candidates,
                        table_offset=current_start,
                        stride=st,
                        endian=end,
                        base_offset=base_offset,
                        targets=current_targets,
                        min_target_bound=min_target,
                        max_target_bound=max_target,
                        min_confidence=min_confidence,
                    )

    deduped = _filter_overlapping_candidates(candidates)
    deduped.sort(key=lambda c: (c.table_offset, -c.confidence, -c.entry_count))
    return deduped


def _evaluate_candidate(
    candidates: List[PointerTableCandidate],
    table_offset: int,
    stride: int,
    endian: str,
    base_offset: int,
    targets: List[int],
    min_target_bound: int,
    max_target_bound: int,
    min_confidence: float,
) -> None:
    """Evaluate and append a qualified pointer table candidate."""
    metrics = analyze_pointer_sequence(
        targets,
        min_target=min_target_bound,
        max_target=max_target_bound,
    )
    if metrics.confidence >= min_confidence:
        candidate = PointerTableCandidate(
            table_offset=table_offset,
            entry_count=len(targets),
            stride=stride,
            endian=endian,
            base_offset=base_offset,
            min_target=min(targets),
            max_target=max(targets),
            confidence=metrics.confidence,
            is_monotonic=metrics.monotonic_ratio == 1.0,
            targets=list(targets),
        )
        candidates.append(candidate)


def _filter_overlapping_candidates(
    candidates: List[PointerTableCandidate],
) -> List[PointerTableCandidate]:
    """Filter duplicate or inferior candidate detections at the same offset."""
    by_key: Dict[Tuple[int, int, str], PointerTableCandidate] = {}
    for c in candidates:
        key = (c.table_offset, c.stride, c.endian)
        if key not in by_key:
            by_key[key] = c
        else:
            existing = by_key[key]
            if (c.confidence, c.entry_count) > (existing.confidence, existing.entry_count):
                by_key[key] = c
    return list(by_key.values())
