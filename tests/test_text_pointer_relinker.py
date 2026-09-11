"""
Tests for miorom.text.pointer_relinker.
"""

import struct
import pytest

from miorom.text.pointer_relinker import PointerRecord, RelinkReport, PointerRelinker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_rom(size: int = 0x8000, fill: int = 0xFF) -> bytearray:
    return bytearray([fill] * size)


def embed_le32(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into('<I', buf, offset, value)


def embed_be32(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into('>I', buf, offset, value)


# ---------------------------------------------------------------------------
# read_pointer / write_pointer endian support
# ---------------------------------------------------------------------------

class TestEndianPointers:
    def test_read_little_endian_32(self):
        buf = bytearray(8)
        struct.pack_into('<I', buf, 0, 0x12345678)
        rl = PointerRelinker(pointer_size=4, endian='little')
        assert rl.read_pointer(buf, 0) == 0x12345678

    def test_read_big_endian_32(self):
        buf = bytearray(8)
        struct.pack_into('>I', buf, 0, 0x12345678)
        rl = PointerRelinker(pointer_size=4, endian='big')
        assert rl.read_pointer(buf, 0) == 0x12345678

    def test_write_little_endian_32(self):
        buf = bytearray(8)
        rl = PointerRelinker(pointer_size=4, endian='little')
        rl.write_pointer(buf, 0, 0xDEADBEEF)
        assert struct.unpack_from('<I', buf, 0)[0] == 0xDEADBEEF

    def test_write_big_endian_32(self):
        buf = bytearray(8)
        rl = PointerRelinker(pointer_size=4, endian='big')
        rl.write_pointer(buf, 0, 0xDEADBEEF)
        assert struct.unpack_from('>I', buf, 0)[0] == 0xDEADBEEF

    def test_read_write_16_little(self):
        buf = bytearray(4)
        rl = PointerRelinker(pointer_size=2, endian='little')
        rl.write_pointer(buf, 0, 0xABCD)
        assert rl.read_pointer(buf, 0) == 0xABCD

    def test_read_write_16_big(self):
        buf = bytearray(4)
        rl = PointerRelinker(pointer_size=2, endian='big')
        rl.write_pointer(buf, 0, 0xABCD)
        assert rl.read_pointer(buf, 0) == 0xABCD

    def test_read_write_24_little(self):
        buf = bytearray(4)
        rl = PointerRelinker(pointer_size=3, endian='little')
        rl.write_pointer(buf, 0, 0x123456)
        assert rl.read_pointer(buf, 0) == 0x123456

    def test_read_write_24_big(self):
        buf = bytearray(4)
        rl = PointerRelinker(pointer_size=3, endian='big')
        rl.write_pointer(buf, 0, 0x123456)
        assert rl.read_pointer(buf, 0) == 0x123456

    def test_invalid_pointer_size(self):
        with pytest.raises(ValueError):
            PointerRelinker(pointer_size=5)

    def test_invalid_endian(self):
        with pytest.raises(ValueError):
            PointerRelinker(endian='middle')


# ---------------------------------------------------------------------------
# scan_pointer_table
# ---------------------------------------------------------------------------

class TestScanPointerTable:
    def test_reads_correct_absolute_pointers(self):
        rom = bytearray(0x1000)
        targets = [0x0100, 0x0200, 0x0300]
        for i, addr in enumerate(targets):
            embed_le32(rom, i * 4, addr)
        rl = PointerRelinker(pointer_size=4, endian='little', base_address=0)
        records = rl.scan_pointer_table(rom, table_offset=0, entry_count=3)
        assert len(records) == 3
        for i, rec in enumerate(records):
            assert rec.pointer_offset == i * 4
            assert rec.target_offset == targets[i]
            assert rec.pointer_type == 'absolute'

    def test_reads_with_base_address(self):
        rom = bytearray(0x1000)
        base = 0x8000000
        target_addr = base + 0x200
        embed_le32(rom, 0, target_addr)
        rl = PointerRelinker(pointer_size=4, endian='little', base_address=base)
        records = rl.scan_pointer_table(rom, table_offset=0, entry_count=1)
        assert records[0].target_offset == 0x200

    def test_big_endian_scan(self):
        rom = bytearray(0x1000)
        embed_be32(rom, 0, 0x0500)
        rl = PointerRelinker(pointer_size=4, endian='big', base_address=0)
        records = rl.scan_pointer_table(rom, table_offset=0, entry_count=1)
        assert records[0].target_offset == 0x0500

    def test_pointer_type_stored_in_record(self):
        rom = bytearray(0x1000)
        rl = PointerRelinker(pointer_size=4, endian='little')
        records = rl.scan_pointer_table(rom, 0, 2, pointer_type='relative')
        assert all(r.pointer_type == 'relative' for r in records)

    def test_empty_table(self):
        rom = bytearray(0x100)
        rl = PointerRelinker()
        assert rl.scan_pointer_table(rom, 0, 0) == []


# ---------------------------------------------------------------------------
# find_free_space
# ---------------------------------------------------------------------------

class TestFindFreeSpace:
    def test_finds_run_at_start(self):
        rom = bytearray([0xFF] * 16)
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 16) == 0

    def test_finds_run_after_data(self):
        rom = bytearray([0x00] * 8 + [0xFF] * 16)
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 10) == 8

    def test_returns_none_if_not_enough(self):
        rom = bytearray([0xFF] * 4)
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 8) is None

    def test_search_start_respected(self):
        rom = bytearray([0xFF] * 4 + [0x00] * 4 + [0xFF] * 8)
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 6, search_start=4) == 8

    def test_custom_fill_byte(self):
        rom = bytearray([0x00] * 4 + [0xAA] * 8)
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 6, fill_byte=0xAA) == 4

    def test_run_split_not_counted(self):
        rom = bytearray([0xFF, 0xFF, 0x00, 0xFF, 0xFF])
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 3) is None

    def test_zero_size_returns_search_start(self):
        rom = bytearray(8)
        rl = PointerRelinker()
        assert rl.find_free_space(rom, 0, search_start=3) == 3


# ---------------------------------------------------------------------------
# relink — in-place rewrite
# ---------------------------------------------------------------------------

class TestRelinkInPlace:
    def _setup(self):
        rom = bytearray(0x400)
        old_text = b'HELLO\xFF'
        text_offset = 0x100
        ptr_offset = 0x00
        rom[text_offset:text_offset + 6] = old_text
        rl = PointerRelinker(pointer_size=4, endian='little', base_address=0)
        rl.write_pointer(rom, ptr_offset, text_offset)
        records = [PointerRecord(
            pointer_offset=ptr_offset,
            target_offset=text_offset,
            pointer_type='absolute',
            bank=0,
        )]
        return rl, rom, records

    def test_inplace_string_fits(self):
        rl, rom, records = self._setup()
        new_rom, report = rl.relink(rom, records, new_strings=[b'HI'])
        assert new_rom[0x100:0x103] == b'HI\xFF'
        assert report.entries_relinked == 1
        assert report.entries_relocated == 0

    def test_pointer_unchanged_when_inplace(self):
        rl, rom, records = self._setup()
        new_rom, report = rl.relink(rom, records, new_strings=[b'HI'])
        ptr_val = rl.read_pointer(new_rom, 0)
        assert ptr_val == 0x100

    def test_tail_padded_with_fill_byte(self):
        rl, rom, records = self._setup()
        new_rom, _ = rl.relink(rom, records, new_strings=[b'H'], fill_byte=0xFF)
        assert new_rom[0x101:0x106] == bytes([0xFF] * 5)

    def test_bytes_saved_correct(self):
        rl, rom, records = self._setup()
        _, report = rl.relink(rom, records, new_strings=[b'H'])
        assert report.bytes_saved == 4  # 'HELLO' was 5 bytes; 'H' is 1 byte; saves 4

    def test_pointer_updates_logged(self):
        rl, rom, records = self._setup()
        _, report = rl.relink(rom, records, new_strings=[b'HI'])
        assert len(report.pointer_updates) == 1
        ptr_off, old_t, new_t = report.pointer_updates[0]
        assert ptr_off == 0
        assert old_t == 0x100
        assert new_t == 0x100


# ---------------------------------------------------------------------------
# relink — relocation to free space
# ---------------------------------------------------------------------------

class TestRelinkRelocation:
    def _setup(self):
        rom = bytearray([0xFF] * 0x400)
        old_text = b'AB'
        text_offset = 0x100
        ptr_offset = 0x00
        rom[text_offset:text_offset + 2] = old_text
        rl = PointerRelinker(pointer_size=4, endian='little', base_address=0)
        rl.write_pointer(rom, ptr_offset, text_offset)
        records = [PointerRecord(
            pointer_offset=ptr_offset,
            target_offset=text_offset,
            pointer_type='absolute',
            bank=0,
        )]
        return rl, rom, records

    def test_relocation_when_string_too_large(self):
        rl, rom, records = self._setup()
        big = b'HELLO WORLD!!'
        new_rom, report = rl.relink(rom, records, new_strings=[big])
        assert report.entries_relocated == 1
        assert report.entries_relinked == 0

    def test_new_pointer_points_to_new_location(self):
        rl, rom, records = self._setup()
        big = b'HELLO WORLD!!'
        new_rom, report = rl.relink(rom, records, new_strings=[big])
        new_ptr = rl.read_pointer(new_rom, 0)
        _, new_t = report.free_space_used[0][0], report.pointer_updates[0][2]
        assert new_ptr == new_t
        assert new_rom[new_ptr:new_ptr + len(big)] == big

    def test_free_space_used_logged(self):
        rl, rom, records = self._setup()
        big = b'HELLO WORLD!!'
        _, report = rl.relink(rom, records, new_strings=[big])
        assert len(report.free_space_used) == 1
        start, length = report.free_space_used[0]
        assert length == len(big)

    def test_no_free_space_raises(self):
        rl, rom, records = self._setup()
        rom[:] = b'\x00' * len(rom)
        rom[0x100:0x102] = b'AB'
        records[0].target_offset = 0x100
        rl.write_pointer(rom, 0, 0x100)
        with pytest.raises(RuntimeError):
            rl.relink(rom, records, new_strings=[b'X' * 2000], fill_byte=0xFF)


# ---------------------------------------------------------------------------
# RelinkReport correctness
# ---------------------------------------------------------------------------

class TestRelinkReport:
    def test_report_dataclass_fields(self):
        rr = RelinkReport(
            entries_relinked=3,
            entries_relocated=1,
            bytes_saved=10,
            pointer_updates=[(0, 0x100, 0x200)],
            free_space_used=[(0x200, 5)],
        )
        assert rr.entries_relinked == 3
        assert rr.entries_relocated == 1
        assert rr.bytes_saved == 10
        assert rr.pointer_updates[0] == (0, 0x100, 0x200)
        assert rr.free_space_used[0] == (0x200, 5)

    def test_report_to_dict(self):
        rr = RelinkReport(1, 0, 5, [(0, 0x10, 0x10)], [])
        d = rr.to_dict()
        assert d['entries_relinked'] == 1
        assert d['bytes_saved'] == 5

    def test_mixed_inplace_and_relocation(self):
        rom = bytearray(0x800)
        rom[0x100:0x105] = b'HELLO'
        rom[0x200:0x204] = b'ABCD'
        rl = PointerRelinker(pointer_size=4, endian='little')
        rl.write_pointer(rom, 0x00, 0x100)
        rl.write_pointer(rom, 0x04, 0x200)
        records = [
            PointerRecord(0x00, 0x100, 'absolute'),
            PointerRecord(0x04, 0x200, 'absolute'),
        ]
        new_rom, report = rl.relink(rom, records, [b'HI', b'A VERY LONG STRING INDEED!'])
        assert report.entries_relinked == 1
        assert report.entries_relocated == 1
        assert len(report.pointer_updates) == 2
