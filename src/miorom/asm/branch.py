import struct
from typing import Optional, Tuple


from miorom.asm.branch_calc import (
    calc_arm_branch,
    resolve_arm_branch,
    calc_thumb_branch,
    resolve_thumb_branch,
    calc_mips_jump,
    resolve_mips_jump,
    calc_mips_branch,
    resolve_mips_branch,
    calc_6502_branch,
    resolve_6502_branch,
)
from miorom.errors import ParseError, RelocationError


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
        return struct.pack("<I", opcode)

    @classmethod
    def decode_b(cls, source_pc: int, instr_bytes: bytes) -> Tuple[int, bool, int]:
        """
        Decodes ARM 32-bit B/BL instruction.
        Returns (target_address, is_link, condition_code).
        """
        instr = struct.unpack("<I", instr_bytes[:4])[0]
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

        imm11 = (diff >> 1) & 0x7FF
        instr = 0xE000 | imm11
        return struct.pack("<H", instr)

    @classmethod
    def encode_bl(cls, source_pc: int, target_addr: int) -> bytes:
        """
        Encodes 32-bit Thumb BL (Branch with Link) composed of two 16-bit halfwords.
        Range: -4MB to +4MB.
        """
        if (target_addr - (source_pc + 4)) % 2 != 0:
            raise ParseError(f"Thumb target address 0x{target_addr:08X} is not 2-byte aligned.")
        w1, w2 = calc_thumb_branch(source_pc, target_addr)
        return struct.pack("<HH", w1, w2)


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

        if not absolute and (diff < -0x02000000 or diff > 0x01FFFFFC):
            raise RelocationError(f"PowerPC relative branch target 0x{target_addr:08X} out of range (diff: {diff}).")

        li24 = (diff >> 2) & 0x00FFFFFF
        aa = 1 if absolute else 0
        lk = 1 if link else 0
        instr = (18 << 26) | (li24 << 2) | (aa << 1) | lk
        return struct.pack(">I", instr)

    @classmethod
    def decode_b(cls, source_pc: int, instr_bytes: bytes) -> Tuple[int, bool, bool]:
        """
        Decodes PowerPC 32-bit B/BL/BA/BLA instruction.
        Returns (target_address, is_link, is_absolute).
        """
        instr = struct.unpack(">I", instr_bytes[:4])[0]
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
        target = diff if aa else (source_pc + diff)
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
        return struct.pack(f"{endian}I", instr)

    @classmethod
    def decode_j(cls, source_pc: int, instr_bytes: bytes, endian: str = "<") -> Tuple[int, bool]:
        """
        Decodes MIPS 32-bit J or JAL instruction.
        Returns (target_address, is_link).
        """
        instr = struct.unpack(f"{endian}I", instr_bytes[:4])[0]
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
        return struct.pack(f"{endian}I", 0)

    @classmethod
    def jr_ra(cls, endian: str = "<") -> bytes:
        """Jump Register $ra (return from function: jr $ra = 0x03E00008)."""
        return struct.pack(f"{endian}I", 0x03E00008)
