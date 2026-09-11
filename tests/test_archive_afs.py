import pytest
from miorom.archive.afs import AFSArchive, AFSEntry
from miorom.errors import ParseError


def test_afs_roundtrip_with_toc():
    e1 = AFSEntry(name="title.adx", data=b"RIFF...ADX_STREAM_DATA_12345", year=2001, month=6, day=23)
    e2 = AFSEntry(name="stage01.bin", data=b"\x00\x01\x02\x03" * 256, year=2001, month=6, day=24)
    e3 = AFSEntry(name="msg.txt", data="Selamat datang di MioROM!".encode("utf-8"))

    afs = AFSArchive(entries=[e1, e2, e3], has_toc=True)
    assert len(afs) == 3
    assert afs.filenames == ["title.adx", "stage01.bin", "msg.txt"]

    raw = afs.to_bytes(sector_align=True)
    assert raw[:4] == b"AFS\x00"
    assert len(raw) % 2048 == 0  # Aligned to 0x800 sectors

    reloaded = AFSArchive.from_bytes(raw)
    assert len(reloaded) == 3
    assert reloaded.filenames == ["title.adx", "stage01.bin", "msg.txt"]
    assert reloaded.get_file("title.adx") == b"RIFF...ADX_STREAM_DATA_12345"
    assert reloaded.get_file(1) == b"\x00\x01\x02\x03" * 256
    assert reloaded.get_file("msg.txt") == "Selamat datang di MioROM!".encode("utf-8")
    assert reloaded.entries[0].year == 2001
    assert reloaded.entries[0].month == 6


def test_afs_without_toc():
    e1 = AFSEntry(name="raw0.bin", data=b"RAW_DATA_ZERO")
    e2 = AFSEntry(name="raw1.bin", data=b"RAW_DATA_ONE")

    afs = AFSArchive(entries=[e1, e2], has_toc=False)
    raw = afs.to_bytes(sector_align=False)
    assert raw[:4] == b"AFS\x00"

    reloaded = AFSArchive.from_bytes(raw)
    assert len(reloaded) == 2
    assert reloaded.entries[0].data == b"RAW_DATA_ZERO"
    assert reloaded.entries[1].data == b"RAW_DATA_ONE"


def test_afs_extract_all(tmp_path):
    e1 = AFSEntry(name="sub/file1.bin", data=b"DATA_FILE_1")
    e2 = AFSEntry(name="file2.bin", data=b"DATA_FILE_2")

    afs = AFSArchive(entries=[e1, e2])
    out_dir = str(tmp_path / "extracted_afs")
    extracted = afs.extract_all(out_dir)

    assert len(extracted) == 2
    with open(tmp_path / "extracted_afs" / "sub" / "file1.bin", "rb") as f:
        assert f.read() == b"DATA_FILE_1"
    with open(tmp_path / "extracted_afs" / "file2.bin", "rb") as f:
        assert f.read() == b"DATA_FILE_2"


def test_afs_invalid_data():
    with pytest.raises(ParseError):
        AFSArchive.from_bytes(b"INVALID")
