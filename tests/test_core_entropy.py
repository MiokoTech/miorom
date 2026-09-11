import math
import os
import pytest
from miorom.core.entropy import (
    calculate_entropy,
    byte_frequency,
    sliding_entropy_scan,
    chi_squared_test,
    find_entropy_regions,
)


def test_calculate_entropy_basics():
    # Empty data
    assert calculate_entropy(b"") == 0.0

    # Constant byte (zero entropy)
    assert calculate_entropy(b"\x00" * 100) == 0.0
    assert calculate_entropy(b"\xFF" * 100) == 0.0

    # 2 equally likely bytes (entropy = 1.0 bit/byte)
    half_half = b"\x00\x01" * 50
    assert math.isclose(calculate_entropy(half_half), 1.0, rel_tol=1e-5)

    # All 256 bytes once (entropy = 8.0 bits/byte)
    all_bytes = bytes(range(256))
    assert math.isclose(calculate_entropy(all_bytes), 8.0, rel_tol=1e-5)


def test_byte_frequency():
    data = b"AABBC"
    freq = byte_frequency(data)
    assert freq[ord("A")] == 2
    assert freq[ord("B")] == 2
    assert freq[ord("C")] == 1


def test_sliding_entropy_and_regions():
    # Construct buffer: 1000 zero bytes, 1024 high-entropy bytes, 1000 zero bytes
    zeros = b"\x00" * 1000
    random_block = bytes(range(256)) * 4  # 1024 bytes, 8.0 entropy
    data = zeros + random_block + zeros

    scan = sliding_entropy_scan(data, window_size=512, step=128)
    assert len(scan) > 0

    regions = find_entropy_regions(data, threshold=7.0, window_size=512, step=128)
    assert len(regions) == 1
    start, end, avg_ent = regions[0]
    # Random block starts at 1000 and ends at 2024
    assert 800 <= start <= 1150
    assert avg_ent > 7.0


def test_chi_squared():
    # Highly non-uniform data has huge chi-squared
    zeros = b"\x00" * 1000
    chi_zeros = chi_squared_test(zeros)
    assert chi_zeros > 10000.0

    # Perfectly uniform data has chi-squared = 0.0
    uniform = bytes(range(256)) * 10
    chi_uniform = chi_squared_test(uniform)
    assert math.isclose(chi_uniform, 0.0, abs_tol=1e-5)
