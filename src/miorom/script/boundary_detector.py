"""
miorom.script.boundary_detector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Statistical script delimiter, string terminator, and embedded control code
discovery engine cross-referencing pointer table target sequences.
"""

from collections import Counter
from dataclasses import dataclass, field
import math
from typing import Dict, List, Optional, Sequence, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class DelimiterCandidate(MioRomResult):
    """
    Candidate string delimiter or terminator discovered at target boundaries.
    """
    byte_sequence: bytes
    hex_representation: str
    count: int
    ratio: float
    confidence: float


@dataclass
class ControlCodeCandidate(MioRomResult):
    """
    Candidate control code or script command embedded within dialogue text.
    """
    opcode: int
    hex_representation: str
    frequency: int
    estimated_arg_length: int
    is_trailing: bool
    confidence: float


@dataclass
class ScriptBoundaryReport(MioRomResult):
    """
    Summary report of dialogue script boundaries, terminators, and control codes.
    """
    total_strings: int
    min_length: int
    max_length: int
    average_length: float
    alignment: int
    primary_terminator: Optional[bytes]
    delimiter_candidates: List[DelimiterCandidate] = field(default_factory=list)
    control_code_candidates: List[ControlCodeCandidate] = field(default_factory=list)


def detect_delimiters(
    data: bytes,
    targets: Sequence[int],
    max_delimiter_len: int = 2,
) -> List[DelimiterCandidate]:
    """
    Analyze trailing bytes immediately preceding pointer targets to discover terminators.
    """
    sorted_targets = sorted(set(targets))
    if len(sorted_targets) < 2:
        return []

    data_len = len(data)
    candidates: List[DelimiterCandidate] = []

    # Single-byte delimiter detection
    single_counts: Counter[int] = Counter()
    tested_boundaries = 0

    for i in range(1, len(sorted_targets)):
        next_target = sorted_targets[i]
        prev_target = sorted_targets[i - 1]
        if prev_target < next_target <= data_len and next_target > 0:
            byte_val = data[next_target - 1]
            single_counts[byte_val] += 1
            tested_boundaries += 1

    if tested_boundaries > 0:
        for val, count in single_counts.most_common():
            ratio = count / tested_boundaries
            seq = bytes([val])
            # Delimiter consistency check
            conf = min(1.0, ratio * (1.0 if count >= 4 else count / 4.0))
            candidates.append(
                DelimiterCandidate(
                    byte_sequence=seq,
                    hex_representation=f"{val:02X}",
                    count=count,
                    ratio=round(ratio, 4),
                    confidence=round(conf, 4),
                )
            )

    # Multi-byte delimiter detection if requested
    if max_delimiter_len >= 2 and tested_boundaries > 0:
        pair_counts: Counter[bytes] = Counter()
        for i in range(1, len(sorted_targets)):
            next_target = sorted_targets[i]
            prev_target = sorted_targets[i - 1]
            if next_target >= 2 and (next_target - 2) >= prev_target:
                pair = data[next_target - 2 : next_target]
                pair_counts[pair] += 1

        for pair, count in pair_counts.most_common():
            pair_ratio = count / tested_boundaries
            # Filter multi-byte candidates
            if pair_ratio >= 0.4 and count >= 3:
                conf = min(1.0, pair_ratio * 0.95)
                candidates.append(
                    DelimiterCandidate(
                        byte_sequence=pair,
                        hex_representation=" ".join(f"{b:02X}" for b in pair),
                        count=count,
                        ratio=round(pair_ratio, 4),
                        confidence=round(conf, 4),
                    )
                )

    candidates.sort(key=lambda c: (-c.confidence, -c.count))
    return candidates


def detect_control_codes(
    data: bytes,
    targets: Sequence[int],
    terminator: Optional[bytes] = None,
    printable_range: Tuple[int, int] = (0x20, 0x7E),
) -> List[ControlCodeCandidate]:
    """
    Discover candidate control codes embedded within dialogue text streams.
    """
    sorted_targets = sorted(set(targets))
    if not sorted_targets:
        return []

    data_len = len(data)
    min_print, max_print = printable_range
    term_set = set(terminator) if terminator else {0x00}

    # Collect slices between targets
    slices: List[bytes] = []
    for i in range(len(sorted_targets)):
        start = sorted_targets[i]
        if i + 1 < len(sorted_targets):
            end = sorted_targets[i + 1]
        else:
            end = min(data_len, start + 256)
        if start < end <= data_len:
            slices.append(data[start:end])

    if not slices:
        return []

    non_printable_counts: Counter[int] = Counter()
    trailing_counts: Counter[int] = Counter()
    total_strings = len(slices)

    for s in slices:
        if not s:
            continue
        cleaned = s
        if terminator and cleaned.endswith(terminator):
            cleaned = cleaned[: -len(terminator)]
        elif cleaned and cleaned[-1] in term_set:
            cleaned = cleaned[:-1]

        for idx, b in enumerate(cleaned):
            if b < min_print or b > max_print:
                if b not in term_set:
                    non_printable_counts[b] += 1
                    if idx == len(cleaned) - 1:
                        trailing_counts[b] += 1

    candidates: List[ControlCodeCandidate] = []
    for opcode, freq in non_printable_counts.most_common():
        if freq < 2:
            continue

        trailing_ratio = trailing_counts[opcode] / freq
        is_trailing = trailing_ratio >= 0.7

        # Estimate argument length
        arg_len = _estimate_argument_length(slices, opcode, min_print, max_print, term_set)

        # Calculate confidence
        freq_factor = min(1.0, freq / float(total_strings))
        conf = 0.5 + 0.4 * freq_factor
        if is_trailing:
            conf += 0.05
        conf = min(0.99, round(conf, 4))

        candidates.append(
            ControlCodeCandidate(
                opcode=opcode,
                hex_representation=f"{opcode:02X}",
                frequency=freq,
                estimated_arg_length=arg_len,
                is_trailing=is_trailing,
                confidence=conf,
            )
        )

    candidates.sort(key=lambda c: (-c.confidence, -c.frequency))
    return candidates


def _estimate_argument_length(
    slices: Sequence[bytes],
    opcode: int,
    min_print: int,
    max_print: int,
    term_set: set,
) -> int:
    """Heuristically estimate argument count (0, 1, 2, or 3) for a control code."""
    arg_distances: List[int] = []

    for s in slices:
        idx = 0
        while idx < len(s):
            if s[idx] == opcode:
                # Look ahead until the next character or terminator
                look = idx + 1
                dist = 0
                while look < len(s) and dist < 4:
                    nxt = s[look]
                    if min_print <= nxt <= max_print or nxt in term_set:
                        break
                    dist += 1
                    look += 1
                arg_distances.append(dist)
                idx = look
            else:
                idx += 1

    if not arg_distances:
        return 0

    mode_dist = Counter(arg_distances).most_common(1)[0][0]
    return min(3, mode_dist)


def analyze_script_boundaries(
    data: bytes,
    targets: Sequence[int],
    primary_terminator: Optional[bytes] = None,
    printable_range: Tuple[int, int] = (0x20, 0x7E),
) -> ScriptBoundaryReport:
    """
    Generate a comprehensive analysis of string boundaries, terminators, and control codes.
    """
    sorted_targets = sorted(set(targets))
    total_strings = len(sorted_targets)
    if total_strings == 0:
        return ScriptBoundaryReport(
            total_strings=0,
            min_length=0,
            max_length=0,
            average_length=0.0,
            alignment=1,
            primary_terminator=None,
        )

    # Detect delimiter candidates
    delimiters = detect_delimiters(data, sorted_targets)
    best_term = primary_terminator
    if best_term is None and delimiters:
        best_term = delimiters[0].byte_sequence

    # Detect control codes
    control_codes = detect_control_codes(
        data=data,
        targets=sorted_targets,
        terminator=best_term,
        printable_range=printable_range,
    )

    # Calculate length metrics and alignment
    lengths: List[int] = []
    data_len = len(data)
    for i in range(total_strings):
        start = sorted_targets[i]
        if i + 1 < total_strings:
            end = sorted_targets[i + 1]
        else:
            end = min(data_len, start + 256)
        lengths.append(max(0, end - start))

    min_len = min(lengths) if lengths else 0
    max_len = max(lengths) if lengths else 0
    avg_len = sum(lengths) / total_strings if total_strings else 0.0

    # Determine alignment based on GCD of target offsets
    offsets_diff = [sorted_targets[i] - sorted_targets[0] for i in range(total_strings)]
    common_gcd = 1
    if offsets_diff:
        common_gcd = offsets_diff[0]
        for d in offsets_diff[1:]:
            common_gcd = math.gcd(common_gcd, d)
    alignment = common_gcd if common_gcd in (1, 2, 4, 8) else 1

    return ScriptBoundaryReport(
        total_strings=total_strings,
        min_length=min_len,
        max_length=max_len,
        average_length=round(avg_len, 2),
        alignment=alignment,
        primary_terminator=best_term,
        delimiter_candidates=delimiters,
        control_code_candidates=control_codes,
    )


def slice_script_entries(
    data: bytes,
    targets: Sequence[int],
    terminator: Optional[bytes] = None,
    strip_terminator: bool = False,
) -> List[bytes]:
    """
    Extract discrete binary string entries between pointer targets according to terminator rules.
    """
    sorted_targets = list(targets)
    total = len(sorted_targets)
    if total == 0:
        return []

    data_len = len(data)
    entries: List[bytes] = []

    for i in range(total):
        start = sorted_targets[i]
        if i + 1 < total:
            limit = sorted_targets[i + 1]
        else:
            limit = data_len

        chunk = data[start:limit]
        if terminator and terminator in chunk:
            idx = chunk.index(terminator)
            if strip_terminator:
                extracted = chunk[:idx]
            else:
                extracted = chunk[: idx + len(terminator)]
        else:
            extracted = chunk

        entries.append(extracted)

    return entries
