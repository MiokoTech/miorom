from typing import Tuple


def calc_arm_branch(src_addr: int, dest_addr: int, link: bool = False, cond: int = 0xE) -> int:
    """
    Calculates 32-bit ARM B or BL instruction opcode.
    Accounts for ARM 8-byte prefetch pipeline offset (PC = src_addr + 8).
    Displacement must be 4-byte aligned and fit within +/- 32MB.
    """
    delta = dest_addr - (src_addr + 8)
    if delta % 4 != 0:
        raise ValueError(f"ARM branch target address 0x{dest_addr:08X} is not 4-byte word-aligned")

    imm24 = delta >> 2
    if not (-0x800000 <= imm24 <= 0x7FFFFF):
        raise ValueError(f"ARM branch target 0x{dest_addr:08X} out of range from 0x{src_addr:08X} (+/- 32MB)")

    l_bit = 1 if link else 0
    return ((cond & 0x0F) << 28) | (0b101 << 25) | (l_bit << 24) | (imm24 & 0x00FFFFFF)


def resolve_arm_branch(src_addr: int, opcode: int) -> int:
    """Resolves destination address from an ARM B or BL opcode at src_addr."""
    imm24 = opcode & 0x00FFFFFF
    if imm24 & 0x00800000:
        imm24 -= 0x01000000
    return (src_addr + 8) + (imm24 << 2)


def calc_thumb_branch(src_addr: int, dest_addr: int) -> Tuple[int, int]:
    """
    Calculates pair of 16-bit Thumb BL instruction opcodes (prefix and suffix).
    Accounts for Thumb 4-byte pipeline offset (PC = src_addr + 4).
    Displacement must be 2-byte halfword-aligned and fit within +/- 4MB.
    """
    delta = dest_addr - (src_addr + 4)
    if delta % 2 != 0:
        raise ValueError(f"Thumb branch target address 0x{dest_addr:08X} is not 2-byte aligned")

    if not (-0x400000 <= delta <= 0x3FFFFE):
        raise ValueError(f"Thumb BL target 0x{dest_addr:08X} out of range from 0x{src_addr:08X} (+/- 4MB)")

    inst1 = 0xF000 | ((delta >> 12) & 0x7FF)
    inst2 = 0xF800 | ((delta >> 1) & 0x7FF)
    return inst1, inst2


def resolve_thumb_branch(src_addr: int, inst1: int, inst2: int) -> int:
    """Resolves destination address from a pair of Thumb BL instructions at src_addr."""
    offset_hi = (inst1 & 0x7FF) << 12
    offset_lo = (inst2 & 0x7FF) << 1
    imm23 = offset_hi | offset_lo
    if imm23 & 0x00400000:
        imm23 -= 0x00800000
    return (src_addr + 4) + imm23


def calc_mips_jump(dest_addr: int, link: bool = False) -> int:
    """
    Calculates 32-bit MIPS J or JAL instruction opcode.
    Target address must be 4-byte word-aligned.
    """
    if dest_addr % 4 != 0:
        raise ValueError(f"MIPS jump target 0x{dest_addr:08X} is not 4-byte word-aligned")

    target26 = (dest_addr >> 2) & 0x03FFFFFF
    op = 0x03 if link else 0x02
    return (op << 26) | target26


def resolve_mips_jump(src_addr: int, opcode: int) -> int:
    """Resolves destination address from a MIPS J or JAL opcode at src_addr."""
    target26 = opcode & 0x03FFFFFF
    return (src_addr & 0xF0000000) | (target26 << 2)


def calc_mips_branch(
    src_addr: int,
    dest_addr: int,
    opcode: int = 0x04,
    rs: int = 0,
    rt: int = 0,
) -> int:
    """
    Calculates 32-bit MIPS conditional branch opcode (e.g. BEQ 0x04, BNE 0x05).
    Accounts for branch delay slot (PC = src_addr + 4).
    Displacement must be 4-byte aligned and fit in 16-bit signed word offset (+/- 128KB).
    """
    delta = dest_addr - (src_addr + 4)
    if delta % 4 != 0:
        raise ValueError(f"MIPS branch target 0x{dest_addr:08X} is not 4-byte word-aligned")

    word_offset = delta >> 2
    if not (-0x8000 <= word_offset <= 0x7FFF):
        raise ValueError(f"MIPS branch target 0x{dest_addr:08X} out of 16-bit range from 0x{src_addr:08X}")

    return ((opcode & 0x3F) << 26) | ((rs & 0x1F) << 21) | ((rt & 0x1F) << 16) | (word_offset & 0xFFFF)


def resolve_mips_branch(src_addr: int, opcode: int) -> int:
    """Resolves destination address from a MIPS branch opcode at src_addr."""
    offset16 = opcode & 0xFFFF
    if offset16 & 0x8000:
        offset16 -= 0x10000
    return (src_addr + 4) + (offset16 << 2)


def calc_6502_branch(src_addr: int, dest_addr: int, opcode: int = 0xF0) -> Tuple[int, int]:
    """
    Calculates 2-byte MOS 6502 / W65C816 relative branch instruction (opcode, displacement).
    Accounts for 2-byte PC advancement (PC = src_addr + 2).
    Displacement must fit in signed 8-bit range (-128 to +127 bytes).
    """
    disp = dest_addr - (src_addr + 2)
    if not (-128 <= disp <= 127):
        raise ValueError(f"6502 branch displacement {disp} out of 8-bit range (-128 to +127)")

    return opcode & 0xFF, disp & 0xFF


def resolve_6502_branch(src_addr: int, disp_byte: int) -> int:
    """Resolves destination address from a 6502 relative branch displacement byte."""
    disp = disp_byte & 0xFF
    if disp & 0x80:
        disp -= 0x100
    return (src_addr + 2) + disp
