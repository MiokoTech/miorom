from typing import Tuple

from miorom.core import schema
from miorom.errors import ParseError, RelocationError


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
    return ((src_addr + 8) + (imm24 << 2)) & 0xFFFFFFFF


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
    return ((src_addr + 4) + imm23) & 0xFFFFFFFF


def calc_mips_jump(dest_addr: int, link: bool = False, src_addr: int = -1) -> int:
    """
    Calculates 32-bit MIPS J or JAL instruction opcode.
    Target address must be 4-byte word-aligned.
    If src_addr is provided, validates the target is in the same 256MB segment
    as the delay slot (src_addr + 4), per MIPS architecture specification.
    """
    if dest_addr % 4 != 0:
        raise ValueError(f"MIPS jump target 0x{dest_addr:08X} is not 4-byte word-aligned")

    if src_addr >= 0:
        pc_seg = (src_addr + 4) & 0xF0000000
        tgt_seg = dest_addr & 0xF0000000
        if pc_seg != tgt_seg:
            raise ValueError(
                f"MIPS jump target 0x{dest_addr:08X} is in a different 256MB segment "
                f"than delay slot PC 0x{src_addr + 4:08X}."
            )

    target26 = (dest_addr >> 2) & 0x03FFFFFF
    op = 0x03 if link else 0x02
    return (op << 26) | target26


def resolve_mips_jump(src_addr: int, opcode: int) -> int:
    """Resolves destination address from a MIPS J or JAL opcode at src_addr."""
    target26 = opcode & 0x03FFFFFF
    return ((src_addr + 4) & 0xF0000000) | (target26 << 2)


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
    return ((src_addr + 4) + (offset16 << 2)) & 0xFFFFFFFF


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



class ARMBranch:
    """
    32-bit ARM state branch encoder and decoder (ARMv4T / ARMv5TE, used in GBA and NDS).
    """

    COND_AL = 0xE  # Always

    @classmethod
    def encode_b(
        cls,
        source_pc: int,
        target_addr: int,
        link: bool = False,
        cond: int = COND_AL,
    ) -> bytes:
        """
        Encodes ARM 32-bit B or BL instruction.
        In ARM state, PC is read as current_instruction + 8.
        """
        if (target_addr - (source_pc + 8)) % 4 != 0:
            raise ParseError(f"Target address 0x{target_addr:08X} is not 4-byte aligned.")
        opcode = calc_arm_branch(source_pc, target_addr, link=link, cond=cond)
        return schema.pack("<I", opcode)

    @classmethod
    def decode_b(cls, source_pc: int, instr_bytes: bytes) -> Tuple[int, bool, int]:
        """
        Decodes ARM 32-bit B/BL instruction.
        Returns (target_address, is_link, condition_code).
        """
        instr = schema.unpack("<I", instr_bytes[:4])[0]
        cond = (instr >> 28) & 0xF
        link = bool((instr >> 24) & 1)
        target = resolve_arm_branch(source_pc, instr)
        return target, link, cond


class ThumbBranch:
    """
    16-bit Thumb state branch encoder and decoder (used in GBA and NDS ARM7/ARM9).
    """

    @classmethod
    def encode_b(cls, source_pc: int, target_addr: int) -> bytes:
        """
        Encodes unconditional 16-bit Thumb branch (B label).
        PC is read as current_instruction + 4. Range: -2048 to +2046 bytes.
        """
        diff = target_addr - (source_pc + 4)
        if diff % 2 != 0:
            raise ParseError(f"Thumb target address 0x{target_addr:08X} is not 2-byte aligned.")
        if not (-2048 <= diff <= 2046):
            raise RelocationError(
                f"Thumb B target 0x{target_addr:08X} out of range from 0x{source_pc:08X} (-2048 to +2046 bytes)."
            )

        imm11 = (diff >> 1) & 0x7FF
        instr = 0xE000 | imm11
        return schema.pack("<H", instr)

    @classmethod
    def decode_b(cls, source_pc: int, instr_bytes: bytes) -> int:
        """
        Decodes 16-bit Thumb unconditional branch (B).
        Returns target address.
        """
        instr = schema.unpack("<H", instr_bytes[:2])[0]
        if (instr & 0xF800) != 0xE000:
            raise ParseError(f"Instruction 0x{instr:04X} is not a Thumb unconditional branch.")
        imm11 = instr & 0x7FF
        if imm11 & 0x400:
            imm11 -= 0x800
        return ((source_pc + 4) + (imm11 << 1)) & 0xFFFFFFFF

    @classmethod
    def encode_bl(cls, source_pc: int, target_addr: int) -> bytes:
        """
        Encodes 32-bit Thumb BL (Branch with Link) composed of two 16-bit halfwords.
        Range: -4MB to +4MB.
        """
        if (target_addr - (source_pc + 4)) % 2 != 0:
            raise ParseError(f"Thumb target address 0x{target_addr:08X} is not 2-byte aligned.")
        w1, w2 = calc_thumb_branch(source_pc, target_addr)
        return schema.pack("<HH", w1, w2)

    @classmethod
    def decode_bl(cls, source_pc: int, instr_bytes: bytes) -> int:
        """
        Decodes 32-bit Thumb BL pair (two 16-bit halfwords).
        Returns target address.
        """
        w1, w2 = schema.unpack("<HH", instr_bytes[:4])
        return resolve_thumb_branch(source_pc, w1, w2)


class PowerPCBranch:
    """
    32-bit PowerPC (PPC32 / Gekko / Broadway) branch encoder and decoder.
    Used in Nintendo GameCube and Wii.
    """

    @classmethod
    def encode_b(
        cls,
        source_pc: int,
        target_addr: int,
        link: bool = False,
        absolute: bool = False,
    ) -> bytes:
        """
        Encodes PowerPC 32-bit B, BA, BL, or BLA instruction.
        In PowerPC, PC is the address of the branch instruction itself.
        Range for relative branch: -32MB to +32MB (-0x02000000 to +0x01FFFFFC).
        """
        if absolute:
            diff = target_addr
        else:
            diff = target_addr - source_pc

        if diff % 4 != 0:
            raise ParseError(f"PowerPC target address 0x{target_addr:08X} is not 4-byte aligned.")

        if absolute:
            if not (0 <= target_addr <= 0x01FFFFFC or target_addr >= 0xFE000000):
                raise RelocationError(
                    f"PowerPC absolute branch target 0x{target_addr:08X} out of 26-bit addressable range."
                )
        elif diff < -0x02000000 or diff > 0x01FFFFFC:
            raise RelocationError(f"PowerPC relative branch target 0x{target_addr:08X} out of range (diff: {diff}).")

        li24 = (diff >> 2) & 0x00FFFFFF
        aa = 1 if absolute else 0
        lk = 1 if link else 0
        instr = (18 << 26) | (li24 << 2) | (aa << 1) | lk
        return schema.pack(">I", instr)

    @classmethod
    def decode_b(cls, source_pc: int, instr_bytes: bytes) -> Tuple[int, bool, bool]:
        """
        Decodes PowerPC 32-bit B/BL/BA/BLA instruction.
        Returns (target_address, is_link, is_absolute).
        """
        instr = schema.unpack(">I", instr_bytes[:4])[0]
        opcode = (instr >> 26) & 0x3F
        if opcode != 18:
            raise ParseError(f"Instruction 0x{instr:08X} is not a PowerPC unconditional branch (opcode {opcode} != 18).")

        li24 = (instr >> 2) & 0x00FFFFFF
        aa = bool((instr >> 1) & 1)
        lk = bool(instr & 1)

        # Sign-extend 24-bit to 32-bit
        if li24 & 0x00800000:
            li24 -= 0x01000000

        diff = li24 << 2
        target = (diff if aa else (source_pc + diff)) & 0xFFFFFFFF
        return target, lk, aa

    @classmethod
    def nop(cls) -> bytes:
        """Standard PowerPC NOP (ori r0, r0, 0 = 0x60000000)."""
        return b"\x60\x00\x00\x00"

    @classmethod
    def blr(cls) -> bytes:
        """Branch to Link Register (return from function: 0x4E800020)."""
        return b"\x4E\x80\x00\x20"


class MIPSBranch:
    """
    32-bit MIPS branch and jump encoder/decoder (MIPS I/II/III/IV/Allegrex).
    Used in PSX, PS2, N64, and PSP.
    """

    @classmethod
    def encode_j(
        cls,
        source_pc: int,
        target_addr: int,
        link: bool = False,
        endian: str = "<",
    ) -> bytes:
        """
        Encodes MIPS 32-bit J or JAL instruction.
        MIPS jump targets must share the same 256MB region with the jump delay slot (source_pc + 4).
        """
        if target_addr % 4 != 0:
            raise ParseError(f"MIPS target address 0x{target_addr:08X} is not 4-byte aligned.")

        pc_seg = (source_pc + 4) & 0xF0000000
        tgt_seg = target_addr & 0xF0000000
        if pc_seg != tgt_seg:
            raise ParseError(
                f"MIPS jump target 0x{target_addr:08X} is in a different 256MB segment than PC 0x{source_pc:08X}."
            )

        target_index = (target_addr >> 2) & 0x03FFFFFF
        opcode = 3 if link else 2
        instr = (opcode << 26) | target_index
        return schema.pack(f"{endian}I", instr)

    @classmethod
    def decode_j(cls, source_pc: int, instr_bytes: bytes, endian: str = "<") -> Tuple[int, bool]:
        """
        Decodes MIPS 32-bit J or JAL instruction.
        Returns (target_address, is_link).
        """
        instr = schema.unpack(f"{endian}I", instr_bytes[:4])[0]
        opcode = (instr >> 26) & 0x3F
        if opcode not in (2, 3):
            raise ParseError(f"Instruction 0x{instr:08X} is not a MIPS J/JAL instruction (opcode {opcode}).")

        target_index = instr & 0x03FFFFFF
        target_addr = ((source_pc + 4) & 0xF0000000) | (target_index << 2)
        link = (opcode == 3)
        return target_addr, link

    @classmethod
    def nop(cls, endian: str = "<") -> bytes:
        """Standard MIPS NOP (sll r0, r0, 0 = 0x00000000)."""
        return schema.pack(f"{endian}I", 0)

    @classmethod
    def jr_ra(cls, endian: str = "<") -> bytes:
        """Jump Register $ra (return from function: jr $ra = 0x03E00008)."""
        return schema.pack(f"{endian}I", 0x03E00008)
