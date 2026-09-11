from typing import List, Optional, Sequence


def cumulative_offsets(
    lengths: Sequence[int],
    base_offset: int = 0,
    include_end: bool = False,
) -> List[int]:
    """
    Computes absolute start offsets from a sequence of entry lengths.
    If include_end=True, appends the terminal end offset.
    """
    offsets = [base_offset]
    for length in lengths:
        if length < 0:
            raise ValueError(f"Entry length cannot be negative: {length}")
        offsets.append(offsets[-1] + length)

    if include_end:
        return offsets
    return offsets[:-1]


def offsets_to_lengths(
    offsets: Sequence[int],
    total_size: Optional[int] = None,
) -> List[int]:
    """
    Computes entry lengths from a sequence of contiguous start offsets.
    If total_size is given, computes the length of the final entry.
    """
    if not offsets:
        return []

    lengths = []
    for i in range(len(offsets) - 1):
        delta = offsets[i + 1] - offsets[i]
        if delta < 0:
            raise ValueError(
                f"Offsets must be non-decreasing: offsets[{i}]={offsets[i]} > offsets[{i+1}]={offsets[i+1]}"
            )
        lengths.append(delta)

    if total_size is not None:
        final_len = total_size - offsets[-1]
        if final_len < 0:
            raise ValueError(
                f"Total size ({total_size}) is smaller than last offset ({offsets[-1]})"
            )
        lengths.append(final_len)

    return lengths


def delta_decode(deltas: Sequence[int], initial: int = 0) -> List[int]:
    """
    Reconstructs an absolute value series from differential deltas.
    X_0 = initial + delta_0, X_i = X_(i-1) + delta_i.
    """
    values = []
    accum = initial
    for d in deltas:
        accum += d
        values.append(accum)
    return values


def delta_encode(values: Sequence[int], initial: int = 0) -> List[int]:
    """
    Computes differential deltas from an absolute value series.
    delta_0 = X_0 - initial, delta_i = X_i - X_(i-1).
    """
    deltas = []
    prev = initial
    for v in values:
        deltas.append(v - prev)
        prev = v
    return deltas


def relative_to_absolute(rel_offsets: Sequence[int], base: int) -> List[int]:
    """Translates relative offsets to absolute offsets by adding base."""
    return [off + base for off in rel_offsets]


def absolute_to_relative(abs_offsets: Sequence[int], base: int) -> List[int]:
    """Translates absolute offsets to relative offsets by subtracting base."""
    return [off - base for off in abs_offsets]
