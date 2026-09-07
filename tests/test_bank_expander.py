import struct
import pytest
from miorom.core import RomExpander, FarPointerRelocator


def test_snes_rom_expansion():
    # Build minimal 512KB SNES LoROM
    rom = bytearray(0x80000)
    # Header at 0x7FC0
    header_off = 0x7FC0
    rom[header_off:header_off + 21] = b"TEST SNES GAME       "
    rom[header_off + 0x17] = 9  # 512KB = 2^9 KB
    # Valid checksum complement
    csum = 0x1234
    comp = 0xEDCB
    struct.pack_into("<HH", rom, header_off + 0x1C, comp, csum)

    # Expand to 2MB (0x200000)
    expanded = RomExpander.expand_snes(rom, 0x200000)
    assert len(expanded) == 0x200000
    # 2MB = 2048KB = 2^11 -> 0x0B
    assert expanded[header_off + 0x17] == 11

    # Verify checksum complement
    new_comp, new_csum = struct.unpack_from("<HH", expanded, header_off + 0x1C)
    assert (new_comp + new_csum) == 0xFFFF


def test_gb_rom_expansion():
    # Build minimal 256KB Game Boy ROM
    rom = bytearray(0x40000)
    rom[0x0134:0x0143] = b"TESTGAME\x00\x00\x00\x00\x00\x00\x00"
    rom[0x0148] = 3  # 256KB (32KB << 3)

    # Expand to 1MB (0x100000)
    expanded = RomExpander.expand_gb(rom, 0x100000)
    assert len(expanded) == 0x100000
    # 1MB = 32KB << 5
    assert expanded[0x0148] == 5

    # Verify header checksum
    h_csum = 0
    for b in expanded[0x0134:0x014D]:
        h_csum = (h_csum - b - 1) & 0xFF
    assert expanded[0x014D] == h_csum


def test_gba_rom_expansion():
    rom = bytearray(b"\x00" * 0x400000)  # 4MB
    expanded = RomExpander.expand_gba(rom, 0x800000)  # 8MB
    assert len(expanded) == 0x800000
    assert expanded[0x400000:] == b"\xFF" * 0x400000


def test_far_pointer_relocator_snes_24():
    # 32KB banks (0x8000), base bank = 0x80, RAM base = 0x8000
    relocator = FarPointerRelocator(
        bank_size=0x8000,
        base_bank=0x80,
        bank_ram_base=0x8000,
        pointer_format="snes_24",
    )

    # 3 items of 20KB (0x5000) each:
    # Item 1: fits in bank 0x80 (offset 0..0x5000)
    # Item 2: 0x5000 + 0x5000 = 0xA000 > 0x8000, must spill to bank 0x81!
    # Item 3: must spill to bank 0x82!
    items = [
        ("str1", b"A" * 0x5000),
        ("str2", b"B" * 0x5000),
        ("str3", b"C" * 0x5000),
    ]

    allocated = relocator.allocate(items)
    assert len(allocated) == 3

    assert allocated[0].bank == 0x80
    assert allocated[0].offset_in_bank == 0
    # SNES 24-bit pointer: offset 0x8000 in bank 0x80 -> 0x808000 (LE: 00 80 80)
    assert allocated[0].pointer_bytes == bytes([0x00, 0x80, 0x80])

    assert allocated[1].bank == 0x81
    assert allocated[1].offset_in_bank == 0
    assert allocated[1].pointer_bytes == bytes([0x00, 0x80, 0x81])

    assert allocated[2].bank == 0x82
    assert allocated[2].offset_in_bank == 0
    assert allocated[2].pointer_bytes == bytes([0x00, 0x80, 0x82])

    ptr_table, buffers = relocator.build_bank_buffers(items)
    assert len(ptr_table) == 9  # 3 items * 3 bytes
    assert len(buffers) == 3
    assert buffers[0x80][:5] == b"AAAAA"
    assert buffers[0x81][:5] == b"BBBBB"
    assert buffers[0x82][:5] == b"CCCCC"
