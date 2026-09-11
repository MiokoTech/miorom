"""
miorom.asm.reloc_calc
~~~~~~~~~~~~~~~~~~~~~
Low-level PC-relative branch displacement rebasing and instruction relocation engine.
Calculates displacement adjustments when moving machine code routines across memory bases.
Supports MOS 6502, W65C816, Z80, SM83, Motorola 68000, ARM, Thumb, and MIPS.
"""

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class BranchRelocation(MioRomResult):
    """Represents a relocated or inspected PC-relative branch instruction."""
    offset: int
    arch: str
    mnemonic: str
    orig_pc: int
    new_pc: int
    target_addr: int
    orig_bytes: bytes
    new_bytes: bytes
    displacement: int
    in_range: bool
    description: str = ""


class BranchRelocator:
    """
    Engine for calculating, inspecting, and patching PC-relative branch displacements
    when relocating binary code blocks or re-targeting routines into code caves.
    """

    BRANCH_OPCODES_6502 = {
        0x10: "BPL",
        0x30: "BMI",
        0x50: "BVC",
        0x70: "BVS",
        0x90: "BCC",
        0xB0: "BCS",
        0xD0: "BNE",
        0xF0: "BEQ",
    }

    BRANCH_OPCODES_Z80 = {
        0x18: "JR",
        0x20: "JR_NZ",
        0x28: "JR_Z",
        0x30: "JR_NC",
        0x38: "JR_C",
        0x10: "DJNZ",
    }

    @staticmethod
    def calc_displacement_6502(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 8-bit displacement for MOS 6502 relative branch (PC advance: 2)."""
        disp = target - (pc + 2)
        valid = -128 <= disp <= 127
        return disp, valid

    @staticmethod
    def resolve_target_6502(pc: int, disp_byte: int) -> int:
        """Resolves target address from 6502 PC and displacement byte."""
        disp = disp_byte & 0xFF
        if disp & 0x80:
            disp -= 0x100
        return pc + 2 + disp

    @staticmethod
    def calc_displacement_65816_long(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 16-bit displacement for 65816 BRL instruction (PC advance: 3)."""
        disp = target - (pc + 3)
        valid = -32768 <= disp <= 32767
        return disp, valid

    @staticmethod
    def calc_displacement_z80(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 8-bit displacement for Z80/SM83 relative branch (PC advance: 2)."""
        disp = target - (pc + 2)
        valid = -128 <= disp <= 127
        return disp, valid

    @staticmethod
    def resolve_target_z80(pc: int, disp_byte: int) -> int:
        """Resolves target address from Z80/SM83 PC and displacement byte."""
        disp = disp_byte & 0xFF
        if disp & 0x80:
            disp -= 0x100
        return pc + 2 + disp

    @staticmethod
    def calc_displacement_m68k_8bit(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 8-bit displacement for M68K branch (PC advance: 2)."""
        disp = target - (pc + 2)
        valid = -128 <= disp <= 127 and disp != 0 and disp != -1
        return disp, valid

    @staticmethod
    def calc_displacement_m68k_16bit(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 16-bit displacement for M68K branch (PC advance: 2)."""
        disp = target - (pc + 2)
        valid = -32768 <= disp <= 32767
        return disp, valid

    @staticmethod
    def calc_displacement_arm(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates 24-bit word offset for ARM B/BL (PC advance: 8)."""
        delta = target - (pc + 8)
        if delta % 4 != 0:
            return delta, False
        imm24 = delta >> 2
        valid = -0x800000 <= imm24 <= 0x7FFFFF
        return imm24, valid

    @staticmethod
    def calc_displacement_thumb_cond(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 8-bit halfword offset for Thumb conditional B (PC advance: 4)."""
        delta = target - (pc + 4)
        if delta % 2 != 0:
            return delta, False
        imm8 = delta >> 1
        valid = -128 <= imm8 <= 127
        return imm8, valid

    @staticmethod
    def calc_displacement_thumb_uncond(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 11-bit halfword offset for Thumb unconditional B (PC advance: 4)."""
        delta = target - (pc + 4)
        if delta % 2 != 0:
            return delta, False
        imm11 = delta >> 1
        valid = -1024 <= imm11 <= 1023
        return imm11, valid

    @staticmethod
    def calc_displacement_mips_branch(pc: int, target: int) -> Tuple[int, bool]:
        """Calculates signed 16-bit word offset for MIPS conditional branch (PC advance: 4)."""
        delta = target - (pc + 4)
        if delta % 4 != 0:
            return delta, False
        word_offset = delta >> 2
        valid = -0x8000 <= word_offset <= 0x7FFF
        return word_offset, valid

    def patch_single_branch(
        self,
        inst_bytes: bytes,
        orig_pc: int,
        new_pc: int,
        target_addr: int,
        arch: str,
    ) -> BranchRelocation:
        """
        Recalculates displacement and patches a single branch instruction bytes.
        """
        arch_norm = arch.lower().strip()

        if arch_norm in ("6502", "nes"):
            if len(inst_bytes) < 2:
                raise ValueError("6502 branch instruction requires at least 2 bytes")
            op = inst_bytes[0]
            mnemonic = self.BRANCH_OPCODES_6502.get(op, f"B_{op:02X}")
            disp, valid = self.calc_displacement_6502(new_pc, target_addr)
            new_bytes = bytes([op, disp & 0xFF])
            return BranchRelocation(
                offset=0,
                arch=arch_norm,
                mnemonic=mnemonic,
                orig_pc=orig_pc,
                new_pc=new_pc,
                target_addr=target_addr,
                orig_bytes=inst_bytes[:2],
                new_bytes=new_bytes,
                displacement=disp,
                in_range=valid,
                description=f"{mnemonic} to 0x{target_addr:04X} (disp: {disp})",
            )

        if arch_norm in ("65816", "snes"):
            if len(inst_bytes) < 2:
                raise ValueError("65816 branch instruction requires at least 2 bytes")
            op = inst_bytes[0]
            if op == 0x82:
                if len(inst_bytes) < 3:
                    raise ValueError("65816 BRL instruction requires 3 bytes")
                disp, valid = self.calc_displacement_65816_long(new_pc, target_addr)
                new_bytes = bytes([0x82]) + struct.pack("<h", disp if valid else 0)
                return BranchRelocation(
                    offset=0,
                    arch=arch_norm,
                    mnemonic="BRL",
                    orig_pc=orig_pc,
                    new_pc=new_pc,
                    target_addr=target_addr,
                    orig_bytes=inst_bytes[:3],
                    new_bytes=new_bytes,
                    displacement=disp,
                    in_range=valid,
                    description=f"BRL to 0x{target_addr:04X} (disp: {disp})",
                )
            mnemonic = self.BRANCH_OPCODES_6502.get(op, f"B_{op:02X}")
            disp, valid = self.calc_displacement_6502(new_pc, target_addr)
            new_bytes = bytes([op, disp & 0xFF])
            return BranchRelocation(
                offset=0,
                arch=arch_norm,
                mnemonic=mnemonic,
                orig_pc=orig_pc,
                new_pc=new_pc,
                target_addr=target_addr,
                orig_bytes=inst_bytes[:2],
                new_bytes=new_bytes,
                displacement=disp,
                in_range=valid,
                description=f"{mnemonic} to 0x{target_addr:04X} (disp: {disp})",
            )

        if arch_norm in ("z80", "sm83", "gb"):
            if len(inst_bytes) < 2:
                raise ValueError("Z80 branch instruction requires at least 2 bytes")
            op = inst_bytes[0]
            mnemonic = self.BRANCH_OPCODES_Z80.get(op, f"JR_{op:02X}")
            disp, valid = self.calc_displacement_z80(new_pc, target_addr)
            new_bytes = bytes([op, disp & 0xFF])
            return BranchRelocation(
                offset=0,
                arch=arch_norm,
                mnemonic=mnemonic,
                orig_pc=orig_pc,
                new_pc=new_pc,
                target_addr=target_addr,
                orig_bytes=inst_bytes[:2],
                new_bytes=new_bytes,
                displacement=disp,
                in_range=valid,
                description=f"{mnemonic} to 0x{target_addr:04X} (disp: {disp})",
            )

        if arch_norm in ("m68k", "genesis", "md"):
            if len(inst_bytes) < 2:
                raise ValueError("M68K branch requires at least 2 bytes")
            op_hi = inst_bytes[0]
            op_lo = inst_bytes[1]
            if (op_hi & 0xF0) != 0x60:
                raise ValueError(f"Not an M68K branch instruction: 0x{op_hi:02X}{op_lo:02X}")

            mnemonic = "BSR" if op_hi == 0x61 else ("BRA" if op_hi == 0x60 else f"Bcc_{op_hi & 0x0F:X}")
            if op_lo != 0:
                disp, valid = self.calc_displacement_m68k_8bit(new_pc, target_addr)
                new_bytes = bytes([op_hi, disp & 0xFF])
                return BranchRelocation(
                    offset=0,
                    arch=arch_norm,
                    mnemonic=f"{mnemonic}.s",
                    orig_pc=orig_pc,
                    new_pc=new_pc,
                    target_addr=target_addr,
                    orig_bytes=inst_bytes[:2],
                    new_bytes=new_bytes,
                    displacement=disp,
                    in_range=valid,
                    description=f"{mnemonic}.s to 0x{target_addr:06X} (disp: {disp})",
                )
            if len(inst_bytes) < 4:
                raise ValueError("M68K 16-bit branch requires 4 bytes")
            disp, valid = self.calc_displacement_m68k_16bit(new_pc, target_addr)
            new_bytes = bytes([op_hi, 0x00]) + struct.pack(">h", disp if valid else 0)
            return BranchRelocation(
                offset=0,
                arch=arch_norm,
                mnemonic=f"{mnemonic}.w",
                orig_pc=orig_pc,
                new_pc=new_pc,
                target_addr=target_addr,
                orig_bytes=inst_bytes[:4],
                new_bytes=new_bytes,
                displacement=disp,
                in_range=valid,
                description=f"{mnemonic}.w to 0x{target_addr:06X} (disp: {disp})",
            )

        if arch_norm == "arm":
            if len(inst_bytes) < 4:
                raise ValueError("ARM instruction requires 4 bytes")
            raw_val = struct.unpack("<I", inst_bytes[:4])[0]
            cond = (raw_val >> 28) & 0x0F
            is_bl = (raw_val >> 24) & 1
            mnemonic = "BL" if is_bl else "B"
            imm24, valid = self.calc_displacement_arm(new_pc, target_addr)
            new_val = (cond << 28) | (0b101 << 25) | (is_bl << 24) | (imm24 & 0x00FFFFFF)
            new_bytes = struct.pack("<I", new_val)
            return BranchRelocation(
                offset=0,
                arch=arch_norm,
                mnemonic=mnemonic,
                orig_pc=orig_pc,
                new_pc=new_pc,
                target_addr=target_addr,
                orig_bytes=inst_bytes[:4],
                new_bytes=new_bytes,
                displacement=imm24 << 2,
                in_range=valid,
                description=f"{mnemonic} to 0x{target_addr:08X}",
            )

        if arch_norm == "thumb":
            if len(inst_bytes) < 2:
                raise ValueError("Thumb instruction requires at least 2 bytes")
            raw_val = struct.unpack("<H", inst_bytes[:2])[0]
            if (raw_val & 0xF000) == 0xD000 and (raw_val & 0x0F00) != 0x0F00:
                imm8, valid = self.calc_displacement_thumb_cond(new_pc, target_addr)
                new_val = (raw_val & 0xFF00) | (imm8 & 0xFF)
                new_bytes = struct.pack("<H", new_val)
                return BranchRelocation(
                    offset=0,
                    arch=arch_norm,
                    mnemonic="B<cond>",
                    orig_pc=orig_pc,
                    new_pc=new_pc,
                    target_addr=target_addr,
                    orig_bytes=inst_bytes[:2],
                    new_bytes=new_bytes,
                    displacement=imm8 << 1,
                    in_range=valid,
                    description=f"B<cond> to 0x{target_addr:08X}",
                )
            if (raw_val & 0xF800) == 0xE000:
                imm11, valid = self.calc_displacement_thumb_uncond(new_pc, target_addr)
                new_val = 0xE000 | (imm11 & 0x7FF)
                new_bytes = struct.pack("<H", new_val)
                return BranchRelocation(
                    offset=0,
                    arch=arch_norm,
                    mnemonic="B",
                    orig_pc=orig_pc,
                    new_pc=new_pc,
                    target_addr=target_addr,
                    orig_bytes=inst_bytes[:2],
                    new_bytes=new_bytes,
                    displacement=imm11 << 1,
                    in_range=valid,
                    description=f"B to 0x{target_addr:08X}",
                )
            if (raw_val & 0xF800) == 0xF000 and len(inst_bytes) >= 4:
                raw_val2 = struct.unpack("<H", inst_bytes[2:4])[0]
                delta = target_addr - (new_pc + 4)
                valid = -0x400000 <= delta <= 0x3FFFFE and (delta % 2 == 0)
                inst1 = 0xF000 | ((delta >> 12) & 0x7FF)
                inst2 = 0xF800 | ((delta >> 1) & 0x7FF)
                new_bytes = struct.pack("<HH", inst1, inst2)
                return BranchRelocation(
                    offset=0,
                    arch=arch_norm,
                    mnemonic="BL",
                    orig_pc=orig_pc,
                    new_pc=new_pc,
                    target_addr=target_addr,
                    orig_bytes=inst_bytes[:4],
                    new_bytes=new_bytes,
                    displacement=delta,
                    in_range=valid,
                    description=f"BL to 0x{target_addr:08X}",
                )
            raise ValueError(f"Unrecognized Thumb branch instruction: 0x{raw_val:04X}")

        if arch_norm == "mips":
            if len(inst_bytes) < 4:
                raise ValueError("MIPS branch requires 4 bytes")
            raw_val = struct.unpack(">I", inst_bytes[:4])[0]
            opcode = (raw_val >> 26) & 0x3F
            word_offset, valid = self.calc_displacement_mips_branch(new_pc, target_addr)
            new_val = (raw_val & 0xFFFF0000) | (word_offset & 0xFFFF)
            new_bytes = struct.pack(">I", new_val)
            return BranchRelocation(
                offset=0,
                arch=arch_norm,
                mnemonic=f"BRANCH_OP_{opcode:02X}",
                orig_pc=orig_pc,
                new_pc=new_pc,
                target_addr=target_addr,
                orig_bytes=inst_bytes[:4],
                new_bytes=new_bytes,
                displacement=word_offset << 2,
                in_range=valid,
                description=f"MIPS branch to 0x{target_addr:08X}",
            )

        raise ValueError(f"Unsupported architecture for branch patching: '{arch}'")

    def rebase_block(
        self,
        code: bytes,
        orig_base: int,
        new_base: int,
        arch: str,
        external_targets: Optional[Dict[int, int]] = None,
    ) -> Tuple[bytes, List[BranchRelocation]]:
        """
        Inspects and rebases all PC-relative branches within a code block relocated from
        orig_base to new_base.

        Branches with internal targets within the block retain their relative displacement
        because source and target shift equally.
        Branches with external targets are adjusted so their destination remains at target_addr
        or its remapped address in external_targets.
        """
        arch_norm = arch.lower().strip()
        result_buf = bytearray(code)
        relocs: List[BranchRelocation] = []
        ext_map = external_targets or {}
        block_len = len(code)
        orig_end = orig_base + block_len

        i = 0
        if arch_norm in ("6502", "nes", "z80", "sm83", "gb"):
            opcode_map = self.BRANCH_OPCODES_6502 if arch_norm in ("6502", "nes") else self.BRANCH_OPCODES_Z80
            while i < block_len - 1:
                b = code[i]
                if b in opcode_map:
                    orig_pc = orig_base + i
                    new_pc = new_base + i
                    disp = code[i + 1]
                    target = (
                        self.resolve_target_6502(orig_pc, disp)
                        if arch_norm in ("6502", "nes")
                        else self.resolve_target_z80(orig_pc, disp)
                    )

                    is_internal = orig_base <= target < orig_end
                    if is_internal:
                        new_target = target + (new_base - orig_base)
                        item = self.patch_single_branch(code[i : i + 2], orig_pc, new_pc, new_target, arch_norm)
                    else:
                        new_target = ext_map.get(target, target)
                        item = self.patch_single_branch(code[i : i + 2], orig_pc, new_pc, new_target, arch_norm)
                        result_buf[i : i + 2] = item.new_bytes

                    item.offset = i
                    relocs.append(item)
                    i += 2
                    continue
                i += 1

        elif arch_norm in ("m68k", "genesis", "md"):
            while i < block_len - 1:
                op_hi = code[i]
                op_lo = code[i + 1]
                if (op_hi & 0xF0) == 0x60:
                    orig_pc = orig_base + i
                    new_pc = new_base + i
                    if op_lo != 0:
                        disp_s8 = op_lo if op_lo < 128 else op_lo - 256
                        target = orig_pc + 2 + disp_s8
                        is_internal = orig_base <= target < orig_end
                        new_target = target + (new_base - orig_base) if is_internal else ext_map.get(target, target)
                        item = self.patch_single_branch(code[i : i + 2], orig_pc, new_pc, new_target, arch_norm)
                        if not is_internal:
                            result_buf[i : i + 2] = item.new_bytes
                        item.offset = i
                        relocs.append(item)
                        i += 2
                        continue
                    if i + 3 < block_len:
                        disp_s16 = struct.unpack(">h", code[i + 2 : i + 4])[0]
                        target = orig_pc + 2 + disp_s16
                        is_internal = orig_base <= target < orig_end
                        new_target = target + (new_base - orig_base) if is_internal else ext_map.get(target, target)
                        item = self.patch_single_branch(code[i : i + 4], orig_pc, new_pc, new_target, arch_norm)
                        if not is_internal:
                            result_buf[i : i + 4] = item.new_bytes
                        item.offset = i
                        relocs.append(item)
                        i += 4
                        continue
                i += 2

        elif arch_norm == "arm":
            while i <= block_len - 4:
                raw_val = struct.unpack("<I", code[i : i + 4])[0]
                if (raw_val & 0x0E000000) == 0x0A000000:
                    orig_pc = orig_base + i
                    new_pc = new_base + i
                    imm24 = raw_val & 0x00FFFFFF
                    if imm24 & 0x00800000:
                        imm24 -= 0x01000000
                    target = orig_pc + 8 + (imm24 << 2)
                    is_internal = orig_base <= target < orig_end
                    new_target = target + (new_base - orig_base) if is_internal else ext_map.get(target, target)
                    item = self.patch_single_branch(code[i : i + 4], orig_pc, new_pc, new_target, arch_norm)
                    if not is_internal:
                        result_buf[i : i + 4] = item.new_bytes
                    item.offset = i
                    relocs.append(item)
                    i += 4
                    continue
                i += 4

        return bytes(result_buf), relocs
