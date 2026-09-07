import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class DisasmInstruction:
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
        else:
            raise ValueError(f"Unsupported architecture: '{arch}'")

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

        opcode = (instr >> 26) & 0x3F

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

        # JR / JALR (opcode 0, funct 8 / 9)
        if opcode == 0:
            funct = instr & 0x3F
            rs = (instr >> 21) & 0x1F
            if funct == 8:  # jr
                is_ret = (rs == 31)  # $ra is $31
                return DisasmInstruction(
                    address=address,
                    raw_bytes=raw,
                    mnemonic="jr",
                    operands=[f"${rs}" if rs != 31 else "$ra"],
                    is_branch=True,
                    is_return=is_ret,
                )

        # LUI (opcode 15)
        if opcode == 15:
            rt = (instr >> 16) & 0x1F
            imm = instr & 0xFFFF
            return DisasmInstruction(address, raw, "lui", [f"${rt}", f"0x{imm:04X}"])

        # ADDIU (opcode 9)
        if opcode == 9:
            rs = (instr >> 21) & 0x1F
            rt = (instr >> 16) & 0x1F
            simm = struct.unpack(">h", struct.pack(">H", instr & 0xFFFF))[0]
            return DisasmInstruction(address, raw, "addiu", [f"${rt}", f"${rs}", str(simm)])

        return DisasmInstruction(address, raw, ".word", [f"0x{instr:08X}"])

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
        step = 2 if arch.lower() == "thumb" else 4

        while offset + step <= len(data):
            if max_instructions and len(instructions) >= max_instructions:
                break
            ins = cls.disassemble_instruction(
                address=base_address + offset,
                raw_bytes=data[offset : offset + step],
                arch=arch,
                endian=endian,
            )
            instructions.append(ins)
            offset += step

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
