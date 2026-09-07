import pytest
from miorom.compression import (
    LZSSConfig,
    decompress_lzss,
    compress_lzss,
    HeuristicLZSolver,
)


def test_lzss_roundtrip_default():
    cfg = LZSSConfig()
    original = b"The quick brown fox jumps over the lazy dog. Repetition: The quick brown fox jumps over the lazy dog!" * 4

    compressed = compress_lzss(original, cfg)
    assert len(compressed) < len(original)

    decompressed = decompress_lzss(compressed, cfg)
    assert decompressed == original


def test_lzss_roundtrip_custom_variations():
    # Test LSB-first, literal_bit=0, layout="dist_low", bias=2
    cfg = LZSSConfig(
        flag_msb_first=False,
        flag_literal_bit=0,
        layout="dist_low",
        length_bias=2,
    )
    original = b"ABABABABABABABABABABABABABABABABABABABABABABABABABABABABABAB" * 5

    compressed = compress_lzss(original, cfg)
    assert len(compressed) < len(original)

    decompressed = decompress_lzss(compressed, cfg)
    assert decompressed == original


def test_heuristic_lz_solver():
    # Compress secret dialogue with a specific non-standard configuration
    target_cfg = LZSSConfig(
        flag_msb_first=True,
        flag_literal_bit=1,
        layout="dist_high",
        length_bias=3,
    )
    secret_text = b"HERO: We must venture into the ancient forest and find the crystal of light! " * 8
    blob = compress_lzss(secret_text, target_cfg)

    # Solve unknown blob
    res = HeuristicLZSolver.solve(blob, expected_prefix=b"HERO:")
    assert res is not None
    solved_cfg, decomp = res

    assert decomp == secret_text
    assert solved_cfg.flag_msb_first == target_cfg.flag_msb_first
    assert solved_cfg.flag_literal_bit == target_cfg.flag_literal_bit
    assert solved_cfg.layout == target_cfg.layout
