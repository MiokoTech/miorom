import random

import pytest

from miorom.compression.rle import RLE
from miorom.errors import CompressionError


def test_rle_boundary_regression_130_131_262():
    """
    Regression test for off-by-one maximum run length in RLE.compress().
    Validates identical runs of length 130, 131, and 262 bytes (2x limit).
    """
    for length in (130, 131, 262):
        data = b"A" * length
        compressed = RLE.compress(data)
        decompressed = RLE.decompress(compressed)
        assert decompressed == data, f"Failed roundtrip for identical byte run of length {length}"


@pytest.mark.parametrize("length", [1, 2, 3, 4, 127, 128, 129, 130, 131, 132, 259, 260, 261, 262, 263, 390, 512])
def test_rle_exact_run_boundaries(length):
    """Test identical runs around single and multi-chunk boundary limits."""
    for byte_val in (b"\x00", b"A", b"\xFF"):
        data = byte_val * length
        compressed = RLE.compress(data)
        decompressed = RLE.decompress(compressed)
        assert decompressed == data


def test_rle_fuzz_random_and_repeated_runs():
    """
    Fuzzing test generating randomized buffers with varying run lengths,
    alternating between random noise and repeated byte sequences.
    """
    rng = random.Random(1337)

    for iteration in range(50):
        # Mix chunks of repeated bytes with random literal bytes
        buf = bytearray()
        num_segments = rng.randint(1, 15)
        for _ in range(num_segments):
            if rng.random() < 0.5:
                # Repeated run of arbitrary length (including across 130/260 boundaries)
                repeat_byte = bytes([rng.randint(0, 255)])
                repeat_len = rng.randint(1, 350)
                buf.extend(repeat_byte * repeat_len)
            else:
                # Random literal run
                lit_len = rng.randint(1, 200)
                buf.extend(bytes(rng.randint(0, 255) for _ in range(lit_len)))

        original = bytes(buf)
        compressed = RLE.compress(original)
        decompressed = RLE.decompress(compressed)
        assert decompressed == original, f"Fuzz failure at iteration {iteration} (len {len(original)})"


def test_rle_pure_random_buffers():
    """Test roundtrip on pure pseudo-random high-entropy byte buffers."""
    rng = random.Random(9999)
    for size in (10, 50, 128, 256, 1024, 4096):
        data = bytes(rng.randint(0, 255) for _ in range(size))
        compressed = RLE.compress(data)
        decompressed = RLE.decompress(compressed)
        assert decompressed == data


def test_rle_with_end_marker():
    """Test roundtrip with include_end_marker=True."""
    data = (b"X" * 131) + (b"Y" * 262) + b"LITERAL_DATA"
    compressed = RLE.compress(data, include_end_marker=True)
    decompressed = RLE.decompress(compressed)
    assert decompressed == data


def test_rle_error_handling():
    """Verify error conditions on corrupted or truncated inputs."""
    with pytest.raises(CompressionError, match="Data too short"):
        RLE.decompress(b"\x30\x01")

    with pytest.raises(CompressionError, match="Invalid RLE magic"):
        RLE.decompress(b"\x10\x01\x00\x00")
