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
    def thumb(endian: str = "<") -> ThumbSnippet:
        return ThumbSnippet(endian=endian)

    @staticmethod
    def mips(endian: str = ">") -> MipsSnippet:
        return MipsSnippet(endian=endian)

    @staticmethod
    def ppc(endian: str = ">") -> PpcSnippet:
        return PpcSnippet(endian=endian)

    @staticmethod
    def sm83() -> SM83Snippet:
        return SM83Snippet()

    @staticmethod
    def snes() -> SnesSnippet:
        return SnesSnippet()

    @staticmethod
    def m68k() -> M68kSnippet:
        return M68kSnippet()

    @staticmethod
    def mos6502() -> Mos6502Snippet:
        return Mos6502Snippet()


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


class ThumbSnippet:
    """Fluent 16-bit ARM Thumb assembly snippet builder for GBA & NDS."""

    REG_MAP: Dict[str, int] = {
        "r0": 0, "r1": 1, "r2": 2, "r3": 3,
        "r4": 4, "r5": 5, "r6": 6, "r7": 7,
        "r8": 8, "r9": 9, "r10": 10, "r11": 11,
        "r12": 12, "sp": 13, "r13": 13, "lr": 14, "r14": 14,
        "pc": 15, "r15": 15,
    }

    COND_MAP: Dict[str, int] = {
        "eq": 0, "ne": 1, "cs": 2, "hs": 2, "cc": 3, "lo": 3,
        "mi": 4, "pl": 5, "vs": 6, "vc": 7, "hi": 8, "ls": 9,
        "ge": 10, "lt": 11, "gt": 12, "le": 13, "al": 14,
    }

    def __init__(self, endian: str = "<"):
        self.endian = endian
        self._instructions: List[int] = []

    def _reg(self, name: str, allow_high: bool = False) -> int:
        clean = name.lower().strip()
        if clean not in self.REG_MAP:
            raise ParseError(f"Unknown Thumb register: {name}")
        idx = self.REG_MAP[clean]
        if not allow_high and idx > 7:
            raise ParseError(f"High register {name} not permitted in low-register Thumb instruction")
        return idx

    def push(self, regs: Sequence[str]) -> "ThumbSnippet":
        """Emits PUSH {regs} (optional LR)."""
        mask = 0
        has_lr = False
        for r in regs:
            clean = r.lower().strip()
            if clean in ("lr", "r14"):
                has_lr = True
            else:
                idx = self._reg(clean, allow_high=False)
                mask |= (1 << idx)
        opcode = 0xB400 | (0x0100 if has_lr else 0) | mask
        self._instructions.append(opcode)
        return self

    def pop(self, regs: Sequence[str]) -> "ThumbSnippet":
        """Emits POP {regs} (optional PC)."""
        mask = 0
        has_pc = False
        for r in regs:
            clean = r.lower().strip()
            if clean in ("pc", "r15"):
                has_pc = True
            else:
                idx = self._reg(clean, allow_high=False)
                mask |= (1 << idx)
        opcode = 0xBC00 | (0x0100 if has_pc else 0) | mask
        self._instructions.append(opcode)
        return self

    def mov_imm(self, rd: str, imm: int) -> "ThumbSnippet":
        """Emits MOV Rd, #imm8."""
        rd_idx = self._reg(rd)
        if not 0 <= imm <= 0xFF:
            raise ParseError(f"Thumb MOV immediate 0x{imm:X} out of 8-bit range (0..255)")
        opcode = 0x2000 | (rd_idx << 8) | (imm & 0xFF)
        self._instructions.append(opcode)
        return self

    def mov_reg(self, rd: str, rs: str) -> "ThumbSnippet":
        """Emits MOV Rd, Rs (supports low and high registers)."""
        rd_idx = self._reg(rd, allow_high=True)
        rs_idx = self._reg(rs, allow_high=True)
        opcode = 0x4600 | ((rd_idx >> 3) << 7) | ((rs_idx >> 3) << 6) | ((rs_idx & 7) << 3) | (rd_idx & 7)
        self._instructions.append(opcode)
        return self

    def add_imm(self, rd: str, imm: int, rn: Optional[str] = None) -> "ThumbSnippet":
        """Emits ADD Rd, #imm8 or ADD Rd, Rn, #imm3."""
        rd_idx = self._reg(rd)
        if rn is None or rn.lower().strip() == rd.lower().strip():
            if not 0 <= imm <= 0xFF:
                raise ParseError(f"Thumb ADD immediate 0x{imm:X} out of 8-bit range")
            opcode = 0x3000 | (rd_idx << 8) | (imm & 0xFF)
        else:
            rn_idx = self._reg(rn)
            if not 0 <= imm <= 7:
                raise ParseError(f"Thumb ADD 3-reg immediate 0x{imm:X} out of 3-bit range (0..7)")
            opcode = 0x1C00 | ((imm & 7) << 6) | (rn_idx << 3) | rd_idx
        self._instructions.append(opcode)
        return self

    def sub_imm(self, rd: str, imm: int, rn: Optional[str] = None) -> "ThumbSnippet":
        """Emits SUB Rd, #imm8 or SUB Rd, Rn, #imm3."""
        rd_idx = self._reg(rd)
        if rn is None or rn.lower().strip() == rd.lower().strip():
            if not 0 <= imm <= 0xFF:
                raise ParseError(f"Thumb SUB immediate 0x{imm:X} out of 8-bit range")
            opcode = 0x3800 | (rd_idx << 8) | (imm & 0xFF)
        else:
            rn_idx = self._reg(rn)
            if not 0 <= imm <= 7:
                raise ParseError(f"Thumb SUB 3-reg immediate 0x{imm:X} out of 3-bit range (0..7)")
            opcode = 0x1E00 | ((imm & 7) << 6) | (rn_idx << 3) | rd_idx
        self._instructions.append(opcode)
        return self

    def add_reg(self, rd: str, rn: str, rm: str) -> "ThumbSnippet":
        """Emits ADD Rd, Rn, Rm."""
        rd_idx = self._reg(rd)
        rn_idx = self._reg(rn)
        rm_idx = self._reg(rm)
        opcode = 0x1800 | (rm_idx << 6) | (rn_idx << 3) | rd_idx
        self._instructions.append(opcode)
        return self

    def sub_reg(self, rd: str, rn: str, rm: str) -> "ThumbSnippet":
        """Emits SUB Rd, Rn, Rm."""
        rd_idx = self._reg(rd)
        rn_idx = self._reg(rn)
        rm_idx = self._reg(rm)
        opcode = 0x1A00 | (rm_idx << 6) | (rn_idx << 3) | rd_idx
        self._instructions.append(opcode)
        return self

    def cmp_imm(self, rn: str, imm: int) -> "ThumbSnippet":
        """Emits CMP Rn, #imm8."""
        rn_idx = self._reg(rn)
        if not 0 <= imm <= 0xFF:
            raise ParseError(f"Thumb CMP immediate 0x{imm:X} out of 8-bit range")
        opcode = 0x2800 | (rn_idx << 8) | (imm & 0xFF)
        self._instructions.append(opcode)
        return self

    def cmp_reg(self, rn: str, rm: str) -> "ThumbSnippet":
        """Emits CMP Rn, Rm (supports low and high registers)."""
        rn_idx = self._reg(rn, allow_high=True)
        rm_idx = self._reg(rm, allow_high=True)
        if rn_idx <= 7 and rm_idx <= 7:
            opcode = 0x4280 | (rm_idx << 3) | rn_idx
        else:
            opcode = 0x4500 | ((rn_idx >> 3) << 7) | ((rm_idx >> 3) << 6) | ((rm_idx & 7) << 3) | (rn_idx & 7)
        self._instructions.append(opcode)
        return self

    def ldr_imm(self, rd: str, rn: str, offset: int = 0) -> "ThumbSnippet":
        """Emits LDR Rd, [Rn, #offset] (offset must be multiple of 4, 0..124)."""
        rd_idx = self._reg(rd)
        rn_idx = self._reg(rn)
        if offset % 4 != 0 or not (0 <= offset <= 124):
            raise ParseError(f"Thumb LDR offset {offset} must be multiple of 4 in range 0..124")
        imm5 = offset >> 2
        opcode = 0x6800 | (imm5 << 6) | (rn_idx << 3) | rd_idx
        self._instructions.append(opcode)
        return self

    def str_imm(self, rd: str, rn: str, offset: int = 0) -> "ThumbSnippet":
        """Emits STR Rd, [Rn, #offset] (offset must be multiple of 4, 0..124)."""
        rd_idx = self._reg(rd)
        rn_idx = self._reg(rn)
        if offset % 4 != 0 or not (0 <= offset <= 124):
            raise ParseError(f"Thumb STR offset {offset} must be multiple of 4 in range 0..124")
        imm5 = offset >> 2
        opcode = 0x6000 | (imm5 << 6) | (rn_idx << 3) | rd_idx
        self._instructions.append(opcode)
        return self

    def ldr_pc(self, rd: str, offset: int) -> "ThumbSnippet":
        """Emits LDR Rd, [PC, #offset] (offset must be multiple of 4, 0..1020)."""
        rd_idx = self._reg(rd)
        if offset % 4 != 0 or not (0 <= offset <= 1020):
            raise ParseError(f"Thumb LDR PC offset {offset} must be multiple of 4 in range 0..1020")
        imm8 = offset >> 2
        opcode = 0x4800 | (rd_idx << 8) | imm8
        self._instructions.append(opcode)
        return self

    def ldr_sp(self, rd: str, offset: int) -> "ThumbSnippet":
        """Emits LDR Rd, [SP, #offset] (offset must be multiple of 4, 0..1020)."""
        rd_idx = self._reg(rd)
        if offset % 4 != 0 or not (0 <= offset <= 1020):
            raise ParseError(f"Thumb LDR SP offset {offset} must be multiple of 4 in range 0..1020")
        imm8 = offset >> 2
        opcode = 0x9800 | (rd_idx << 8) | imm8
        self._instructions.append(opcode)
        return self

    def str_sp(self, rd: str, offset: int) -> "ThumbSnippet":
        """Emits STR Rd, [SP, #offset] (offset must be multiple of 4, 0..1020)."""
        rd_idx = self._reg(rd)
        if offset % 4 != 0 or not (0 <= offset <= 1020):
            raise ParseError(f"Thumb STR SP offset {offset} must be multiple of 4 in range 0..1020")
        imm8 = offset >> 2
        opcode = 0x9000 | (rd_idx << 8) | imm8
        self._instructions.append(opcode)
        return self

    def b(self, target_vaddr: int, current_pc: int) -> "ThumbSnippet":
        """Emits unconditional branch B label (PC-relative)."""
        diff = target_vaddr - (current_pc + 4)
        if diff % 2 != 0:
            raise ParseError(f"Thumb target address 0x{target_vaddr:08X} is not 2-byte aligned")
        if not (-2048 <= diff <= 2046):
            raise ParseError(f"Thumb branch displacement {diff} out of range (-2048..+2046)")
        imm11 = (diff >> 1) & 0x7FF
        opcode = 0xE000 | imm11
        self._instructions.append(opcode)
        return self

    def b_cond(self, cond: str, target_vaddr: int, current_pc: int) -> "ThumbSnippet":
        """Emits conditional branch B{cond} label."""
        clean = cond.lower().strip()
        if clean not in self.COND_MAP:
            raise ParseError(f"Unknown Thumb condition code: {cond}")
        cond_code = self.COND_MAP[clean]
        diff = target_vaddr - (current_pc + 4)
        if diff % 2 != 0:
            raise ParseError(f"Thumb target address 0x{target_vaddr:08X} is not 2-byte aligned")
        if not (-256 <= diff <= 254):
            raise ParseError(f"Thumb conditional branch displacement {diff} out of range (-256..+254)")
        imm8 = (diff >> 1) & 0xFF
        opcode = 0xD000 | (cond_code << 8) | imm8
        self._instructions.append(opcode)
        return self

    def bl(self, target_vaddr: int, current_pc: int) -> "ThumbSnippet":
        """Emits 32-bit BL target_vaddr (two 16-bit halfwords)."""
        diff = target_vaddr - (current_pc + 4)
        if diff % 2 != 0:
            raise ParseError(f"Thumb BL target address 0x{target_vaddr:08X} is not 2-byte aligned")
        offset22 = diff >> 1
        hi_11 = (offset22 >> 11) & 0x7FF
        lo_11 = offset22 & 0x7FF
        self._instructions.append(0xF000 | hi_11)
        self._instructions.append(0xF800 | lo_11)
        return self

    def bx(self, rm: str = "lr") -> "ThumbSnippet":
        """Emits BX Rm."""
        rm_idx = self._reg(rm, allow_high=True)
        opcode = 0x4700 | (rm_idx << 3)
        self._instructions.append(opcode)
        return self

    def blx(self, rm: str) -> "ThumbSnippet":
        """Emits BLX Rm."""
        rm_idx = self._reg(rm, allow_high=True)
        opcode = 0x4780 | (rm_idx << 3)
        self._instructions.append(opcode)
        return self

    def nop(self, count: int = 1) -> "ThumbSnippet":
        """Emits Thumb NOP (mov r8, r8 = 0x46C0)."""
        for _ in range(count):
            self._instructions.append(0x46C0)
        return self

    def emit(self) -> bytes:
        fmt = f"{self.endian}H"
        buf = bytearray()
        for op in self._instructions:
            buf.extend(struct.pack(fmt, op))
        return bytes(buf)


class PpcSnippet:
    """Fluent PowerPC 32-bit assembly snippet builder for GameCube & Wii."""

    REG_MAP: Dict[str, int] = {
        f"r{i}": i for i in range(32)
    }
    REG_MAP.update({
        "sp": 1, "r1": 1, "rtoc": 2, "r2": 2,
    })

    def __init__(self, endian: str = ">"):
        self.endian = endian
        self._instructions: List[int] = []

    def _reg(self, name: str) -> int:
        clean = name.lower().strip()
        if clean not in self.REG_MAP:
            raise ParseError(f"Unknown PowerPC register: {name}")
        return self.REG_MAP[clean]

    def nop(self, count: int = 1) -> "PpcSnippet":
        """Emits PowerPC NOP (ori r0, r0, 0 = 0x60000000)."""
        for _ in range(count):
            self._instructions.append(0x60000000)
        return self

    def blr(self) -> "PpcSnippet":
        """Emits BLR (branch to Link Register: 0x4E800020)."""
        self._instructions.append(0x4E800020)
        return self

    def b(self, target_vaddr: int, current_pc: int) -> "PpcSnippet":
        """Emits relative B target_vaddr."""
        diff = target_vaddr - current_pc
        if diff % 4 != 0:
            raise ParseError(f"PowerPC branch target 0x{target_vaddr:08X} is not 4-byte aligned")
        li24 = (diff >> 2) & 0x00FFFFFF
        opcode = (18 << 26) | (li24 << 2)
        self._instructions.append(opcode)
        return self

    def bl(self, target_vaddr: int, current_pc: int) -> "PpcSnippet":
        """Emits relative BL target_vaddr (Branch with Link)."""
        diff = target_vaddr - current_pc
        if diff % 4 != 0:
            raise ParseError(f"PowerPC branch target 0x{target_vaddr:08X} is not 4-byte aligned")
        li24 = (diff >> 2) & 0x00FFFFFF
        opcode = (18 << 26) | (li24 << 2) | 1
        self._instructions.append(opcode)
        return self

    def addi(self, rt: str, ra: str, imm: int) -> "PpcSnippet":
        """Emits ADDI Rt, Ra, simm16."""
        rt_idx = self._reg(rt)
        ra_idx = self._reg(ra)
        opcode = (14 << 26) | (rt_idx << 21) | (ra_idx << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def lis(self, rt: str, imm: int) -> "PpcSnippet":
        """Emits LIS Rt, imm16 (addis Rt, 0, imm16)."""
        rt_idx = self._reg(rt)
        opcode = (15 << 26) | (rt_idx << 21) | (0 << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def ori(self, ra: str, rs: str, imm: int) -> "PpcSnippet":
        """Emits ORI Ra, Rs, uimm16."""
        ra_idx = self._reg(ra)
        rs_idx = self._reg(rs)
        opcode = (24 << 26) | (rs_idx << 21) | (ra_idx << 16) | (imm & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def li(self, rt: str, imm: int) -> "PpcSnippet":
        """Load 32-bit immediate (emits ADDI or LIS + ORI)."""
        if -0x8000 <= imm <= 0x7FFF:
            return self.addi(rt, "r0", imm)
        hi = (imm >> 16) & 0xFFFF
        lo = imm & 0xFFFF
        self.lis(rt, hi)
        if lo != 0:
            self.ori(rt, rt, lo)
        return self

    def mr(self, ra: str, rs: str) -> "PpcSnippet":
        """Emits MR Ra, Rs (or Ra, Rs, Rs)."""
        ra_idx = self._reg(ra)
        rs_idx = self._reg(rs)
        opcode = (31 << 26) | (rs_idx << 21) | (ra_idx << 16) | (rs_idx << 11) | (444 << 1)
        self._instructions.append(opcode)
        return self

    def lwz(self, rd: str, offset: int, ra: str) -> "PpcSnippet":
        """Emits LWZ Rd, offset(Ra)."""
        rd_idx = self._reg(rd)
        ra_idx = self._reg(ra)
        opcode = (32 << 26) | (rd_idx << 21) | (ra_idx << 16) | (offset & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def stw(self, rs: str, offset: int, ra: str) -> "PpcSnippet":
        """Emits STW Rs, offset(Ra)."""
        rs_idx = self._reg(rs)
        ra_idx = self._reg(ra)
        opcode = (36 << 26) | (rs_idx << 21) | (ra_idx << 16) | (offset & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def stwu(self, rs: str, offset: int, ra: str) -> "PpcSnippet":
        """Emits STWU Rs, offset(Ra) (Store Word with Update, e.g. stwu r1, -0x20(r1))."""
        rs_idx = self._reg(rs)
        ra_idx = self._reg(ra)
        opcode = (37 << 26) | (rs_idx << 21) | (ra_idx << 16) | (offset & 0xFFFF)
        self._instructions.append(opcode)
        return self

    def mflr(self, rd: str) -> "PpcSnippet":
        """Emits MFLR Rd (Move From Link Register: mfspr Rd, 8)."""
        rd_idx = self._reg(rd)
        opcode = 0x7C0802A6 | (rd_idx << 21)
        self._instructions.append(opcode)
        return self

    def mtlr(self, rd: str) -> "PpcSnippet":
        """Emits MTLR Rd (Move To Link Register: mtspr 8, Rd)."""
        rd_idx = self._reg(rd)
        opcode = 0x7C0803A6 | (rd_idx << 21)
        self._instructions.append(opcode)
        return self

    def emit(self) -> bytes:
        fmt = f"{self.endian}I"
        buf = bytearray()
        for op in self._instructions:
            buf.extend(struct.pack(fmt, op))
        return bytes(buf)


class SnesSnippet:
    """Fluent W65C816 (SNES) assembly snippet builder."""

    def __init__(self):
        self._instructions: bytearray = bytearray()

    def nop(self, count: int = 1) -> "SnesSnippet":
        self._instructions.extend(b"\xEA" * count)
        return self

    def clc(self) -> "SnesSnippet":
        self._instructions.append(0x18)
        return self

    def sec(self) -> "SnesSnippet":
        self._instructions.append(0x38)
        return self

    def sei(self) -> "SnesSnippet":
        self._instructions.append(0x78)
        return self

    def cli(self) -> "SnesSnippet":
        self._instructions.append(0x58)
        return self

    def rep(self, flags: int) -> "SnesSnippet":
        """Reset Processor Status Bits (REP #$flags)."""
        self._instructions.extend([0xC2, flags & 0xFF])
        return self

    def sep(self, flags: int) -> "SnesSnippet":
        """Set Processor Status Bits (SEP #$flags)."""
        self._instructions.extend([0xE2, flags & 0xFF])
        return self

    def pha(self) -> "SnesSnippet":
        self._instructions.append(0x48)
        return self

    def pla(self) -> "SnesSnippet":
        self._instructions.append(0x68)
        return self

    def phx(self) -> "SnesSnippet":
        self._instructions.append(0xDA)
        return self

    def plx(self) -> "SnesSnippet":
        self._instructions.append(0xFA)
        return self

    def phy(self) -> "SnesSnippet":
        self._instructions.append(0x5A)
        return self

    def ply(self) -> "SnesSnippet":
        self._instructions.append(0x7A)
        return self

    def php(self) -> "SnesSnippet":
        self._instructions.append(0x08)
        return self

    def plp(self) -> "SnesSnippet":
        self._instructions.append(0x28)
        return self

    def phb(self) -> "SnesSnippet":
        self._instructions.append(0x8B)
        return self

    def plb(self) -> "SnesSnippet":
        self._instructions.append(0xAB)
        return self

    def phd(self) -> "SnesSnippet":
        self._instructions.append(0x0B)
        return self

    def pld(self) -> "SnesSnippet":
        self._instructions.append(0x2B)
        return self

    def phk(self) -> "SnesSnippet":
        self._instructions.append(0x4B)
        return self

    def lda_imm(self, val: int, is_16bit: bool = False) -> "SnesSnippet":
        if is_16bit:
            self._instructions.extend([0xA9, val & 0xFF, (val >> 8) & 0xFF])
        else:
            self._instructions.extend([0xA9, val & 0xFF])
        return self

    def lda_dp(self, offset: int) -> "SnesSnippet":
        self._instructions.extend([0xA5, offset & 0xFF])
        return self

    def lda_addr(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0xAD, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def lda_long(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0xAF, addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF])
        return self

    def sta_dp(self, offset: int) -> "SnesSnippet":
        self._instructions.extend([0x85, offset & 0xFF])
        return self

    def sta_addr(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x8D, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def sta_long(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x8F, addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF])
        return self

    def ldx_imm(self, val: int, is_16bit: bool = False) -> "SnesSnippet":
        if is_16bit:
            self._instructions.extend([0xA2, val & 0xFF, (val >> 8) & 0xFF])
        else:
            self._instructions.extend([0xA2, val & 0xFF])
        return self

    def ldy_imm(self, val: int, is_16bit: bool = False) -> "SnesSnippet":
        if is_16bit:
            self._instructions.extend([0xA0, val & 0xFF, (val >> 8) & 0xFF])
        else:
            self._instructions.extend([0xA0, val & 0xFF])
        return self

    def stx_addr(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x8E, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def sty_addr(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x8C, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def jsr(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x20, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def jsl(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x22, addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF])
        return self

    def rts(self) -> "SnesSnippet":
        self._instructions.append(0x60)
        return self

    def rtl(self) -> "SnesSnippet":
        self._instructions.append(0x6B)
        return self

    def jmp(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x4C, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def jml(self, addr: int) -> "SnesSnippet":
        self._instructions.extend([0x5C, addr & 0xFF, (addr >> 8) & 0xFF, (addr >> 16) & 0xFF])
        return self

    def bra(self, offset: int) -> "SnesSnippet":
        self._instructions.extend([0x80, offset & 0xFF])
        return self

    def emit(self) -> bytes:
        return bytes(self._instructions)


class M68kSnippet:
    """Fluent Motorola 68000 assembly snippet builder for Sega Genesis / Mega Drive."""

    def __init__(self):
        self._instructions: List[int] = []

    def _reg(self, name: str) -> Tuple[int, int]:
        clean = name.lower().strip()
        if clean == "sp":
            return (1, 7)
        if clean.startswith("d") and clean[1:].isdigit():
            idx = int(clean[1:])
            if 0 <= idx <= 7:
                return (0, idx)
        if clean.startswith("a") and clean[1:].isdigit():
            idx = int(clean[1:])
            if 0 <= idx <= 7:
                return (1, idx)
        raise ParseError(f"Unknown M68K register: {name}")

    def nop(self) -> "M68kSnippet":
        self._instructions.append(0x4E71)
        return self

    def rts(self) -> "M68kSnippet":
        self._instructions.append(0x4E75)
        return self

    def rte(self) -> "M68kSnippet":
        self._instructions.append(0x4E73)
        return self

    def rtr(self) -> "M68kSnippet":
        self._instructions.append(0x4E77)
        return self

    def illegal(self) -> "M68kSnippet":
        self._instructions.append(0x4AFC)
        return self

    def trap(self, vector: int) -> "M68kSnippet":
        self._instructions.append(0x4E40 | (vector & 0xF))
        return self

    def moveq(self, reg: str, imm: int) -> "M68kSnippet":
        mode, r = self._reg(reg)
        if mode != 0:
            raise ParseError(f"MOVEQ target must be a data register (D0-D7), got {reg}")
        self._instructions.append(0x7000 | (r << 9) | (imm & 0xFF))
        return self

    def move_imm(self, dst: str, imm: int, size: str = "w") -> "M68kSnippet":
        mode, r = self._reg(dst)
        size = size.lower()
        if size == "l" and mode == 0 and -128 <= imm <= 127:
            return self.moveq(dst, imm)

        size_code = {"b": 1, "w": 3, "l": 2}.get(size)
        if size_code is None:
            raise ParseError(f"Invalid M68K size: {size}")

        dst_bits = (r << 9) | (mode << 6)
        opcode = (size_code << 12) | dst_bits | 0x3C
        self._instructions.append(opcode)

        if size == "l":
            self._instructions.append((imm >> 16) & 0xFFFF)
            self._instructions.append(imm & 0xFFFF)
        elif size == "w":
            self._instructions.append(imm & 0xFFFF)
        else:
            self._instructions.append(imm & 0xFF)
        return self

    def move_reg(self, src: str, dst: str, size: str = "w") -> "M68kSnippet":
        s_mode, s_reg = self._reg(src)
        d_mode, d_reg = self._reg(dst)
        size = size.lower()
        size_code = {"b": 1, "w": 3, "l": 2}.get(size)
        if size_code is None:
            raise ParseError(f"Invalid M68K size: {size}")

        dst_bits = (d_reg << 9) | (d_mode << 6)
        src_bits = (s_mode << 3) | s_reg
        opcode = (size_code << 12) | dst_bits | src_bits
        self._instructions.append(opcode)
        return self

    def lea(self, addr: int, dst: str) -> "M68kSnippet":
        mode, r = self._reg(dst)
        if mode != 1:
            raise ParseError(f"LEA target must be an address register (A0-A7), got {dst}")
        opcode = 0x41F9 | (r << 9)
        self._instructions.append(opcode)
        self._instructions.append((addr >> 16) & 0xFFFF)
        self._instructions.append(addr & 0xFFFF)
        return self

    def jmp(self, addr: int) -> "M68kSnippet":
        self._instructions.append(0x4EF9)
        self._instructions.append((addr >> 16) & 0xFFFF)
        self._instructions.append(addr & 0xFFFF)
        return self

    def jsr(self, addr: int) -> "M68kSnippet":
        self._instructions.append(0x4EB9)
        self._instructions.append((addr >> 16) & 0xFFFF)
        self._instructions.append(addr & 0xFFFF)
        return self

    def bra(self, disp: int) -> "M68kSnippet":
        if -128 <= disp <= 127 and disp != 0:
            self._instructions.append(0x6000 | (disp & 0xFF))
        else:
            self._instructions.append(0x6000)
            self._instructions.append(disp & 0xFFFF)
        return self

    def bsr(self, disp: int) -> "M68kSnippet":
        if -128 <= disp <= 127 and disp != 0:
            self._instructions.append(0x6100 | (disp & 0xFF))
        else:
            self._instructions.append(0x6100)
            self._instructions.append(disp & 0xFFFF)
        return self

    def emit(self) -> bytes:
        out = bytearray()
        for word in self._instructions:
            out.extend(struct.pack(">H", word & 0xFFFF))
        return bytes(out)


class Mos6502Snippet:
    """Fluent MOS 6502 assembly snippet builder for NES / Famicom."""

    def __init__(self):
        self._instructions: List[int] = []

    def nop(self) -> "Mos6502Snippet":
        self._instructions.append(0xEA)
        return self

    def lda_imm(self, val: int) -> "Mos6502Snippet":
        self._instructions.extend([0xA9, val & 0xFF])
        return self

    def lda_zp(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0xA5, addr & 0xFF])
        return self

    def lda_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0xAD, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def sta_zp(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x85, addr & 0xFF])
        return self

    def sta_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x8D, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def ldx_imm(self, val: int) -> "Mos6502Snippet":
        self._instructions.extend([0xA2, val & 0xFF])
        return self

    def ldx_zp(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0xA6, addr & 0xFF])
        return self

    def ldx_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0xAE, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def stx_zp(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x86, addr & 0xFF])
        return self

    def stx_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x8E, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def ldy_imm(self, val: int) -> "Mos6502Snippet":
        self._instructions.extend([0xA0, val & 0xFF])
        return self

    def ldy_zp(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0xA4, addr & 0xFF])
        return self

    def ldy_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0xAC, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def sty_zp(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x84, addr & 0xFF])
        return self

    def sty_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x8C, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def tax(self) -> "Mos6502Snippet":
        self._instructions.append(0xAA)
        return self

    def tay(self) -> "Mos6502Snippet":
        self._instructions.append(0xA8)
        return self

    def txa(self) -> "Mos6502Snippet":
        self._instructions.append(0x8A)
        return self

    def tya(self) -> "Mos6502Snippet":
        self._instructions.append(0x98)
        return self

    def pha(self) -> "Mos6502Snippet":
        self._instructions.append(0x48)
        return self

    def pla(self) -> "Mos6502Snippet":
        self._instructions.append(0x68)
        return self

    def php(self) -> "Mos6502Snippet":
        self._instructions.append(0x08)
        return self

    def plp(self) -> "Mos6502Snippet":
        self._instructions.append(0x28)
        return self

    def jsr(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x20, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def rts(self) -> "Mos6502Snippet":
        self._instructions.append(0x60)
        return self

    def jmp_abs(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x4C, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def jmp_ind(self, addr: int) -> "Mos6502Snippet":
        self._instructions.extend([0x6C, addr & 0xFF, (addr >> 8) & 0xFF])
        return self

    def bne(self, offset: int) -> "Mos6502Snippet":
        self._instructions.extend([0xD0, offset & 0xFF])
        return self

    def beq(self, offset: int) -> "Mos6502Snippet":
        self._instructions.extend([0xF0, offset & 0xFF])
        return self

    def clc(self) -> "Mos6502Snippet":
        self._instructions.append(0x18)
        return self

    def sec(self) -> "Mos6502Snippet":
        self._instructions.append(0x38)
        return self

    def cli(self) -> "Mos6502Snippet":
        self._instructions.append(0x58)
        return self

    def sei(self) -> "Mos6502Snippet":
        self._instructions.append(0x78)
        return self

    def emit(self) -> bytes:
        return bytes(self._instructions)
