"""
Unit tests for Nintendo GameCube / Wii RARC Archive (.arc, .rarc).
"""

import os
import tempfile
import pytest
from miorom.platforms.wii.rarc import RARCArchive, RARCEntry, rarc_hash
from miorom.errors import ParseError


def test_rarc_hash():
    assert rarc_hash(".") == ord(".")
    h = rarc_hash("ROOT")
    assert isinstance(h, int)


def test_rarc_roundtrip():
    e1 = RARCEntry(name="dialogue.txt", path="dialogue.txt", data=b"Sample dialog line from Wind Waker.")
    e2 = RARCEntry(name="layout.bin", path="layout.bin", data=b"\x00\x01\x02\x03\xFF\xFE" * 30)

    archive = RARCArchive(entries=[e1, e2])
    raw = archive.to_bytes()
    assert raw[:4] == b"RARC"
    assert RARCArchive.is_rarc(raw) is True

    reloaded = RARCArchive.from_bytes(raw)
    assert reloaded.get_file("dialogue.txt") == b"Sample dialog line from Wind Waker."
    assert reloaded.get_file("layout.bin") == b"\x00\x01\x02\x03\xFF\xFE" * 30


def test_rarc_extract_all():
    with tempfile.TemporaryDirectory() as tmpdir:
        e1 = RARCEntry(name="test.txt", path="test.txt", data=b"Content 1")
        archive = RARCArchive(entries=[e1])
        arc_path = os.path.join(tmpdir, "test.rarc")
        with open(arc_path, "wb") as f:
            f.write(archive.to_bytes())

        out_dir = os.path.join(tmpdir, "out")
        extracted = RARCArchive.extract_all(arc_path, out_dir)
        assert len(extracted) == 1
        with open(extracted[0], "rb") as f:
            assert f.read() == b"Content 1"


def test_rarc_invalid():
    with pytest.raises(ParseError):
        RARCArchive.from_bytes(b"BAD!")

    with pytest.raises(ParseError):
        RARCArchive.from_bytes(b"RARC" + b"\x00" * 10)
