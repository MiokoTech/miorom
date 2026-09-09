from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


from miorom.errors import UnsupportedFormatError
@dataclass
class DisasmInstruction(MioRomResult):
    address: int
    raw_bytes: bytes
    mnemonic: str
    operands: List[str] = field(default_factory=list)
    target_address: Optional[int] = None
    is_branch: bool = False
    is_call: bool = False
    is_return: bool = False
    is_conditional: bool = False
    comment: Optional[str] = None

    @property
    def size(self) -> int:
        return len(self.raw_bytes)

    @property
    def disassembly(self) -> str:
        return self.to_string()

    def to_string(self, symbols: Optional[Dict[int, str]] = None) -> str:
        ops_str = ", ".join(self.operands)
        target_sym = ""
        if self.target_address is not None and symbols and self.target_address in symbols:
            target_sym = f" <{symbols[self.target_address]}>"
        elif self.target_address is not None:
            target_sym = f" <0x{self.target_address:08X}>"

        comment_str = f"  ; {self.comment}" if self.comment else ""
        return f"0x{self.address:08X}:  {self.mnemonic:<8} {ops_str}{target_sym}{comment_str}".rstrip()


class _DisassembleDescriptor:
    def __get__(self, instance, owner):
        if instance is not None:
            def _instance_disassemble(
                data: bytes,
                base_address: int = 0,
                arch: Optional[str] = None,
                endian: Optional[str] = None,
                max_instructions: Optional[int] = None,
            ) -> List[DisasmInstruction]:
                target_arch = arch or instance.arch
                target_endian = endian or instance.endian
                return owner._disassemble_impl(
                    data=data,
                    base_address=base_address,
                    arch=target_arch,
                    endian=target_endian,
                    max_instructions=max_instructions,
                )
            return _instance_disassemble
        else:
            def _class_disassemble(
                data: bytes,
                base_address: int = 0,
                arch: str = "ppc",
                endian: Optional[str] = None,
                max_instructions: Optional[int] = None,
            ) -> List[DisasmInstruction]:
                return owner._disassemble_impl(
                    data=data,
                    base_address=base_address,
                    arch=arch,
                    endian=endian,
                    max_instructions=max_instructions,
                )
            return _class_disassemble


class UniversalDisassembler:
    """
    Multi-architecture instruction disassembler supporting PowerPC, ARM, Thumb, and MIPS.
    Parses instruction bitfields into structured DisasmInstruction objects with target resolution.
    """

    disassemble = _DisassembleDescriptor()

    def __init__(self, arch: str = "ppc", endian: Optional[str] = None):
        self.arch = arch
        self.endian = endian

    @classmethod
    def disassemble_instruction(
        cls,
        address: int,
        raw_bytes: bytes,
        arch: str = "ppc",
        endian: Optional[str] = None,
    ) -> DisasmInstruction:
        arch_norm = arch.lower()
        end_char = "<"
        if endian:
            e_norm = endian.lower().strip()
            if e_norm in (">", "big", "be"):
                end_char = ">"
            elif e_norm in ("<", "little", "le"):
                end_char = "<"
            else:
                end_char = endian
        elif "mips" in arch_norm or arch_norm in ("psx", "n64", "psp"):
            end_char = ">" if "be" in arch_norm or arch_norm == "n64" else "<"

        if arch_norm in ("ppc", "powerpc", "wii", "gc"):
            return cls._disasm_ppc(address, raw_bytes)
        elif arch_norm in ("arm", "arm32", "gba_arm", "nds_arm"):
            return cls._disasm_arm(address, raw_bytes, end_char)
        elif arch_norm in ("thumb", "arm_thumb"):
            return cls._disasm_thumb(address, raw_bytes, end_char)
        elif "mips" in arch_norm or arch_norm in ("psx", "n64", "psp"):
            return cls._disasm_mips(address, raw_bytes, end_char)
        elif arch_norm in ("sm83", "gb", "gbc", "gameboy"):
            return cls._disasm_sm83(address, raw_bytes)
        elif arch_norm in ("m68k", "68000", "md", "genesis", "megadrive"):
            return cls._disasm_m68k(address, raw_bytes)
        else:
            raise UnsupportedFormatError(f"Unsupported architecture: '{arch}'")

    @classmethod
    def _disasm_ppc(cls, address: int, data: bytes) -> DisasmInstruction:
        if len(data) < 4:
            return DisasmInstruction(address, data, ".byte", [f"0x{b:02X}" for b in data])

        instr = struct.unpack(">I", data[:4])[0]
        raw = data[:4]
        opcode = (instr >> 26) & 0x3F

        # Special NOP check (ori 0, 0, 0)
        if instr == 0x60000000:
            return DisasmInstruction(address, raw, "nop")

        # blr (bclr 20, 0)
        if instr == 0x4E800020:
            return DisasmInstruction(address, raw, "blr", is_return=True)

        # bctr (bcctr 20, 0)
        if instr == 0x4E800420:
            return DisasmInstruction(address, raw, "bctr", is_branch=True)

        # bctrl (bcctrl 20, 0)
        if instr == 0x4E800421:
            return DisasmInstruction(address, raw, "bctrl", is_branch=True, is_call=True)

        # cmpli / cmplwi (opcode 10)
        if opcode == 10:
            ra = (instr >> 16) & 0x1F
            uimm = instr & 0xFFFF
            return DisasmInstruction(address, raw, "cmplwi", [f"r{ra}", str(uimm)])

        # cmpi / cmpwi (opcode 11)
        if opcode == 11:
            ra = (instr >> 16) & 0x1F
            simm = struct.unpack(">h", struct.pack(">H", instr & 0xFFFF))[0]
            return DisasmInstruction(address, raw, "cmpwi", [f"r{ra}", str(simm)])

        # Branch unconditional (opcode 18: b, bl, ba, bla)
        if opcode == 18:
            li24 = (instr >> 2) & 0x00FFFFFF
            aa = bool((instr >> 1) & 1)
            lk = bool(instr & 1)

            # Sign extend 24 bits
            if li24 & 0x00800000:
                diff = li24 - 0x01000000
            else:
                diff = li24
            diff <<= 2

            target = (diff if aa else address + diff) & 0xFFFFFFFF
            mnem = "bl" if lk else "b"
            if aa:
                mnem += "a"

            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnem,
                operands=[f"0x{target:08X}"],
                target_address=target,
                is_branch=True,
                is_call=lk,
                is_conditional=False,
            )

        # Conditional branch (opcode 16: bc, bcl, bca, bcla)
        if opcode == 16:
            bo = (instr >> 21) & 0x1F
            bi = (instr >> 16) & 0x1F
            bd14 = (instr >> 2) & 0x3FFF
            aa = bool((instr >> 1) & 1)
            lk = bool(instr & 1)

            if bd14 & 0x2000:
                diff = bd14 - 0x4000
            else:
                diff = bd14
            diff <<= 2

            target = (diff if aa else address + diff) & 0xFFFFFFFF
            mnem = "bcl" if lk else "bc"
            if aa:
                mnem += "a"

            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnem,
                operands=[str(bo), str(bi), f"0x{target:08X}"],
                target_address=target,
                is_branch=True,
                is_call=lk,
                is_conditional=True,
            )

        # addi (opcode 14) / addis (opcode 15: lis when rA == 0)
        if opcode in (14, 15):
            rt = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            simm = struct.unpack(">h", struct.pack(">H", instr & 0xFFFF))[0]

            if opcode == 15 and ra == 0:
                return DisasmInstruction(address, raw, "lis", [f"r{rt}", f"0x{simm & 0xFFFF:04X}"])
            elif opcode == 14 and ra == 0:
                return DisasmInstruction(address, raw, "li", [f"r{rt}", str(simm)])
            else:
                mnem = "addis" if opcode == 15 else "addi"
                return DisasmInstruction(address, raw, mnem, [f"r{rt}", f"r{ra}", str(simm)])

        # ori (opcode 24)
        if opcode == 24:
            rs = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            uimm = instr & 0xFFFF
            return DisasmInstruction(address, raw, "ori", [f"r{ra}", f"r{rs}", f"0x{uimm:04X}"])

        # Load / Store words (lwz=32, stw=36)
        if opcode in (32, 36):
            rt = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            d = struct.unpack(">h", struct.pack(">H", instr & 0xFFFF))[0]
            mnem = "lwz" if opcode == 32 else "stw"
            return DisasmInstruction(address, raw, mnem, [f"r{rt}", f"{d}(r{ra})"])

        # Special opcode 31
        if opcode == 31:
            xo = (instr >> 1) & 0x3FF
            rt = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # mflr (xo 339, ra=8)
            if xo == 339 and ra == 8:
                return DisasmInstruction(address, raw, "mflr", [f"r{rt}"])
            # mtlr (xo 467, ra=8)
            if xo == 467 and ra == 8:
                return DisasmInstruction(address, raw, "mtlr", [f"r{rt}"])
            # mfctr (xo 339, ra=9)
            if xo == 339 and ra == 9:
                return DisasmInstruction(address, raw, "mfctr", [f"r{rt}"])
            # mtctr (xo 467, ra=9)
            if xo == 467 and ra == 9:
                return DisasmInstruction(address, raw, "mtctr", [f"r{rt}"])
            # add (xo 266)
            if xo == 266:
                return DisasmInstruction(address, raw, "add", [f"r{rt}", f"r{ra}", f"r{rb}"])
            # subf (xo 40)
            if xo == 40:
                return DisasmInstruction(address, raw, "subf", [f"r{rt}", f"r{ra}", f"r{rb}"])

        # Fallback raw 32-bit word
        return DisasmInstruction(address, raw, ".word", [f"0x{instr:08X}"])

    @classmethod
    def _disasm_arm(cls, address: int, data: bytes, endian: str = "<") -> DisasmInstruction:
        if len(data) < 4:
            return DisasmInstruction(address, data, ".byte", [f"0x{b:02X}" for b in data])

        instr = struct.unpack(f"{endian}I", data[:4])[0]
        raw = data[:4]

        cond = (instr >> 28) & 0xF
        if cond == 0xF:
            # BLX unconditional
            pass

        # Branch / Branch with Link (B / BL)
        # bits 25..27 = 0b101
        if ((instr >> 25) & 0x7) == 0b101:
            is_link = bool((instr >> 24) & 1)
            imm24 = instr & 0x00FFFFFF
            if imm24 & 0x00800000:
                offset = (imm24 - 0x01000000) << 2
            else:
                offset = imm24 << 2
            target = (address + 8 + offset) & 0xFFFFFFFF
            mnem = "bl" if is_link else "b"
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnem,
                operands=[f"0x{target:08X}"],
                target_address=target,
                is_branch=True,
                is_call=is_link,
                is_conditional=(cond != 0xE),
            )

        # BX (branch and exchange, bx lr is return)
        if (instr & 0x0FFFFFF0) == 0x012FFF10:
            rm = instr & 0xF
            is_ret = (rm == 14)  # lr is r14
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="bx",
                operands=[f"r{rm}" if rm != 14 else "lr"],
                is_branch=True,
                is_return=is_ret,
            )

        # Halfword & Signed Data Transfer (LDRH, STRH, LDRSH, LDRSB)
        if ((instr >> 25) & 0x7) == 0 and (instr & 0x90) == 0x90 and ((instr >> 4) & 0xF) != 0x9:
            l = bool((instr >> 20) & 1)
            s = bool((instr >> 6) & 1)
            h = bool((instr >> 5) & 1)
            rn = (instr >> 16) & 0xF
            rd = (instr >> 12) & 0xF
            u = bool((instr >> 23) & 1)
            is_imm = bool((instr >> 22) & 1)

            if is_imm:
                off_hi = (instr >> 8) & 0xF
                off_lo = instr & 0xF
                imm = (off_hi << 4) | off_lo
                off_str = f"#{imm if u else -imm}" if imm != 0 else ""
            else:
                rm = instr & 0xF
                off_str = f", r{rm}" if u else f", -r{rm}"

            ptr_str = f"[r{rn}{', ' + off_str if off_str else ''}]"

            if s and h:
                mnem = "ldrsh"
            elif s and not h:
                mnem = "ldrsb"
            elif not s and h:
                mnem = "ldrh" if l else "strh"
            else:
                mnem = ".word"

            if mnem != ".word":
                return DisasmInstruction(address, raw, mnem, [f"r{rd}", ptr_str])

        # Single Data Transfer (LDR / STR / LDRB / STRB)
        if ((instr >> 26) & 0x3) == 0b01:
            is_imm_reg = bool((instr >> 25) & 1)
            l = bool((instr >> 20) & 1)
            b = bool((instr >> 22) & 1)
            u = bool((instr >> 23) & 1)
            rn = (instr >> 16) & 0xF
            rd = (instr >> 12) & 0xF

            mnem = ("ldrb" if b else "ldr") if l else ("strb" if b else "str")
            if not is_imm_reg:
                imm12 = instr & 0xFFF
                off_str = f"#{imm12 if u else -imm12}" if imm12 != 0 else ""
                ptr_str = f"[r{rn}{', ' + off_str if off_str else ''}]"
            else:
                rm = instr & 0xF
                ptr_str = f"[r{rn}, r{rm}]"

            return DisasmInstruction(address, raw, mnem, [f"r{rd}", ptr_str])

        # Data Processing Operations (ADD, SUB, CMP, etc.)
        if ((instr >> 26) & 0x3) == 0b00:
            is_imm = bool((instr >> 25) & 1)
            opc = (instr >> 21) & 0xF
            rn = (instr >> 16) & 0xF
            rd = (instr >> 12) & 0xF

            if is_imm:
                imm8 = instr & 0xFF
                rot = ((instr >> 8) & 0xF) * 2
                val = ((imm8 >> rot) | (imm8 << (32 - rot))) & 0xFFFFFFFF if rot != 0 else imm8
                op2_str = f"#0x{val:X}"
            else:
                rm = instr & 0xF
                op2_str = f"r{rm}"

            alu_names = {
                0: "and", 1: "eor", 2: "sub", 3: "rsb", 4: "add", 5: "adc",
                6: "sbc", 7: "rsc", 8: "tst", 9: "teq", 10: "cmp", 11: "cmn",
                12: "orr", 13: "mov", 14: "bic", 15: "mvn"
            }
            alu_mnem = alu_names.get(opc, ".word")

            if alu_mnem in ("cmp", "cmn", "tst", "teq"):
                return DisasmInstruction(address, raw, alu_mnem, [f"r{rn}", op2_str], is_conditional=True)
            elif alu_mnem in ("mov", "mvn"):
                return DisasmInstruction(address, raw, alu_mnem, [f"r{rd}", op2_str])
            elif alu_mnem != ".word":
                return DisasmInstruction(address, raw, alu_mnem, [f"r{rd}", f"r{rn}", op2_str])

        return DisasmInstruction(address, raw, ".word", [f"0x{instr:08X}"])

    @classmethod
    def _disasm_thumb(cls, address: int, data: bytes, endian: str = "<") -> DisasmInstruction:
        if len(data) < 2:
            return DisasmInstruction(address, data, ".byte", [f"0x{b:02X}" for b in data])

        instr = struct.unpack(f"{endian}H", data[:2])[0]
        raw = data[:2]

        # BX Rm
        if (instr & 0xFF87) == 0x4700:
            rm = (instr >> 3) & 0xF
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="bx",
                operands=[f"r{rm}" if rm != 14 else "lr"],
                is_branch=True,
                is_return=(rm == 14),
            )

        # Unconditional branch B (format 18: 0b11100 + 11-bit imm)
        if (instr >> 11) == 0b11100:
            imm11 = instr & 0x7FF
            if imm11 & 0x400:
                diff = (imm11 - 0x800) << 1
            else:
                diff = imm11 << 1
            target = (address + 4 + diff) & 0xFFFFFFFF
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="b",
                operands=[f"0x{target:08X}"],
                target_address=target,
                is_branch=True,
            )

        return DisasmInstruction(address, raw, ".short", [f"0x{instr:04X}"])

    @classmethod
    def _disasm_mips(cls, address: int, data: bytes, endian: str = "<") -> DisasmInstruction:
        if len(data) < 4:
            return DisasmInstruction(address, data, ".byte", [f"0x{b:02X}" for b in data])

        instr = struct.unpack(f"{endian}I", data[:4])[0]
        raw = data[:4]

        # NOP
        if instr == 0:
            return DisasmInstruction(address, raw, "nop")

        MIPS_REGS = (
            "$zero", "$at", "$v0", "$v1", "$a0", "$a1", "$a2", "$a3",
            "$t0", "$t1", "$t2", "$t3", "$t4", "$t5", "$t6", "$t7",
            "$s0", "$s1", "$s2", "$s3", "$s4", "$s5", "$s6", "$s7",
            "$t8", "$t9", "$k0", "$k1", "$gp", "$sp", "$fp", "$ra",
        )

        opcode = (instr >> 26) & 0x3F
        rs = (instr >> 21) & 0x1F
        rt = (instr >> 16) & 0x1F
        rd = (instr >> 11) & 0x1F
        sa = (instr >> 6) & 0x1F
        funct = instr & 0x3F
        imm16 = instr & 0xFFFF
        simm16 = struct.unpack(">h", struct.pack(">H", imm16))[0]

        r_rs = MIPS_REGS[rs]
        r_rt = MIPS_REGS[rt]
        r_rd = MIPS_REGS[rd]

        # J / JAL
        if opcode in (2, 3):
            is_jal = (opcode == 3)
            target = ((address & 0xF0000000) | ((instr & 0x03FFFFFF) << 2))
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="jal" if is_jal else "j",
                operands=[f"0x{target:08X}"],
                target_address=target,
                is_branch=True,
                is_call=is_jal,
            )

        # SPECIAL (opcode 0)
        if opcode == 0:
            if funct == 0:
                if rd == 0 and rt == 0 and sa == 0:
                    return DisasmInstruction(address, raw, "nop")
                return DisasmInstruction(address, raw, "sll", [r_rd, r_rt, str(sa)])
            elif funct == 2:
                return DisasmInstruction(address, raw, "srl", [r_rd, r_rt, str(sa)])
            elif funct == 3:
                return DisasmInstruction(address, raw, "sra", [r_rd, r_rt, str(sa)])
            elif funct == 4:
                return DisasmInstruction(address, raw, "sllv", [r_rd, r_rt, r_rs])
            elif funct == 6:
                return DisasmInstruction(address, raw, "srlv", [r_rd, r_rt, r_rs])
            elif funct == 7:
                return DisasmInstruction(address, raw, "srav", [r_rd, r_rt, r_rs])
            elif funct == 8:  # jr
                return DisasmInstruction(
                    address=address,
                    raw_bytes=raw,
                    mnemonic="jr",
                    operands=[r_rs],
                    is_branch=True,
                    is_return=(rs == 31),
                )
            elif funct == 9:  # jalr
                return DisasmInstruction(
                    address=address,
                    raw_bytes=raw,
                    mnemonic="jalr",
                    operands=[r_rd, r_rs] if rd != 31 else [r_rs],
                    is_branch=True,
                    is_call=True,
                )
            elif funct == 12:
                return DisasmInstruction(address, raw, "syscall")
            elif funct == 13:
                return DisasmInstruction(address, raw, "break")
            elif funct == 16:
                return DisasmInstruction(address, raw, "mfhi", [r_rd])
            elif funct == 17:
                return DisasmInstruction(address, raw, "mthi", [r_rs])
            elif funct == 18:
                return DisasmInstruction(address, raw, "mflo", [r_rd])
            elif funct == 19:
                return DisasmInstruction(address, raw, "mtlo", [r_rs])
            elif funct == 24:
                return DisasmInstruction(address, raw, "mult", [r_rs, r_rt])
            elif funct == 25:
                return DisasmInstruction(address, raw, "multu", [r_rs, r_rt])
            elif funct == 26:
                return DisasmInstruction(address, raw, "div", [r_rs, r_rt])
            elif funct == 27:
                return DisasmInstruction(address, raw, "divu", [r_rs, r_rt])
            elif funct == 32:
                return DisasmInstruction(address, raw, "add", [r_rd, r_rs, r_rt])
            elif funct == 33:
                if rs == 0:
                    return DisasmInstruction(address, raw, "move", [r_rd, r_rt])
                return DisasmInstruction(address, raw, "addu", [r_rd, r_rs, r_rt])
            elif funct == 34:
                return DisasmInstruction(address, raw, "sub", [r_rd, r_rs, r_rt])
            elif funct == 35:
                return DisasmInstruction(address, raw, "subu", [r_rd, r_rs, r_rt])
            elif funct == 36:
                return DisasmInstruction(address, raw, "and", [r_rd, r_rs, r_rt])
            elif funct == 37:
                if rt == 0:
                    return DisasmInstruction(address, raw, "move", [r_rd, r_rs])
                return DisasmInstruction(address, raw, "or", [r_rd, r_rs, r_rt])
            elif funct == 38:
                return DisasmInstruction(address, raw, "xor", [r_rd, r_rs, r_rt])
            elif funct == 39:
                return DisasmInstruction(address, raw, "nor", [r_rd, r_rs, r_rt])
            elif funct == 42:
                return DisasmInstruction(address, raw, "slt", [r_rd, r_rs, r_rt])
            elif funct == 43:
                return DisasmInstruction(address, raw, "sltu", [r_rd, r_rs, r_rt])

        # REGIMM branches (opcode 1)
        if opcode == 1:
            target = (address + 4 + (simm16 << 2)) & 0xFFFFFFFF
            if rt == 0:
                return DisasmInstruction(address, raw, "bltz", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
            elif rt == 1:
                return DisasmInstruction(address, raw, "bgez", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
            elif rt == 16:
                return DisasmInstruction(address, raw, "bltzal", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_call=True, is_conditional=True)
            elif rt == 17:
                return DisasmInstruction(address, raw, "bgezal", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_call=True, is_conditional=True)

        # Conditional branches
        if opcode in (4, 5, 6, 7):
            target = (address + 4 + (simm16 << 2)) & 0xFFFFFFFF
            if opcode == 4:
                if rt == 0 and rs == 0:
                    return DisasmInstruction(address, raw, "b", [f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=False)
                elif rt == 0:
                    return DisasmInstruction(address, raw, "beqz", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
                return DisasmInstruction(address, raw, "beq", [r_rs, r_rt, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
            elif opcode == 5:
                if rt == 0:
                    return DisasmInstruction(address, raw, "bnez", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
                return DisasmInstruction(address, raw, "bne", [r_rs, r_rt, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
            elif opcode == 6:
                return DisasmInstruction(address, raw, "blez", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
            elif opcode == 7:
                return DisasmInstruction(address, raw, "bgtz", [r_rs, f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)

        # Immediate arithmetic & logic
        if opcode == 8:
            return DisasmInstruction(address, raw, "addi", [r_rt, r_rs, str(simm16)])
        if opcode == 9:
            if rs == 0:
                return DisasmInstruction(address, raw, "li", [r_rt, str(simm16)])
            return DisasmInstruction(address, raw, "addiu", [r_rt, r_rs, str(simm16)])
        if opcode == 10:
            return DisasmInstruction(address, raw, "slti", [r_rt, r_rs, str(simm16)])
        if opcode == 11:
            return DisasmInstruction(address, raw, "sltiu", [r_rt, r_rs, str(simm16)])
        if opcode == 12:
            return DisasmInstruction(address, raw, "andi", [r_rt, r_rs, f"0x{imm16:04X}"])
        if opcode == 13:
            return DisasmInstruction(address, raw, "ori", [r_rt, r_rs, f"0x{imm16:04X}"])
        if opcode == 14:
            return DisasmInstruction(address, raw, "xori", [r_rt, r_rs, f"0x{imm16:04X}"])

        # LUI (opcode 15)
        if opcode == 15:
            return DisasmInstruction(address, raw, "lui", [r_rt, f"0x{imm16:04X}"])

        # COP1 (opcode 17, Floating Point Operations)
        if opcode == 17:
            fmt_code = rs
            fs = (instr >> 11) & 0x1F
            fd = (instr >> 6) & 0x1F
            r_fs = f"$f{fs}"
            r_ft = f"$f{rt}"
            r_fd = f"$f{fd}"
            if fmt_code == 0:  # mfc1
                return DisasmInstruction(address, raw, "mfc1", [r_rt, r_fs])
            elif fmt_code == 4:  # mtc1
                return DisasmInstruction(address, raw, "mtc1", [r_rt, r_fs])
            elif fmt_code == 8:  # bc1t / bc1f
                target = (address + 4 + (simm16 << 2)) & 0xFFFFFFFF
                is_true = bool(rt & 1)
                mn = "bc1t" if is_true else "bc1f"
                return DisasmInstruction(address, raw, mn, [f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
            elif fmt_code in (16, 17):  # single (.s) or double (.d)
                suffix = ".s" if fmt_code == 16 else ".d"
                cop1_ops = {
                    0: "add", 1: "sub", 2: "mul", 3: "div", 5: "abs", 6: "mov",
                    7: "neg", 32: "cvt.s", 33: "cvt.d", 36: "cvt.w"
                }
                if funct in cop1_ops:
                    mn = f"{cop1_ops[funct]}{suffix}"
                    ops = [r_fd, r_fs, r_ft] if funct in (0, 1, 2, 3) else [r_fd, r_fs]
                    return DisasmInstruction(address, raw, mn, ops)
                elif 48 <= funct <= 63:  # c.cond.fmt
                    cond_names = {
                        48: "c.f", 50: "c.eq", 52: "c.olt", 54: "c.ole",
                        60: "c.lt", 62: "c.le"
                    }
                    mn = f"{cond_names.get(funct, f'c.{funct}')}{suffix}"
                    return DisasmInstruction(address, raw, mn, [r_fs, r_ft])

        # Load / Store instructions
        load_store = {
            32: "lb", 33: "lh", 34: "lwl", 35: "lw", 36: "lbu", 37: "lhu", 38: "lwr",
            40: "sb", 41: "sh", 42: "swl", 43: "sw", 46: "swr",
            49: "lwc1", 53: "ldc1", 57: "swc1", 61: "sdc1"
        }
        if opcode in load_store:
            mn = load_store[opcode]
            rt_name = f"$f{rt}" if mn.endswith("c1") else r_rt
            return DisasmInstruction(address, raw, mn, [rt_name, f"{simm16}({r_rs})"])

        return DisasmInstruction(address, raw, ".word", [f"0x{instr:08X}"])

    @classmethod
    def _disasm_sm83(cls, address: int, data: bytes) -> DisasmInstruction:
        if not data:
            return DisasmInstruction(address, b"", ".byte", [])
        b0 = data[0]
        if b0 == 0x00:
            return DisasmInstruction(address, bytes([b0]), "nop")
        elif b0 == 0xC9:
            return DisasmInstruction(address, bytes([b0]), "ret", is_return=True, is_branch=True)
        elif b0 == 0xC3 and len(data) >= 3:
            target = data[1] | (data[2] << 8)
            return DisasmInstruction(address, data[:3], "jp", [f"0x{target:04X}"], target_address=target, is_branch=True)
        elif b0 == 0xCD and len(data) >= 3:
            target = data[1] | (data[2] << 8)
            return DisasmInstruction(address, data[:3], "call", [f"0x{target:04X}"], target_address=target, is_branch=True, is_call=True)
        elif b0 == 0x18 and len(data) >= 2:
            rel = struct.unpack("b", bytes([data[1]]))[0]
            target = (address + 2 + rel) & 0xFFFF
            return DisasmInstruction(address, data[:2], "jr", [f"0x{target:04X}"], target_address=target, is_branch=True)
        elif 0x40 <= b0 <= 0x7F:
            regs = ["b", "c", "d", "e", "h", "l", "[hl]", "a"]
            rd = regs[(b0 >> 3) & 0x07]
            rs = regs[b0 & 0x07]
            return DisasmInstruction(address, bytes([b0]), "ld", [rd, rs])
        elif b0 == 0x3E and len(data) >= 2:
            return DisasmInstruction(address, data[:2], "ld", ["a", f"0x{data[1]:02X}"])
        elif b0 in (0xC5, 0xD5, 0xE5, 0xF5):
            r = {0xC5: "bc", 0xD5: "de", 0xE5: "hl", 0xF5: "af"}[b0]
            return DisasmInstruction(address, bytes([b0]), "push", [r])
        elif b0 in (0xC1, 0xD1, 0xE1, 0xF1):
            r = {0xC1: "bc", 0xD1: "de", 0xE1: "hl", 0xF1: "af"}[b0]
            return DisasmInstruction(address, bytes([b0]), "pop", [r])
        return DisasmInstruction(address, data[:1], ".byte", [f"0x{b0:02X}"])

    @classmethod
    def _disasm_m68k(cls, address: int, data: bytes) -> DisasmInstruction:
        if len(data) < 2:
            return DisasmInstruction(address, data, ".byte", [f"0x{b:02X}" for b in data])
        w0 = struct.unpack(">H", data[:2])[0]
        if w0 == 0x4E71:
            return DisasmInstruction(address, data[:2], "nop")
        elif w0 == 0x4E75:
            return DisasmInstruction(address, data[:2], "rts", is_return=True, is_branch=True)
        elif (w0 >> 12) == 0x06 and len(data) >= 2:
            cond = (w0 >> 8) & 0x0F
            disp = struct.unpack("b", bytes([w0 & 0xFF]))[0]
            target = address + 2 + disp
            if cond == 0:
                return DisasmInstruction(address, data[:2], "bra", [f"0x{target:08X}"], target_address=target, is_branch=True)
            elif cond == 1:
                return DisasmInstruction(address, data[:2], "bsr", [f"0x{target:08X}"], target_address=target, is_branch=True, is_call=True)
            else:
                cond_names = {2: "bhi", 3: "bls", 4: "bcc", 5: "bcs", 6: "bne", 7: "beq", 12: "bge", 13: "blt", 14: "bgt", 15: "ble"}
                mn = cond_names.get(cond, f"b{cond:X}")
                return DisasmInstruction(address, data[:2], mn, [f"0x{target:08X}"], target_address=target, is_branch=True, is_conditional=True)
        elif (w0 >> 12) == 0x07:
            reg = (w0 >> 9) & 0x07
            data_val = struct.unpack("b", bytes([w0 & 0xFF]))[0]
            return DisasmInstruction(address, data[:2], "moveq", [f"#{data_val}", f"d{reg}"])
        return DisasmInstruction(address, data[:2], ".word", [f"0x{w0:04X}"])

    @classmethod
    def _disassemble_impl(
        cls,
        data: bytes,
        base_address: int = 0,
        arch: str = "ppc",
        endian: Optional[str] = None,
        max_instructions: Optional[int] = None,
    ) -> List[DisasmInstruction]:
        """
        Disassemble a contiguous block of bytes into a list of DisasmInstruction objects.
        """
        instructions: List[DisasmInstruction] = []
        offset = 0
        arch_l = arch.lower()
        if arch_l in ("thumb", "arm_thumb", "m68k", "68000", "md", "genesis", "megadrive"):
            step = 2
        elif arch_l in ("sm83", "gb", "gbc", "gameboy"):
            step = 1
        else:
            step = 4

        while offset < len(data):
            if max_instructions and len(instructions) >= max_instructions:
                break
            chunk_len = min(4, len(data) - offset)
            ins = cls.disassemble_instruction(
                address=base_address + offset,
                raw_bytes=data[offset : offset + chunk_len],
                arch=arch,
                endian=endian,
            )
            instructions.append(ins)
            offset += len(ins.raw_bytes) if ins.raw_bytes else step

        return instructions

    @classmethod
    def format_listing(
        cls,
        instructions: List[DisasmInstruction],
        symbols: Optional[Dict[int, str]] = None,
    ) -> str:
        """
        Format disassembled instructions into an assembly listing with labels.
        """
        sym_map = symbols or {}
        lines: List[str] = []

        for ins in instructions:
            if ins.address in sym_map:
                lines.append(f"\n{sym_map[ins.address]}:")
            lines.append(f"    {ins.to_string(sym_map)}")

        return "\n".join(lines).strip()
