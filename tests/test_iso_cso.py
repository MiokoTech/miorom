import os
import zlib
import pytest
from miorom.platforms.iso.cso import CSOImage, CSO_MAGIC
from miorom.errors import ParseError, CompressionError


def test_cso_compression_and_decompression_roundtrip(tmp_path):
    block_size = 2048
    sector_0 = b"A" * block_size
    sector_1 = b"B" * block_size
    sector_2 = b"C" * block_size
    iso_data = sector_0 + sector_1 + sector_2

    cso_bytes = CSOImage.compress_iso(iso_data, block_size=block_size)
    assert len(cso_bytes) < len(iso_data)
    assert cso_bytes[:4] == CSO_MAGIC

    cso = CSOImage(cso_bytes)
    assert cso.sector_count == 3
    assert cso.sector_size == block_size
    assert cso.uncompressed_size == len(iso_data)

    assert cso.read_sector(0) == sector_0
    assert cso.read_sector(1) == sector_1
    assert cso.read_sector(2) == sector_2

    multi = cso.read_sectors(0, 2)
    assert multi == sector_0 + sector_1

    cross_chunk = cso.read_bytes(block_size - 10, 20)
    assert cross_chunk == (b"A" * 10) + (b"B" * 10)

    out_iso_path = str(tmp_path / "decompressed.iso")
    cso.decompress_to_file(out_iso_path, chunk_sectors=1)
    with open(out_iso_path, "rb") as f:
        assert f.read() == iso_data


def test_cso_raw_uncompressed_blocks():
    block_size = 2048
    random_bytes = os.urandom(block_size)
    iso_data = random_bytes

    cso_bytes = CSOImage.compress_iso(iso_data, block_size=block_size)
    cso = CSOImage(cso_bytes)

    # High bit set indicating raw uncompressed block
    assert (cso._index[0] & 0x80000000) != 0
    assert cso.read_sector(0) == random_bytes


def test_cso_file_path_io_and_context_manager(tmp_path):
    iso_file = tmp_path / "input.iso"
    cso_file = tmp_path / "output.cso"

    payload = b"X" * 4096
    iso_file.write_bytes(payload)

    CSOImage.compress_iso(str(iso_file), output_path=str(cso_file), block_size=2048)
    assert os.path.exists(cso_file)

    with CSOImage(str(cso_file)) as img:
        assert img.sector_count == 2
        assert img.read_bytes(0, 4096) == payload


def test_cso_boundary_and_error_handling():
    with pytest.raises(ParseError):
        CSOImage(b"SHORT")

    with pytest.raises(ParseError):
        CSOImage(b"BADM" + b"\x00" * 20)

    cso_bytes = CSOImage.compress_iso(b"TEST" * 512, block_size=2048)
    cso = CSOImage(cso_bytes)

    with pytest.raises(IndexError):
        cso.read_sector(99)

    assert cso.read_bytes(-1, 10) == b""
    assert cso.read_bytes(10000, 10) == b""
