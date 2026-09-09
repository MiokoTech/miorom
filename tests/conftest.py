"""Shared test fixtures for the MioROM test suite."""
import struct
import pytest
from pathlib import Path


@pytest.fixture
def tmp_rom_data():
    """A minimal synthetic ROM buffer (8 KB of pseudorandom bytes)."""
    import os
    rng = bytearray(os.urandom(0x2000))
    return bytes(rng)


@pytest.fixture
def tmp_narc_bytes():
    """Minimal NARC archive with 3 entries for unpack/repack tests."""
    from miorom.platforms.nds.narc import NARCArchive
    return NARCArchive.pack_files([b"AAAA", b"BBBBBBBB", b"CC"])
