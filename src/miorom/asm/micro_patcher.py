"""
miorom.asm.micro_patcher
~~~~~~~~~~~~~~~~~~~~~~~~
Low-Level Assembly Micro-Patcher & Split Immediate Math Primitives.
Pure math and opcode transformation functions for PowerPC, MIPS, and ARM architectures.
Leaves full control of instruction placement and verification to the programmer.
"""

import struct
from typing import Tuple


class SplitImmediateCalculator:
    """
    Pure mathematical calculator for split 16-bit immediates across RISC architectures.
    """

    @classmethod
    def calc_ppc_ha_l(cls, target_addr: int) -> Tuple[int, int]:
        """
        Calculates PowerPC (lis @ha, addi @l) immediate pair with sign-extension compensation.
        Returns (ha16, l16).
        """
        addr = target_addr & 0xFFFFFFFF
        l = addr & 0xFFFF
        ha = (addr >> 16) & 0xFFFF
        if l >= 0x8000:
            ha = (ha + 1) & 0xFFFF
        return ha, l

    @classmethod
    def calc_mips_hi_lo(cls, target_addr: int) -> Tuple[int, int]:
        """
        Calculates MIPS (lui %hi, addiu %lo) immediate pair with sign-extension compensation.
        Returns (hi16, lo16).
        """
        addr = target_addr & 0xFFFFFFFF
        lo = addr & 0xFFFF
        hi = (addr >> 16) & 0xFFFF
        if lo >= 0x8000:
            hi = (hi + 1) & 0xFFFF
        return hi, lo

    @classmethod
    def calc_arm_movw_movt(cls, target_addr: int) -> Tuple[int, int]:
        """
        Calculates ARMv7 (movw #imm16, movt #imm16) immediate pair.
        Returns (imm_lo, imm_hi).
        """
        addr = target_addr & 0xFFFFFFFF
        return addr & 0xFFFF, (addr >> 16) & 0xFFFF


class StackAllocPatcher:
    """
    Pure primitive to patch stack frame allocation immediates.
    """

    @classmethod
    def patch_arm_sub_sp(
        cls,
        code: bytearray,
        offset: int,
        frame_size: int,
        endian: str = "<",
    ) -> bool:
        """
        Patches an ARM32 SUB SP, SP, #imm8 instruction (frame_size <= 255).
        """
        if not (0 <= frame_size <= 255) or offset + 4 > len(code):
            return False
        word = struct.unpack_from(f"{endian}I", code, offset)[0]
        # Preserve condition code
        cond = (word >> 28) & 0xF
        new_op = (cond << 28) | 0x024DD000 | frame_size
        struct.pack_into(f"{endian}I", code, offset, new_op)
        return True

    @classmethod
    def patch_mips_addiu_sp(
        cls,
        code: bytearray,
        offset: int,
        frame_size: int,
        endian: str = "<",
    ) -> bool:
        """
        Patches MIPS addiu $sp, $sp, -frame_size (frame_size <= 32768).
        """
        if not (0 < frame_size <= 32768) or offset + 4 > len(code):
            return False
        # addiu $sp, $sp, -frame_size: opcode=0x27BD, imm16 = (-frame_size) & 0xFFFF
        imm16 = (-frame_size) & 0xFFFF
        op = 0x27BD0000 | imm16
        struct.pack_into(f"{endian}I", code, offset, op)
        return True


class OpcodeTransmuter:
    """
    Pure primitive to transmute single assembly instructions in-place.
    """

    @classmethod
    def transmute_arm_ldrh_to_ldrb(
        cls,
        code: bytearray,
        offset: int,
        endian: str = "<",
    ) -> bool:
        """
        Transmutes an ARM32 LDRH instruction to an LDRB instruction at offset.
        """
        if offset + 4 > len(code):
            return False

        word = struct.unpack_from(f"{endian}I", code, offset)[0]
        is_ldrh = ((word >> 25) & 0x7) == 0 and ((word >> 4) & 0xF) == 0xB
        if not is_ldrh:
            return False

        cond = (word >> 28) & 0xF
        u_bit = (word >> 23) & 1
        rn = (word >> 16) & 0xF
        rd = (word >> 12) & 0xF
        imm_hi = (word >> 8) & 0xF
        imm_lo = word & 0xF
        offset_imm = (imm_hi << 4) | imm_lo

        u_flag = 0x00800000 if u_bit else 0
        new_opcode = (cond << 28) | 0x05500000 | u_flag | (rn << 16) | (rd << 12) | (offset_imm & 0xFFF)
        struct.pack_into(f"{endian}I", code, offset, new_opcode)
        return True
