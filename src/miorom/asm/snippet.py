"""
miorom.asm.snippet
~~~~~~~~~~~~~~~~~~
Declarative Micro-Assembly Snippet Emitter Primitive.
Enables reverse engineers to assemble small instruction sequences (ARM, MIPS)
fluently in Python without needing external toolchains (GCC/devkitARM).
"""

import struct
from typing import Dict, List, Optional, Sequence, Union


class ArmSnippet:
    """Fluent ARM32 assembly snippet builder."""

    REG_MAP: Dict[str, int] = {
        "r0": 0, "r1": 1, "r2": 2, "r3": 3,
        "r4": 4, "r5": 5, "r6": 6, "r7": 7,
        "r8": 8, "r9": 9, "r10": 10, "r11": 11,
        "r12": 12, "sp": 13, "r13": 13, "lr": 14, "r14": 14,
        "pc": 15, "r15": 15,
    }

    def __init__(self, endian: str = "<"):
        self.endian = endian
        self._instructions: List[int] = []

    def _reg(self, name: str) -> int:
        clean = name.lower().strip()
        if clean not in self.REG_MAP:
            raise ValueError(f"Unknown ARM register: {name}")
        return self.REG_MAP[clean]

    def _reg_mask(self, regs: Sequence[str]) -> int:
        mask = 0
        for r in regs:
            mask |= (1 << self._reg(r))
        return mask

    def push(self, regs: Sequence[str]) -> "ArmSnippet":
        """Emits PUSH {regs} (STMDB SP!, {regs})."""
        mask = self._reg_mask(regs)
        opcode = 0xE92D0000 | mask
        self._instructions.append(opcode)
        return self

    def pop(self, regs: Sequence[str]) -> "ArmSnippet":
        """Emits POP {regs} (LDMIA SP!, {regs})."""
        mask = self._reg_mask(regs)
        opcode = 0xE8BD0000 | mask
        self._instructions.append(opcode)
        return self

    def mov_imm(self, rd: str, imm: int) -> "ArmSnippet":
        """Emits MOV Rd, #imm8."""
        rd_idx = self._reg(rd)
        opcode = 0xE3A00000 | (rd_idx << 12) | (imm & 0xFF)
        self._instructions.append(opcode)
        return self

    def add_imm(self, rd: str, rn: str, imm: int) -> "ArmSnippet":
        """Emits ADD Rd, Rn, #imm8."""
        rd_idx = self._reg(rd)
        rn_idx = self._reg(rn)
        opcode = 0xE2800000 | (rn_idx << 16) | (rd_idx << 12) | (imm & 0xFF)
        self._instructions.append(opcode)
        return self

    def sub_imm(self, rd: str, rn: str, imm: int) -> "ArmSnippet":
        """Emits SUB Rd, Rn, #imm8."""
        rd_idx = self._reg(rd)
        rn_idx = self._reg(rn)
        opcode = 0xE2400000 | (rn_idx << 16) | (rd_idx << 12) | (imm & 0xFF)
        self._instructions.append(opcode)
        return self

    def bx(self, rm: str = "lr") -> "ArmSnippet":
        """Emits BX Rm."""
        rm_idx = self._reg(rm)
        opcode = 0xE12FFF10 | rm_idx
        self._instructions.append(opcode)
        return self

    def b(self, target_vaddr: int, current_pc: int) -> "ArmSnippet":
        """Emits B target_vaddr (PC-relative branch)."""
        offset = (target_vaddr - (current_pc + 8)) >> 2
        opcode = 0xEA000000 | (offset & 0x00FFFFFF)
        self._instructions.append(opcode)
        return self

    def bl(self, target_vaddr: int, current_pc: int) -> "ArmSnippet":
        """Emits BL target_vaddr (PC-relative branch with link)."""
        offset = (target_vaddr - (current_pc + 8)) >> 2
        opcode = 0xEB000000 | (offset & 0x00FFFFFF)
        self._instructions.append(opcode)
        return self

    def nop(self, count: int = 1) -> "ArmSnippet":
        """Emits MOV r0, r0 (NOP)."""
        for _ in range(count):
            self._instructions.append(0xE1A00000)
        return self

    def emit(self) -> bytes:
        """Assembles and returns binary machine code."""
        fmt = f"{self.endian}I"
        buf = bytearray()
        for op in self._instructions:
            buf.extend(struct.pack(fmt, op))
        return bytes(buf)


class MipsSnippet:
    """Fluent MIPS assembly snippet builder."""

    REG_MAP: Dict[str, int] = {
        "zero": 0, "at": 1, "v0": 2, "v1": 3,
        "a0": 4, "a1": 5, "a2": 6, "a3": 7,
        "t0": 8, "t1": 9, "t2": 10, "t3": 11,
        "t4": 12, "t5": 13, "t6": 14, "t7": 15,
        "s0": 16, "s1": 17, "s2": 18, "s3": 19,
        "s4": 20, "s5": 21, "s6": 22, "s7": 23,
        "t8": 24, "t9": 25, "k0": 26, "k1": 27,
        "gp": 28, "sp": 29, "fp": 30, "s8": 30, "ra": 31,
    }

    def __init__(self, endian: str = ">"):
        self.endian = endian
        self._instructions: List[int] = []

    def _reg(self, name: str) -> int:
        clean = name.lower().strip().lstrip("$")
        if clean not in self.REG_MAP:
            raise ValueError(f"Unknown MIPS register: {name}")
        return self.REG_MAP[clean]

    def nop(self, count: int = 1) -> "MipsSnippet":
        """Emits MIPS NOP (sll $0, $0, 0)."""
        for _ in range(count):
            self._instructions.append(0x00000000)
        return self

    def jr_ra(self) -> "MipsSnippet":
        """Emits JR $ra (with automatic NOP in branch delay slot)."""
        self._instructions.append(0x03E00008)
        self._instructions.append(0x00000000)
        return self

    def lui(self, rt: str, imm: int) -> "MipsSnippet":
        """Emits LUI Rt, imm16."""
        rt_idx = self._reg(rt)
        opcode = 0x3C000000 | (rt_idx << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def addiu(self, rt: str, rs: str, imm: int) -> "MipsSnippet":
        """Emits ADDIU Rt, Rs, simm16."""
        rt_idx = self._reg(rt)
        rs_idx = self._reg(rs)
        opcode = 0x24000000 | (rs_idx << 21) | (rt_idx << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def emit(self) -> bytes:
        fmt = f"{self.endian}I"
        buf = bytearray()
        for op in self._instructions:
            buf.extend(struct.pack(fmt, op))
        return bytes(buf)


class AsmSnippet:
    """Factory for assembly snippet builders."""

    @staticmethod
    def arm(endian: str = "<") -> ArmSnippet:
        return ArmSnippet(endian=endian)

    @staticmethod
    def mips(endian: str = ">") -> MipsSnippet:
        return MipsSnippet(endian=endian)
