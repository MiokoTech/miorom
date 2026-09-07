import pytest
from miorom.compression.lz10 import LZ10
from miorom.compression.lz11 import LZ11
from miorom.compression.rle import RLE
from miorom.compression import decompress, compress


def test_lz10_roundtrip():
    original = b"Hello, world! This is a test of Nintendo LZ10 compression. Repeating string Repeating string!" * 5
    compressed = LZ10.compress(original)

    assert compressed[0] == 0x10
    assert len(compressed) < len(original)

    decompressed = LZ10.decompress(compressed)
    assert decompressed == original


def test_lz11_roundtrip():
    # Construct data with short matches, medium matches (>16), and long matches (>272)
    original = (b"A" * 300) + (b"B" * 50) + (b"Testing Nintendo DS LZ11 compression! " * 20)
    compressed = LZ11.compress(original)

    assert compressed[0] == 0x11
    assert len(compressed) < len(original)

    decompressed = LZ11.decompress(compressed)
    assert decompressed == original


def test_rle_roundtrip():
    original = (b"\x00" * 40) + b"ABCDEFG" + (b"\xFF" * 100) + b"12345"
    compressed = RLE.compress(original)

    assert compressed[0] == 0x30
    assert len(compressed) < len(original)

    decompressed = RLE.decompress(compressed)
    assert decompressed == original


def test_auto_decompress_and_compress():
    sample = b"The quick brown fox jumps over the lazy dog. The quick brown fox jumps over the lazy dog."

    # Test auto LZ10
    c_lz10 = compress(sample, "lz10")
    assert decompress(c_lz10) == sample

    # Test auto LZ11
    c_lz11 = compress(sample, "lz11")
    assert decompress(c_lz11) == sample

    # Test auto RLE
    rle_sample = b"\x00" * 50 + b"\x01" * 50
    c_rle = compress(rle_sample, "rle")
    assert decompress(c_rle) == rle_sample


def test_cli_compression_roundtrip(tmp_path):
    import subprocess
    input_file = tmp_path / "raw.bin"
    comp_file = tmp_path / "comp.bin"
    decomp_file = tmp_path / "decomp.bin"

    raw_data = b"MioROM CLI compression test! " * 50
    input_file.write_bytes(raw_data)

    # CLI compress
    res = subprocess.run(["miorom", "compress", str(input_file), "-o", str(comp_file), "-f", "lz11"], capture_output=True, text=True)
    assert res.returncode == 0
    assert comp_file.exists()
    assert comp_file.stat().st_size < len(raw_data)

    # CLI decompress
    res2 = subprocess.run(["miorom", "decompress", str(comp_file), "-o", str(decomp_file)], capture_output=True, text=True)
    assert res2.returncode == 0
    assert decomp_file.exists()
    assert decomp_file.read_bytes() == raw_data


def test_yaz0_roundtrip():
    original = b"Nintendo Yaz0 GameCube/Wii compression test! " * 30
    comp = compress(original, "yaz0")
    assert comp[:4] == b"Yaz0"
    decomp = decompress(comp)
    assert decomp == original


def test_huffman_roundtrip():
    original = b"Huffman coding test for Nintendo BIOS standard!" * 10
    comp4 = compress(original, "huffman4")
    assert comp4[0] == 0x24
    assert decompress(comp4) == original

    comp8 = compress(original, "huffman8")
    assert comp8[0] == 0x28
    assert decompress(comp8) == original
