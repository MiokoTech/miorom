"""
miorom.asm.snippet
~~~~~~~~~~~~~~~~~~
Declarative Micro-Assembly Snippet Emitter Primitive.
Enables reverse engineers to assemble small instruction sequences (ARM, MIPS)
fluently in Python without needing external toolchains (GCC/devkitARM).
"""

from __future__ import annotations

from miorom.errors import ParseError, UnsupportedFormatError

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
            raise ParseError(f"Unknown ARM register: {name}")
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
            raise ParseError(f"Unknown MIPS register: {name}")
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

    def li(self, rt: str, imm: int) -> "MipsSnippet":
        """Load 32-bit immediate (emits ADDIU or LUI + ORI)."""
        if -0x8000 <= imm <= 0x7FFF:
            return self.addiu(rt, "zero", imm)
        hi = (imm >> 16) & 0xFFFF
        lo = imm & 0xFFFF
        self.lui(rt, hi)
        if lo != 0:
            self.ori(rt, rt, lo)
        return self

    def ori(self, rt: str, rs: str, imm: int) -> "MipsSnippet":
        """Emits ORI Rt, Rs, uimm16."""
        rt_idx = self._reg(rt)
        rs_idx = self._reg(rs)
        opcode = 0x34000000 | (rs_idx << 21) | (rt_idx << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def andi(self, rt: str, rs: str, imm: int) -> "MipsSnippet":
        """Emits ANDI Rt, Rs, uimm16."""
        rt_idx = self._reg(rt)
        rs_idx = self._reg(rs)
        opcode = 0x30000000 | (rs_idx << 21) | (rt_idx << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def addu(self, rd: str, rs: str, rt: str) -> "MipsSnippet":
        """Emits ADDU Rd, Rs, Rt."""
        opcode = (self._reg(rs) << 21) | (self._reg(rt) << 16) | (self._reg(rd) << 11) | 0x21
        self._instructions.append(opcode)
        return self

    def subu(self, rd: str, rs: str, rt: str) -> "MipsSnippet":
        """Emits SUBU Rd, Rs, Rt."""
        opcode = (self._reg(rs) << 21) | (self._reg(rt) << 16) | (self._reg(rd) << 11) | 0x23
        self._instructions.append(opcode)
        return self

    def sll(self, rd: str, rt: str, sa: int) -> "MipsSnippet":
        """Emits SLL Rd, Rt, sa."""
        opcode = (self._reg(rt) << 16) | (self._reg(rd) << 11) | ((sa & 0x1F) << 6) | 0x00
        self._instructions.append(opcode)
        return self

    def srl(self, rd: str, rt: str, sa: int) -> "MipsSnippet":
        """Emits SRL Rd, Rt, sa."""
        opcode = (self._reg(rt) << 16) | (self._reg(rd) << 11) | ((sa & 0x1F) << 6) | 0x02
        self._instructions.append(opcode)
        return self

    def lw(self, rt: str, rs: str, offset: int = 0) -> "MipsSnippet":
        """Emits LW Rt, offset(Rs)."""
        opcode = 0x8C000000 | (self._reg(rs) << 21) | (self._reg(rt) << 16) | (offset & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def sw(self, rt: str, rs: str, offset: int = 0) -> "MipsSnippet":
        """Emits SW Rt, offset(Rs)."""
        opcode = 0xAC000000 | (self._reg(rs) << 21) | (self._reg(rt) << 16) | (offset & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def j(self, target_vaddr: int) -> "MipsSnippet":
        """Emits J target_vaddr."""
        opcode = 0x08000000 | ((target_vaddr >> 2) & 0x03FFFFFF)
        self._instructions.append(opcode)
        return self

    def jal(self, target_vaddr: int) -> "MipsSnippet":
        """Emits JAL target_vaddr."""
        opcode = 0x0C000000 | ((target_vaddr >> 2) & 0x03FFFFFF)
        self._instructions.append(opcode)
        return self

    def move(self, rd: str, rs: str) -> "MipsSnippet":
        """Emits MOVE Rd, Rs (ADDU Rd, Rs, $zero)."""
        return self.addu(rd, rs, "zero")

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

    @staticmethod
    def sm83() -> SM83Snippet:
        return SM83Snippet()


class SM83Snippet:
    """Fluent SM83 (Game Boy) assembly snippet builder."""

    REG_MAP: Dict[str, int] = {
        "b": 0, "c": 1, "d": 2, "e": 3, "h": 4, "l": 5, "a": 7,
    }

    def __init__(self):
        self._instructions: bytearray = bytearray()

    def _reg(self, name: str) -> int:
        clean = name.lower().strip()
        if clean not in self.REG_MAP:
            raise ParseError(f"Unknown SM83 register: {name}")
        return self.REG_MAP[clean]

    def ld_rr(self, rd: str, rh: str, rl: str) -> "SM83Snippet":
        pair = (rh.lower(), rl.lower())
        if rd.lower() == "a" and pair == ("b", "c"):
            self._instructions.append(0x0A)
        elif rd.lower() == "a" and pair == ("d", "e"):
            self._instructions.append(0x1A)
        elif rd.lower() == "a" and pair == ("h", "l"):
            self._instructions.append(0x7A)
        elif pair == ("h", "l"):
            self._instructions.append(0x40 | (self._reg(rd) << 3) | 0x06)
        else:
            raise UnsupportedFormatError("Unsupported SM83 ld_rr addressing mode")
        return self

    def ld_tr(self, rh: str, rl: str, rs: str) -> "SM83Snippet":
        if (rh.lower(), rl.lower(), rs.lower()) != ("h", "l", "a"):
            raise UnsupportedFormatError("Unsupported SM83 ld_tr addressing mode")
        self._instructions.append(0x77)
        return self

    def ld_r_n(self, rd: str, value: int) -> "SM83Snippet":
        self._instructions.extend(
            bytes((0x06 | (self._reg(rd) << 3), value & 0xFF))
        )
        return self

    def ld_a_nn(self, address: int) -> "SM83Snippet":
        self._instructions.extend(bytes((0xFA, address & 0xFF, (address >> 8) & 0xFF)))
        return self

    def inc_rp(self, pair: str) -> "SM83Snippet":
        opcodes = {"bc": 0x03, "de": 0x13, "hl": 0x23, "sp": 0x33}
        if pair.lower() not in opcodes:
            raise ParseError("Unknown SM83 register pair")
        self._instructions.append(opcodes[pair.lower()])
        return self

    def dec_rp(self, pair: str) -> "SM83Snippet":
        opcodes = {"bc": 0x0B, "de": 0x1B, "hl": 0x2B, "sp": 0x3B}
        if pair.lower() not in opcodes:
            raise ParseError("Unknown SM83 register pair")
        self._instructions.append(opcodes[pair.lower()])
        return self

    def jr_cc(self, condition: str, offset: int) -> "SM83Snippet":
        opcodes = {"nz": 0x20, "z": 0x28, "nc": 0x30, "c": 0x38}
        clean = condition.lower()
        if clean not in opcodes:
            raise ParseError("Unknown SM83 condition")
        self._instructions.extend(bytes((opcodes[clean], offset & 0xFF)))
        return self

    def jr(self, offset: int) -> "SM83Snippet":
        self._instructions.extend(bytes((0x18, offset & 0xFF)))
        return self

    def jp_hl(self) -> "SM83Snippet":
        self._instructions.append(0xE9)
        return self

    def ret(self) -> "SM83Snippet":
        self._instructions.append(0xC9)
        return self

    def di(self) -> "SM83Snippet":
        self._instructions.append(0xF3)
        return self

    def ei(self) -> "SM83Snippet":
        self._instructions.append(0xFB)
        return self

    def push(self, pair: str) -> "SM83Snippet":
        opcodes = {"bc": 0xC5, "de": 0xD5, "hl": 0xE5, "af": 0xF5}
        if pair.lower() not in opcodes:
            raise ParseError("Unknown SM83 register pair")
        self._instructions.append(opcodes[pair.lower()])
        return self

    def pop(self, pair: str) -> "SM83Snippet":
        opcodes = {"bc": 0xC1, "de": 0xD1, "hl": 0xE1, "af": 0xF1}
        if pair.lower() not in opcodes:
            raise ParseError("Unknown SM83 register pair")
        self._instructions.append(opcodes[pair.lower()])
        return self

    def call(self, address: int) -> "SM83Snippet":
        self._instructions.extend(
            bytes((0xCD, address & 0xFF, (address >> 8) & 0xFF))
        )
        return self

    def rst(self, vector: int) -> "SM83Snippet":
        if vector % 8 or vector > 0x38:
            raise ParseError("Invalid SM83 reset vector")
        self._instructions.append(0xC7 | vector)
        return self

    def xor(self, register: str) -> "SM83Snippet":
        self._instructions.append(0xA8 | self._reg(register))
        return self

    def cp(self, register: str) -> "SM83Snippet":
        self._instructions.append(0xB8 | self._reg(register))
        return self

    def ldh_a_c(self) -> "SM83Snippet":
        self._instructions.append(0xF2)
        return self

    def ldh_a_n(self, offset: int) -> "SM83Snippet":
        self._instructions.extend(bytes((0xF0, offset & 0xFF)))
        return self

    def cb(self, operation: str, register: str, bit: int) -> "SM83Snippet":
        operation_codes = {"rlc": 0x00, "rrc": 0x08, "rl": 0x10, "rr": 0x18,
                           "sla": 0x20, "sra": 0x28, "swap": 0x30, "srl": 0x38,
                           "bit": 0x40, "res": 0x90, "set": 0xC0}
        clean = operation.lower()
        if clean not in operation_codes:
            raise ParseError("Unknown SM83 CB operation")
        if not 0 <= bit <= 7:
            raise ParseError("SM83 bit index must be 0..7")
        opcode = operation_codes[clean]
        if clean in {"bit", "res", "set"}:
            opcode |= bit << 3
        self._instructions.extend(bytes((0xCB, opcode | self._reg(register))))
        return self

    def nop(self, count: int = 1) -> "SM83Snippet":
        self._instructions.extend(b"\x00" * count)
        return self

    def emit(self) -> bytes:
        return bytes(self._instructions)
