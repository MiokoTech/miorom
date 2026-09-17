import pytest

from miorom.compression.huffman import Huffman
from miorom.errors import CompressionError


def test_huffman_empty_data_roundtrip():
    """
    Regression test for Huffman compression and decompression of empty data (b"").
    Ensures that empty input produces valid headers that decompress back to b"".
    """
    # 8-bit Huffman empty roundtrip
    comp8 = Huffman.compress(b"", bit_depth=8)
    assert len(comp8) >= 7
    decomp8 = Huffman.decompress(comp8)
    assert decomp8 == b""

    # 4-bit Huffman empty roundtrip
    comp4 = Huffman.compress(b"", bit_depth=4)
    assert len(comp4) >= 7
    decomp4 = Huffman.decompress(comp4)
    assert decomp4 == b""


def test_huffman_legacy_empty_stream():
    """Decompressor must gracefully handle 6-byte legacy empty streams without crashing."""
    legacy_6b = bytes([0x28, 0, 0, 0, 0, 0])
    assert Huffman.decompress(legacy_6b) == b""

    # Fewer than 5 bytes is too short for a Huffman header
    with pytest.raises(CompressionError, match="Data too short"):
        Huffman.decompress(bytes([0x28, 0, 0, 0]))


@pytest.mark.parametrize("bit_depth", [4, 8])
@pytest.mark.parametrize(
    "data",
    [
        b"A",
        b"\x00",
        b"\xFF",
        b"AB",
        b"Hello, world!",
        b"Nintendo GBA/NDS Huffman Compression Test!" * 5,
        (b"X" * 100) + (b"Y" * 50) + (b"Z" * 25),
    ],
)
def test_huffman_normal_data_roundtrip(bit_depth, data):
    """Ensure standard non-empty payloads roundtrip with 100% fidelity."""
    comp = Huffman.compress(data, bit_depth=bit_depth)
    assert comp[0] in (0x24, 0x28)
    decomp = Huffman.decompress(comp)
    assert decomp == data


def test_huffman_high_entropy_depth_rejection():
    """
    Verify that pure high-entropy/random data is correctly rejected when
    the Huffman tree depth exceeds the Nintendo BIOS format constraint (0x3F).
    """
    # 256 all-different unique bytes with uniform flat frequencies
    flat_data = bytes(range(256))
    with pytest.raises(CompressionError, match="Huffman tree too deep for Nintendo format"):
        Huffman.compress(flat_data, bit_depth=8)


def test_huffman_invalid_inputs_and_errors():
    """Verify error checking for corrupted, truncated, or invalid Huffman streams."""
    with pytest.raises(CompressionError, match="Data too short"):
        Huffman.decompress(b"\x28\x00")

    with pytest.raises(CompressionError, match="Invalid Huffman type byte"):
        Huffman.decompress(b"\x10\x01\x00\x00\x00")

    with pytest.raises(CompressionError, match="bit_depth must be 4 or 8"):
        Huffman.compress(b"test", bit_depth=16)
