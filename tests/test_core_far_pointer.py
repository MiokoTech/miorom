"""
Unit tests for miorom.core.far_pointer.
"""

import pytest

from miorom.core.far_pointer import (
    BankedPointer,
    SplitPointerTable,
    InterleavedPointerTable,
    resolve_banked_to_offset,
    resolve_offset_to_banked,
    read_split_pointer_table,
    write_split_pointer_table,
    read_interleaved_pointer_table,
    write_interleaved_pointer_table,
    relocate_banked_table,
)


def test_resolve_banked_offset_roundtrip():
    # Game Boy Bank 2, Address 0x4200 -> Offset (2 * 0x4000) + 0x200 = 0x8200
    gb_offset = resolve_banked_to_offset(bank=2, cpu_address=0x4200, system="gb")
    assert gb_offset == 0x8200
    gb_bank, gb_addr = resolve_offset_to_banked(gb_offset, system="gb")
    assert gb_bank == 2
    assert gb_addr == 0x4200

    # SNES LoROM Bank $80, Address $8500 -> Offset $0500
    snes_offset = resolve_banked_to_offset(bank=0x80, cpu_address=0x8500, system="snes_lorom")
    assert snes_offset == 0x500
    s_bank, s_addr = resolve_offset_to_banked(snes_offset, system="snes_lorom")
    assert s_bank == 0x80
    assert s_addr == 0x8500

    # NES Linear Bank 3 (16KB bank), Address 0x9000 (base 0x8000) -> 3 * 0x4000 + 0x1000 = 0xD000
    nes_offset = resolve_banked_to_offset(bank=3, cpu_address=0x9000, system="nes", bank_size=0x4000, bank_base=0x8000)
    assert nes_offset == 0xD000
    n_bank, n_addr = resolve_offset_to_banked(nes_offset, system="nes", bank_size=0x4000, bank_base=0x8000)
    assert n_bank == 3
    assert n_addr == 0x9000


def test_split_pointer_table_read_write():
    # Build simulated ROM buffer
    buf = bytearray(256)

    # Bank table at offset 0x20: 3 entries [1, 2, 3]
    buf[0x20] = 1
    buf[0x21] = 2
    buf[0x22] = 3

    # Addr table at offset 0x40: 3 entries [0x4000, 0x4100, 0x4200]
    buf[0x40:0x42] = (0x4000).to_bytes(2, "little")
    buf[0x42:0x44] = (0x4100).to_bytes(2, "little")
    buf[0x44:0x46] = (0x4200).to_bytes(2, "little")

    table = read_split_pointer_table(
        bytes(buf),
        bank_offset=0x20,
        addr_offset=0x40,
        count=3,
        system="gb",
    )
    assert len(table.entries) == 3
    assert table.entries[0].bank == 1
    assert table.entries[0].cpu_address == 0x4000
    assert table.entries[0].file_offset == 0x4000

    assert table.entries[1].bank == 2
    assert table.entries[1].cpu_address == 0x4100
    assert table.entries[1].file_offset == (2 * 0x4000) + 0x100

    # Modify entry 1: change to bank 4, addr 0x5000
    table.entries[1].bank = 4
    table.entries[1].cpu_address = 0x5000
    write_split_pointer_table(buf, table)

    assert buf[0x21] == 4
    assert int.from_bytes(buf[0x42:0x44], "little") == 0x5000


def test_interleaved_pointer_table_read_write():
    # 3-byte entries SNES style: [addr_lo, addr_hi, bank]
    buf = bytearray(64)
    # Entry 0: Bank $81, Addr $8200 -> bytes: 0x00, 0x82, 0x81
    buf[0x10:0x13] = bytes([0x00, 0x82, 0x81])
    # Entry 1: Bank $81, Addr $8400 -> bytes: 0x00, 0x84, 0x81
    buf[0x13:0x16] = bytes([0x00, 0x84, 0x81])

    table = read_interleaved_pointer_table(
        bytes(buf),
        table_offset=0x10,
        count=2,
        system="snes_lorom",
        bank_first=False,
    )
    assert len(table.entries) == 2
    assert table.entries[0].bank == 0x81
    assert table.entries[0].cpu_address == 0x8200
    assert table.entries[0].file_offset == (1 * 0x8000) + 0x200

    # Modify entry 0 to Bank $82, Addr $9000
    table.entries[0].bank = 0x82
    table.entries[0].cpu_address = 0x9000
    write_interleaved_pointer_table(buf, table)

    assert buf[0x10:0x13] == bytes([0x00, 0x90, 0x82])


def test_relocate_banked_table():
    entries = [
        BankedPointer(index=0, bank=1, cpu_address=0x4000, file_offset=0x4000),
        BankedPointer(index=1, bank=1, cpu_address=0x4100, file_offset=0x4100),
    ]
    table = SplitPointerTable(
        bank_offset=0,
        addr_offset=10,
        count=2,
        endian="<",
        entries=entries,
    )

    # Relocate entry at 0x4100 to bank 3, offset 0xC250
    reloc_map = {0x4100: 0xC250}
    relocated = relocate_banked_table(table, reloc_map, system="gb")
    assert relocated == 1
    assert table.entries[1].file_offset == 0xC250
    assert table.entries[1].bank == 3
    assert table.entries[1].cpu_address == 0x4250
