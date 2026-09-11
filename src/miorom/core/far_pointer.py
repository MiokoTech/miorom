"""
miorom.core.far_pointer
~~~~~~~~~~~~~~~~~~~~~~~
Split-bank and dual-table far pointer resolver, serializer, and relocator
for banked retro console architectures (NES, Game Boy, SNES, and PCE).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union
import struct

from miorom.core.bus_mapper import SNESBusMapper, GameBoyBusMapper
from miorom.result import MioRomResult


@dataclass
class BankedPointer(MioRomResult):
    """
    Represents a far pointer composed of a memory bank and CPU address.
    """
    index: int
    bank: int
    cpu_address: int
    file_offset: int
    bank_table_offset: Optional[int] = None
    addr_table_offset: Optional[int] = None


@dataclass
class SplitPointerTable(MioRomResult):
    """
    Manages dual parallel tables: a 1-byte bank array and a 2-byte address array.
    """
    bank_offset: int
    addr_offset: int
    count: int
    endian: str
    entries: List[BankedPointer]


@dataclass
class InterleavedPointerTable(MioRomResult):
    """
    Manages 3-byte contiguous far pointer entries (e.g. SNES 24-bit far pointers).
    """
    table_offset: int
    count: int
    bank_first: bool
    endian: str
    entries: List[BankedPointer]


def resolve_banked_to_offset(
    bank: int,
    cpu_address: int,
    system: str = "nes",
    bank_size: int = 0x4000,
    bank_base: int = 0x8000,
    smc_header: bool = False,
) -> int:
    """
    Translate a (bank, cpu_address) pair to a physical ROM file offset.
    """
    sys_lower = system.lower()
    if sys_lower == "gb":
        return GameBoyBusMapper.mbc_to_offset(cpu_address, bank=bank)
    elif sys_lower in ("snes_lorom", "lorom"):
        snes_addr = ((bank & 0xFF) << 16) | (cpu_address & 0xFFFF)
        return SNESBusMapper.lorom_to_offset(snes_addr, smc_header=smc_header)
    elif sys_lower in ("snes_hirom", "hirom"):
        snes_addr = ((bank & 0xFF) << 16) | (cpu_address & 0xFFFF)
        return SNESBusMapper.hirom_to_offset(snes_addr, smc_header=smc_header)
    else:
        # Linear banked mapping
        return (bank * bank_size) + (cpu_address - bank_base)


def resolve_offset_to_banked(
    file_offset: int,
    system: str = "nes",
    bank_size: int = 0x4000,
    bank_base: int = 0x8000,
    smc_header: bool = False,
) -> Tuple[int, int]:
    """
    Translate a physical ROM file offset to a (bank, cpu_address) pair.
    """
    sys_lower = system.lower()
    if sys_lower == "gb":
        return GameBoyBusMapper.offset_to_mbc(file_offset)
    elif sys_lower in ("snes_lorom", "lorom"):
        snes_addr = SNESBusMapper.offset_to_lorom(file_offset, smc_header=smc_header)
        return (snes_addr >> 16) & 0xFF, snes_addr & 0xFFFF
    elif sys_lower in ("snes_hirom", "hirom"):
        snes_addr = SNESBusMapper.offset_to_hirom(file_offset, smc_header=smc_header)
        return (snes_addr >> 16) & 0xFF, snes_addr & 0xFFFF
    else:
        bank = file_offset // bank_size
        cpu_addr = bank_base + (file_offset % bank_size)
        return bank, cpu_addr


def read_split_pointer_table(
    data: bytes,
    bank_offset: int,
    addr_offset: int,
    count: int,
    system: str = "nes",
    bank_size: int = 0x4000,
    bank_base: int = 0x8000,
    endian: str = "<",
) -> SplitPointerTable:
    """
    Read dual parallel tables (1-byte banks and 2-byte CPU addresses).
    """
    if bank_offset + count > len(data):
        raise ValueError("Bank table exceeds data length")
    if addr_offset + (count * 2) > len(data):
        raise ValueError("Address table exceeds data length")

    entries: List[BankedPointer] = []
    for i in range(count):
        b_pos = bank_offset + i
        a_pos = addr_offset + (i * 2)
        bank_val = data[b_pos]
        addr_val = struct.unpack_from(f"{endian}H", data, a_pos)[0]
        f_offset = resolve_banked_to_offset(
            bank=bank_val,
            cpu_address=addr_val,
            system=system,
            bank_size=bank_size,
            bank_base=bank_base,
        )
        entries.append(
            BankedPointer(
                index=i,
                bank=bank_val,
                cpu_address=addr_val,
                file_offset=f_offset,
                bank_table_offset=b_pos,
                addr_table_offset=a_pos,
            )
        )

    return SplitPointerTable(
        bank_offset=bank_offset,
        addr_offset=addr_offset,
        count=count,
        endian=endian,
        entries=entries,
    )


def write_split_pointer_table(
    buffer: bytearray,
    table: SplitPointerTable,
) -> None:
    """
    Write updated banked pointer entries into dual parallel tables in a bytearray buffer.
    """
    for entry in table.entries:
        b_pos = entry.bank_table_offset if entry.bank_table_offset is not None else (table.bank_offset + entry.index)
        a_pos = entry.addr_table_offset if entry.addr_table_offset is not None else (table.addr_offset + entry.index * 2)
        buffer[b_pos] = entry.bank & 0xFF
        struct.pack_into(f"{table.endian}H", buffer, a_pos, entry.cpu_address & 0xFFFF)


def read_interleaved_pointer_table(
    data: bytes,
    table_offset: int,
    count: int,
    system: str = "snes_lorom",
    bank_first: bool = False,
    bank_size: int = 0x8000,
    bank_base: int = 0x8000,
    endian: str = "<",
    smc_header: bool = False,
) -> InterleavedPointerTable:
    """
    Read 3-byte contiguous far pointer entries.
    bank_first=False parses [addr_lo, addr_hi, bank] (canonical SNES format).
    bank_first=True parses [bank, addr_lo, addr_hi].
    """
    needed = table_offset + (count * 3)
    if len(data) < needed:
        raise ValueError(f"Data length {len(data)} is insufficient for {count} far pointers")

    entries: List[BankedPointer] = []
    for i in range(count):
        pos = table_offset + (i * 3)
        if bank_first:
            b_val = data[pos]
            a_val = struct.unpack_from(f"{endian}H", data, pos + 1)[0]
        else:
            a_val = struct.unpack_from(f"{endian}H", data, pos)[0]
            b_val = data[pos + 2]

        f_offset = resolve_banked_to_offset(
            bank=b_val,
            cpu_address=a_val,
            system=system,
            bank_size=bank_size,
            bank_base=bank_base,
            smc_header=smc_header,
        )
        entries.append(
            BankedPointer(
                index=i,
                bank=b_val,
                cpu_address=a_val,
                file_offset=f_offset,
                bank_table_offset=pos + (0 if bank_first else 2),
                addr_table_offset=pos + (1 if bank_first else 0),
            )
        )

    return InterleavedPointerTable(
        table_offset=table_offset,
        count=count,
        bank_first=bank_first,
        endian=endian,
        entries=entries,
    )


def write_interleaved_pointer_table(
    buffer: bytearray,
    table: InterleavedPointerTable,
) -> None:
    """
    Write updated 3-byte contiguous far pointer entries back to a buffer.
    """
    for i, entry in enumerate(table.entries):
        pos = table.table_offset + (i * 3)
        if table.bank_first:
            buffer[pos] = entry.bank & 0xFF
            struct.pack_into(f"{table.endian}H", buffer, pos + 1, entry.cpu_address & 0xFFFF)
        else:
            struct.pack_into(f"{table.endian}H", buffer, pos, entry.cpu_address & 0xFFFF)
            buffer[pos + 2] = entry.bank & 0xFF


def relocate_banked_table(
    table: Union[SplitPointerTable, InterleavedPointerTable],
    relocation_map: Dict[int, int],
    system: str = "nes",
    bank_size: int = 0x4000,
    bank_base: int = 0x8000,
    smc_header: bool = False,
) -> int:
    """
    Relocate banked pointers matching old file offsets in relocation_map to new offsets.
    Returns the count of relocated entries.
    """
    relocated_count = 0
    for entry in table.entries:
        if entry.file_offset in relocation_map:
            new_offset = relocation_map[entry.file_offset]
            new_bank, new_addr = resolve_offset_to_banked(
                file_offset=new_offset,
                system=system,
                bank_size=bank_size,
                bank_base=bank_base,
                smc_header=smc_header,
            )
            entry.bank = new_bank
            entry.cpu_address = new_addr
            entry.file_offset = new_offset
            relocated_count += 1

    return relocated_count
