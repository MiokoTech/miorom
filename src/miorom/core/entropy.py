import math
from collections import Counter
from typing import Dict, List, Tuple, Union


def calculate_entropy(data: Union[bytes, bytearray, memoryview]) -> float:
    """
    Calculates the Shannon entropy of data in bits per byte (0.0 to 8.0).
    A value near 0.0 indicates uniform repetition/padding; near 8.0 indicates compression or encryption.
    """
    total = len(data)
    if total == 0:
        return 0.0

    counts = Counter(data)
    entropy = 0.0
    for count in counts.values():
        p = count / total
        entropy -= p * math.log2(p)

    return entropy


def byte_frequency(data: Union[bytes, bytearray, memoryview]) -> Dict[int, int]:
    """Returns the byte occurrence frequency histogram for the data."""
    return dict(Counter(data))


def sliding_entropy_scan(
    data: Union[bytes, bytearray, memoryview],
    window_size: int = 1024,
    step: int = 256,
) -> List[Tuple[int, float]]:
    """
    Computes Shannon entropy in sliding windows across data.
    Returns a list of (offset, entropy) tuples.
    """
    if window_size <= 0:
        raise ValueError(f"window_size must be positive, got {window_size}")
    if step <= 0:
        raise ValueError(f"step must be positive, got {step}")

    total = len(data)
    results: List[Tuple[int, float]] = []

    for offset in range(0, total, step):
        chunk = data[offset : min(offset + window_size, total)]
        if len(chunk) < min(64, window_size):
            break
        ent = calculate_entropy(chunk)
        results.append((offset, ent))

    return results


def chi_squared_test(data: Union[bytes, bytearray, memoryview]) -> float:
    """
    Calculates the Chi-squared statistic of byte values against a uniform distribution.
    A chi-squared value close to 255 indicates high randomness (encryption/high compression).
    """
    total = len(data)
    if total == 0:
        return 0.0

    counts = Counter(data)
    expected = total / 256.0
    chi_sq = 0.0

    for byte_val in range(256):
        observed = counts.get(byte_val, 0)
        chi_sq += ((observed - expected) ** 2) / expected

    return chi_sq


def find_entropy_regions(
    data: Union[bytes, bytearray, memoryview],
    threshold: float = 7.2,
    window_size: int = 1024,
    step: int = 256,
) -> List[Tuple[int, int, float]]:
    """
    Detects contiguous memory regions with Shannon entropy at or above threshold.
    Useful for discovering embedded compressed or encrypted streams.
    Returns list of (start_offset, end_offset, average_entropy).
    """
    scan = sliding_entropy_scan(data, window_size=window_size, step=step)
    regions: List[Tuple[int, int, float]] = []

    in_region = False
    region_start = 0
    region_entropies: List[float] = []

    for offset, ent in scan:
        if ent >= threshold:
            if not in_region:
                in_region = True
                region_start = offset
                region_entropies = [ent]
            else:
                region_entropies.append(ent)
        else:
            if in_region:
                avg_ent = sum(region_entropies) / len(region_entropies)
                region_end = offset + window_size
                regions.append((region_start, min(region_end, len(data)), avg_ent))
                in_region = False
                region_entropies = []

    if in_region and region_entropies:
        avg_ent = sum(region_entropies) / len(region_entropies)
        regions.append((region_start, len(data), avg_ent))

    return regions
