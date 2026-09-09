"""Tests for PatchWriter transactional context manager and journal."""

import pytest

from miorom.patch import PatchWriter


def make_rom() -> bytearray:
    return bytearray(b"\x00" * 64)


def test_context_manager_commits_on_success():
    rom = make_rom()
    with PatchWriter(rom) as w:
        w.seek_to(0).write_bytes(b"HELLO")
    assert rom[:5] == b"HELLO"


def test_context_manager_rolls_back_on_exception():
    rom = bytearray(b"ORIGINAL" + b"\x00" * 56)
    with pytest.raises(RuntimeError):
        with PatchWriter(rom) as w:
            w.seek_to(0).write_bytes(b"DESTROYED")
            raise RuntimeError("oops")
    assert bytes(rom[:8]) == b"ORIGINAL"


def test_context_manager_rolls_back_buffer_growth():
    rom = bytearray(16)
    with pytest.raises(ValueError):
        with PatchWriter(rom) as w:
            w.seek_to(10).write_bytes(b"0123456789")  # grows to 20
            raise ValueError("nope")
    assert len(rom) == 16


def test_rollback_restores_buffer_identity():
    rom = make_rom()
    with pytest.raises(RuntimeError):
        with PatchWriter(rom) as w:
            w.write_bytes(b"XX")
            raise RuntimeError("fail")
    # Same object mutated in place, not replaced.
    assert isinstance(rom, bytearray)
    assert bytes(rom) == b"\x00" * 64


def test_journal_lists_writes_before_commit():
    rom = make_rom()
    w = PatchWriter(rom, staged=True)
    w.seek_to(4).write_bytes(b"AB").write_u32(0xDEADBEEF)
    journal = w.journal()
    assert len(journal) == 2
    assert journal[0]["offset"] == 4
    assert journal[0]["data"] == b"AB"
    assert journal[0]["size"] == 2
    assert journal[1]["offset"] == 6
    assert journal[1]["data"] == bytes.fromhex("efbeadde")
    # Nothing applied until commit
    assert bytes(rom[:8]) == b"\x00" * 8


def test_staged_mode_commit_applies_all_writes():
    rom = make_rom()
    with PatchWriter(rom, staged=True) as w:
        w.seek_to(0).write_bytes(b"AB")
        w.seek_to(8).write_u32(0x11223344)
    assert rom[:2] == b"AB"
    assert bytes(rom[8:12]) == bytes.fromhex("44332211")


def test_staged_mode_rollback_discards_writes():
    rom = make_rom()
    with pytest.raises(RuntimeError):
        with PatchWriter(rom, staged=True) as w:
            w.seek_to(0).write_bytes(b"AB")
            raise RuntimeError("fail")
    assert bytes(rom) == b"\x00" * 64


def test_explicit_rollback_method():
    rom = make_rom()
    w = PatchWriter(rom, staged=True)
    w.seek_to(0).write_bytes(b"Z")
    w.rollback()
    assert bytes(rom) == b"\x00" * 64
    assert len(w.journal()) == 0


def test_nested_context_manager_restores_outer_state():
    rom = make_rom()
    with PatchWriter(rom) as outer:
        outer.write_bytes(b"OUTER")
        try:
            with PatchWriter(rom) as inner:
                inner.write_bytes(b"INNER")
                raise RuntimeError("inner fail")
        except RuntimeError:
            pass
        outer.write_bytes(b"!")
    assert rom[:6] == b"OUTER!"


def test_journal_offset_endianness_fields():
    rom = make_rom()
    w = PatchWriter(rom)
    w.write_u16(0x1234, endian=">")
    rec = w.journal()[0]
    assert rec["data"] == b"\x12\x34"
