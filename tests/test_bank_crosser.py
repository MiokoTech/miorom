import pytest
from miorom.patch.bank_crosser import (
    BankCrossingRelocator,
    BankPartitionReport,
    BankedStringLocation,
)


def test_bank_crossing_partition_strings():
    # 5 strings of 100 bytes each. Bank capacity = 250 bytes.
    # Bank 1 can fit strings 0, 1 (200 bytes). String 2 (100 bytes) overflows (200+100 > 250),
    # so string 2 moves to Bank 2.
    # Bank 2 fits strings 2, 3 (200 bytes).
    # String 4 moves to Bank 3 (100 bytes).
    payloads = [b"A" * 100 for _ in range(5)]

    report = BankCrossingRelocator.partition_strings(
        payloads=payloads,
        start_bank=1,
        bank_capacity=250,
        bank_base_address=0x8000,
    )

    assert report.total_strings == 5
    assert report.banks_used == 3
    assert len(report.placements) == 5

    # Placements checks
    p0 = report.placements[0]
    assert p0.bank_id == 1
    assert p0.offset_in_bank == 0x8000
    assert p0.far_address == (1 << 16) | 0x8000

    p1 = report.placements[1]
    assert p1.bank_id == 1
    assert p1.offset_in_bank == 0x8000 + 100
    assert p1.far_address == (1 << 16) | (0x8000 + 100)

    p2 = report.placements[2]
    assert p2.bank_id == 2
    assert p2.offset_in_bank == 0x8000
    assert p2.far_address == (2 << 16) | 0x8000

    p3 = report.placements[3]
    assert p3.bank_id == 2
    assert p3.offset_in_bank == 0x8000 + 100
    assert p3.far_address == (2 << 16) | (0x8000 + 100)

    p4 = report.placements[4]
    assert p4.bank_id == 3
    assert p4.offset_in_bank == 0x8000
    assert p4.far_address == (3 << 16) | 0x8000

    assert report.bank_allocations[1] == 200
    assert report.bank_allocations[2] == 200
    assert report.bank_allocations[3] == 100


def test_bank_crossing_oversized_string_error():
    oversized = [b"X" * 1000]
    with pytest.raises(ValueError, match="exceeds maximum bank capacity"):
        BankCrossingRelocator.partition_strings(
            payloads=oversized,
            start_bank=1,
            bank_capacity=500,
        )


def test_snes_far_trampoline():
    trampoline = BankCrossingRelocator.generate_snes_far_trampoline(
        table_bank=0x05,
        base_offset=0x8000,
    )
    assert len(trampoline) == 11
    # Check LDA #table_bank opcode and operand
    assert trampoline[4] == 0xA9
    assert trampoline[5] == 0x05
    # Check RTL at end
    assert trampoline[-1] == 0x6B
