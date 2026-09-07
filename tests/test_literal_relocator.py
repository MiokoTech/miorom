import struct
import pytest
from miorom.asm.literal_relocator import (
    CodeLiteralRelocator,
    LiteralRelocationReport,
)


def test_arm_literal_pool_relocation():
    # Buffer layout:
    # 0x00: LDR r0, [PC, #8] -> PC is 0x08, so target pool is 0x08 + 8 = 0x10.
    # Opcode: 0xE59F0008
    # 0x04: NOP (0xE1A00000)
    # 0x08: NOP (0xE1A00000)
    # 0x0C: NOP (0xE1A00000)
    # 0x10: Literal pool holding pointer to old string (0x02000050)
    # 0x50: Old string "Sword\x00"
    # 0x100: Cave offset for new string
    rom = bytearray(0x200)
    ram_base = 0x02000000

    struct.pack_into("<I", rom, 0x00, 0xE59F0008)
    struct.pack_into("<I", rom, 0x04, 0xE1A00000)
    struct.pack_into("<I", rom, 0x08, 0xE1A00000)
    struct.pack_into("<I", rom, 0x0C, 0xE1A00000)
    struct.pack_into("<I", rom, 0x10, ram_base + 0x50)

    rom[0x50:0x56] = b"Sword\x00"

    report = CodeLiteralRelocator.relocate_string(
        rom=rom,
        old_str="Sword",
        new_str="Pedang Pusaka Kuno Legenda",
        cave_offset=0x100,
        ram_base=ram_base,
        arch="arm",
        endian="<",
    )

    assert report.pointers_patched == 1
    assert report.old_address == ram_base + 0x50
    assert report.new_address == ram_base + 0x100

    # Verify literal pool at 0x10 updated to new_address
    new_pool_val = struct.unpack_from("<I", rom, 0x10)[0]
    assert new_pool_val == ram_base + 0x100

    # Verify new string at cave
    new_str_bytes = rom[0x100 : rom.find(b"\x00", 0x100)].decode("utf-8")
    assert new_str_bytes == "Pedang Pusaka Kuno Legenda"


def test_ppc_lis_addi_relocation():
    # PowerPC: lis r3, old_vaddr@ha (0x3C60xxxx)
    #          addi r3, r3, old_vaddr@l (0x3863xxxx)
    # ram_base = 0x80000000
    # old_offset = 0x80 -> old_vaddr = 0x80000080 (ha=0x8000, l=0x0080)
    rom = bytearray(0x200)
    ram_base = 0x80000000

    # lis r3, 0x8000 (0x3C608000)
    # addi r3, r3, 0x0080 (0x38630080)
    struct.pack_into(">I", rom, 0x00, 0x3C608000)
    struct.pack_into(">I", rom, 0x04, 0x38630080)

    rom[0x80:0x86] = b"Equip\x00"

    report = CodeLiteralRelocator.relocate_string(
        rom=rom,
        old_str="Equip",
        new_str="Perlengkapan Perang Lengkap",
        cave_offset=0x150,
        ram_base=ram_base,
        arch="ppc",
        endian=">",
    )

    assert report.pointers_patched == 1
    assert report.old_address == ram_base + 0x80
    assert report.new_address == ram_base + 0x150

    # Verify lis and addi patched
    new_lis = struct.unpack_from(">I", rom, 0x00)[0]
    new_addi = struct.unpack_from(">I", rom, 0x04)[0]
    # new_vaddr = 0x80000150 -> ha=0x8000, lo=0x0150
    assert (new_lis & 0xFFFF) == 0x8000
    assert (new_addi & 0xFFFF) == 0x0150
