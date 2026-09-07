"""
miorom.patch.bank_crosser
~~~~~~~~~~~~~~~~~~~~~~~~~
Bank-Crossing Far Pointer Relocator & Multi-Bank Bin Packer.
Solves 16-bit pointer and 64KB/16KB bank overflow limitations on classic architectures
(SNES LoROM/HiROM, Game Boy MBC, GBA) when massive text expansions cannot fit
within a single local memory bank.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


@dataclass
class BankedStringLocation:
    """Represents the placement of a string across memory banks."""
    item_index: int
    bank_id: int
    offset_in_bank: int
    size: int
    far_address: int  # (bank_id << 16) | offset_in_bank


@dataclass
class BankPartitionReport:
    """Report on multi-bank text distribution."""
    total_strings: int
    banks_used: int
    bank_allocations: Dict[int, int] = field(default_factory=dict)  # bank_id -> bytes_used
    placements: List[BankedStringLocation] = field(default_factory=list)


class BankCrossingRelocator:
    """
    Partitions expanded string collections across bank boundaries using bin-packing.
    """

    @classmethod
    def partition_strings(
        cls,
        payloads: Sequence[bytes],
        start_bank: int,
        bank_capacity: int = 0x8000,
        bank_base_address: int = 0x8000,
    ) -> BankPartitionReport:
        """
        Distributes strings sequentially across banks so no string crosses a bank boundary.
        Calculates the exact 16-bit in-bank offset and 24-bit far address for each.
        """
        placements: List[BankedStringLocation] = []
        bank_usage: Dict[int, int] = {}

        cur_bank = start_bank
        cur_offset = 0

        for i, payload in enumerate(payloads):
            sz = len(payload)
            if sz > bank_capacity:
                raise ValueError(
                    f"String {i} size ({sz} bytes) exceeds maximum bank capacity ({bank_capacity} bytes)"
                )

            # If it doesn't fit in the current bank, advance to the next bank
            if cur_offset + sz > bank_capacity:
                bank_usage[cur_bank] = cur_offset
                cur_bank += 1
                cur_offset = 0

            in_bank_addr = bank_base_address + cur_offset
            far_addr = (cur_bank << 16) | (in_bank_addr & 0xFFFF)

            placements.append(
                BankedStringLocation(
                    item_index=i,
                    bank_id=cur_bank,
                    offset_in_bank=in_bank_addr,
                    size=sz,
                    far_address=far_addr,
                )
            )

            cur_offset += sz

        bank_usage[cur_bank] = cur_offset

        return BankPartitionReport(
            total_strings=len(payloads),
            banks_used=len(bank_usage),
            bank_allocations=bank_usage,
            placements=placements,
        )

    @classmethod
    def generate_snes_far_trampoline(cls, table_bank: int, base_offset: int) -> bytes:
        """
        Generates a 65816 SNES ASM trampoline stub to read far strings:
        PHP, REP #$20, LDA table, PHA, PLB, ... PLP, RTL
        """
        # Minimal 65816 byte stub
        return bytes([
            0x08,              # PHP (Push processor status)
            0xC2, 0x20,        # REP #$20 (16-bit A)
            0x8B,              # PHB (Push data bank)
            0xA9, table_bank,  # LDA #table_bank
            0x48,              # PHA
            0xAB,              # PLB (Pull data bank)
            0xAB,              # PLB
            0x28,              # PLP
            0x6B,              # RTL
        ])
