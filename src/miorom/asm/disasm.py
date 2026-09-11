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
                **kwargs,
            ) -> List[DisasmInstruction]:
                target_arch = arch or instance.arch
                target_endian = endian or instance.endian
                return owner._disassemble_impl(
                    data=data,
                    base_address=base_address,
                    arch=target_arch,
                    endian=target_endian,
                    max_instructions=max_instructions,
                    **kwargs,
                )
            return _instance_disassemble
        else:
            def _class_disassemble(
                data: bytes,
                base_address: int = 0,
                arch: str = "ppc",
                endian: Optional[str] = None,
                max_instructions: Optional[int] = None,
                **kwargs,
            ) -> List[DisasmInstruction]:
                return owner._disassemble_impl(
                    data=data,
                    base_address=base_address,
                    arch=arch,
                    endian=endian,
                    max_instructions=max_instructions,
                    **kwargs,
                )
            return _class_disassemble


class UniversalDisassembler:
    """
    Multi-architecture instruction disassembler supporting PowerPC, ARM, Thumb, MIPS, SM83, M68K, MOS 6502, and W65C816.
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
        m16: bool = False,
        x16: bool = False,
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
        elif arch_norm in ("6502", "nes", "famicom", "2a03"):
            return cls._disasm_6502(address, raw_bytes)
        elif arch_norm in ("65816", "snes", "sfc", "5a22", "w65c816"):
            return cls._disasm_65816(address, raw_bytes, m16=m16, x16=x16)
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

        # Load / Store words (lwz=32, lwzu=33, stw=36, stwu=37)
        if opcode in (32, 33, 36, 37):
            rt = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            d = struct.unpack(">h", struct.pack(">H", instr & 0xFFFF))[0]
            mnem_map = {32: "lwz", 33: "lwzu", 36: "stw", 37: "stwu"}
            mnem = mnem_map[opcode]
            return DisasmInstruction(address, raw, mnem, [f"r{rt}", f"{d}(r{ra})"])

        # Special opcode 31
        if opcode == 31:
            xo = (instr >> 1) & 0x3FF
            rt = (instr >> 21) & 0x1F
            ra = (instr >> 16) & 0x1F
            rb = (instr >> 11) & 0x1F

            # or / mr (xo 444)
            if xo == 444:
                rs = rt
                if rs == rb:
                    return DisasmInstruction(address, raw, "mr", [f"r{ra}", f"r{rs}"])
                return DisasmInstruction(address, raw, "or", [f"r{ra}", f"r{rs}", f"r{rb}"])
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

        def _t_reg(r: int) -> str:
            if r == 13:
                return "sp"
            elif r == 14:
                return "lr"
            elif r == 15:
                return "pc"
            return f"r{r}"

        # ------------------------------------------------------------------
        # Format 19: Long branch with link (BL) - 32-bit (2 halfwords)
        # First halfword: 11110_Offset11 (0xF000..0xF7FF)
        # Second halfword: 11111_Offset11 (0xF800..0xFFFF)
        # ------------------------------------------------------------------
        if (instr >> 11) == 0b11110 and len(data) >= 4:
            instr2 = struct.unpack(f"{endian}H", data[2:4])[0]
            if (instr2 >> 11) == 0b11111:
                raw4 = data[:4]
                off_h = instr & 0x7FF
                if off_h & 0x400:
                    off_h -= 0x800
                off_l = instr2 & 0x7FF
                diff = (off_h << 12) + (off_l << 1)
                target = (address + 4 + diff) & 0xFFFFFFFF
                return DisasmInstruction(
                    address=address,
                    raw_bytes=raw4,
                    mnemonic="bl",
                    operands=[f"0x{target:08X}"],
                    target_address=target,
                    is_call=True,
                )

        # ------------------------------------------------------------------
        # Format 1: Move shifted register
        # 000_Op_Offset5_Rs_Rd (Op: 00=lsl, 01=lsr, 10=asr)
        # ------------------------------------------------------------------
        if (instr >> 13) == 0 and (instr >> 11) in (0, 1, 2):
            op = (instr >> 11) & 0x3
            offset5 = (instr >> 6) & 0x1F
            rs = (instr >> 3) & 0x7
            rd = instr & 0x7
            mnems = ["lsl", "lsr", "asr"]
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnems[op],
                operands=[f"r{rd}", f"r{rs}", f"#{offset5}"],
            )

        # ------------------------------------------------------------------
        # Format 2: Add / subtract register or 3-bit immediate
        # 00011_I_Op_Rn/Offset3_Rs_Rd
        # ------------------------------------------------------------------
        if (instr >> 11) == 3:
            imm_flag = (instr >> 10) & 1
            sub_flag = (instr >> 9) & 1
            rn_imm = (instr >> 6) & 0x7
            rs = (instr >> 3) & 0x7
            rd = instr & 0x7
            mnemonic = "sub" if sub_flag else "add"
            op3 = f"#{rn_imm}" if imm_flag else f"r{rn_imm}"
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnemonic,
                operands=[f"r{rd}", f"r{rs}", op3],
            )

        # ------------------------------------------------------------------
        # Format 3: Move/compare/add/subtract immediate
        # 001_Op_Rd_Offset8 (Op: 00=mov, 01=cmp, 10=add, 11=sub)
        # ------------------------------------------------------------------
        if (instr >> 13) == 1:
            op = (instr >> 11) & 0x3
            rd = (instr >> 8) & 0x7
            imm8 = instr & 0xFF
            mnems = ["mov", "cmp", "add", "sub"]
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnems[op],
                operands=[f"r{rd}", f"#{imm8}"],
            )

        # ------------------------------------------------------------------
        # Format 4: ALU operations
        # 010000_Op_Rs_Rd (16 opcodes)
        # ------------------------------------------------------------------
        if (instr >> 10) == 0b010000:
            op = (instr >> 6) & 0xF
            rs = (instr >> 3) & 0x7
            rd = instr & 0x7
            ALU_OPS = [
                "and", "eor", "lsl", "lsr", "asr", "adc", "sbc", "ror",
                "tst", "neg", "cmp", "cmn", "orr", "mul", "bic", "mvn",
            ]
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=ALU_OPS[op],
                operands=[f"r{rd}", f"r{rs}"],
            )

        # ------------------------------------------------------------------
        # Format 5: Hi register operations / branch exchange
        # 010001_Op_H1_H2_Rs_Rd
        # ------------------------------------------------------------------
        if (instr >> 10) == 0b010001:
            op = (instr >> 8) & 0x3
            h1 = (instr >> 7) & 1
            h2 = (instr >> 6) & 1
            rd = (h1 << 3) | (instr & 0x7)
            rm = (h2 << 3) | ((instr >> 3) & 0x7)
            if op == 0:
                return DisasmInstruction(address=address, raw_bytes=raw, mnemonic="add", operands=[_t_reg(rd), _t_reg(rm)])
            elif op == 1:
                return DisasmInstruction(address=address, raw_bytes=raw, mnemonic="cmp", operands=[_t_reg(rd), _t_reg(rm)])
            elif op == 2:
                return DisasmInstruction(address=address, raw_bytes=raw, mnemonic="mov", operands=[_t_reg(rd), _t_reg(rm)])
            elif op == 3:
                # BX Rm
                is_ret = (rm == 14)
                return DisasmInstruction(
                    address=address,
                    raw_bytes=raw,
                    mnemonic="bx",
                    operands=[_t_reg(rm)],
                    is_branch=True,
                    is_return=is_ret,
                )

        # ------------------------------------------------------------------
        # Format 6: PC-relative load
        # 01001_Rd_Word8
        # ------------------------------------------------------------------
        if (instr >> 11) == 0b01001:
            rd = (instr >> 8) & 0x7
            word8 = instr & 0xFF
            offset = word8 * 4
            target = ((address + 4) & ~2) + offset
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="ldr",
                operands=[f"r{rd}", f"[pc, #{offset}]"],
                comment=f"=0x{target:08X}",
            )

        # ------------------------------------------------------------------
        # Format 7: Load/store with register offset
        # 0101_L_B_0_Ro_Rb_Rd
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b0101 and ((instr >> 9) & 1) == 0:
            l_bit = (instr >> 11) & 1
            b_bit = (instr >> 10) & 1
            ro = (instr >> 6) & 0x7
            rb = (instr >> 3) & 0x7
            rd = instr & 0x7
            if l_bit == 0:
                mnemonic = "strb" if b_bit else "str"
            else:
                mnemonic = "ldrb" if b_bit else "ldr"
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnemonic,
                operands=[f"r{rd}", f"[r{rb}, r{ro}]"],
            )

        # ------------------------------------------------------------------
        # Format 8: Load/store sign-extended byte/halfword
        # 0101_H_S_1_Ro_Rb_Rd
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b0101 and ((instr >> 9) & 1) == 1:
            h_bit = (instr >> 11) & 1
            s_bit = (instr >> 10) & 1
            ro = (instr >> 6) & 0x7
            rb = (instr >> 3) & 0x7
            rd = instr & 0x7
            op_code = (h_bit << 1) | s_bit
            mnems = ["strh", "ldsb", "ldrh", "ldsh"]
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnems[op_code],
                operands=[f"r{rd}", f"[r{rb}, r{ro}]"],
            )

        # ------------------------------------------------------------------
        # Format 9: Load/store with immediate offset
        # 011_B_L_Offset5_Rb_Rd
        # ------------------------------------------------------------------
        if (instr >> 13) == 0b011:
            b_bit = (instr >> 12) & 1
            l_bit = (instr >> 11) & 1
            offset5 = (instr >> 6) & 0x1F
            rb = (instr >> 3) & 0x7
            rd = instr & 0x7
            if b_bit == 0:
                mnemonic = "ldr" if l_bit else "str"
                offset = offset5 * 4
            else:
                mnemonic = "ldrb" if l_bit else "strb"
                offset = offset5
            ops = [f"r{rd}", f"[r{rb}, #{offset}]" if offset != 0 else f"[r{rb}]"]
            return DisasmInstruction(address=address, raw_bytes=raw, mnemonic=mnemonic, operands=ops)

        # ------------------------------------------------------------------
        # Format 10: Load/store halfword
        # 1000_L_Offset5_Rb_Rd
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b1000:
            l_bit = (instr >> 11) & 1
            offset5 = (instr >> 6) & 0x1F
            rb = (instr >> 3) & 0x7
            rd = instr & 0x7
            offset = offset5 * 2
            mnemonic = "ldrh" if l_bit else "strh"
            ops = [f"r{rd}", f"[r{rb}, #{offset}]" if offset != 0 else f"[r{rb}]"]
            return DisasmInstruction(address=address, raw_bytes=raw, mnemonic=mnemonic, operands=ops)

        # ------------------------------------------------------------------
        # Format 11: SP-relative load/store
        # 1001_L_Rd_Word8
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b1001:
            l_bit = (instr >> 11) & 1
            rd = (instr >> 8) & 0x7
            word8 = instr & 0xFF
            offset = word8 * 4
            mnemonic = "ldr" if l_bit else "str"
            ops = [f"r{rd}", f"[sp, #{offset}]" if offset != 0 else "[sp]"]
            return DisasmInstruction(address=address, raw_bytes=raw, mnemonic=mnemonic, operands=ops)

        # ------------------------------------------------------------------
        # Format 12: Load address
        # 1010_SP_Rd_Word8
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b1010:
            sp_bit = (instr >> 11) & 1
            rd = (instr >> 8) & 0x7
            word8 = instr & 0xFF
            offset = word8 * 4
            src_reg = "sp" if sp_bit else "pc"
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="add",
                operands=[f"r{rd}", src_reg, f"#{offset}"],
            )

        # ------------------------------------------------------------------
        # Format 13: Add offset to Stack Pointer
        # 10110000_S_Word7
        # ------------------------------------------------------------------
        if (instr >> 8) == 0b10110000:
            s_bit = (instr >> 7) & 1
            word7 = instr & 0x7F
            offset = word7 * 4
            mnemonic = "sub" if s_bit else "add"
            return DisasmInstruction(address=address, raw_bytes=raw, mnemonic=mnemonic, operands=["sp", f"#{offset}"])

        # ------------------------------------------------------------------
        # Format 14: Push/pop register list
        # 1011_L_10_R_Rlist
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b1011 and ((instr >> 9) & 3) == 2:
            l_bit = (instr >> 11) & 1
            r_bit = (instr >> 8) & 1
            rlist = instr & 0xFF
            reg_names = [f"r{i}" for i in range(8) if (rlist & (1 << i))]
            if r_bit:
                reg_names.append("pc" if l_bit else "lr")
            mnemonic = "pop" if l_bit else "push"
            is_ret = (l_bit == 1 and r_bit == 1)
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnemonic,
                operands=["{" + ", ".join(reg_names) + "}"],
                is_branch=is_ret,
                is_return=is_ret,
            )

        # ------------------------------------------------------------------
        # Format 15: Multiple load/store (stmia / ldmia)
        # 1100_L_Rb_Rlist
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b1100:
            l_bit = (instr >> 11) & 1
            rb = (instr >> 8) & 0x7
            rlist = instr & 0xFF
            reg_names = [f"r{i}" for i in range(8) if (rlist & (1 << i))]
            mnemonic = "ldmia" if l_bit else "stmia"
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic=mnemonic,
                operands=[f"r{rb}!", "{" + ", ".join(reg_names) + "}"],
            )

        # ------------------------------------------------------------------
        # Format 17: Software interrupt (SWI)
        # 11011111_Value8
        # ------------------------------------------------------------------
        if (instr >> 8) == 0xDF:
            val8 = instr & 0xFF
            return DisasmInstruction(
                address=address,
                raw_bytes=raw,
                mnemonic="swi",
                operands=[f"0x{val8:02X}"],
                is_call=True,
            )

        # ------------------------------------------------------------------
        # Format 16: Conditional branch
        # 1101_Cond_Offset8
        # ------------------------------------------------------------------
        if (instr >> 12) == 0b1101:
            cond = (instr >> 8) & 0xF
            COND_MNEMS = [
                "beq", "bne", "bcs", "bcc", "bmi", "bpl", "bvs", "bvc",
                "bhi", "bls", "bge", "blt", "bgt", "ble",
            ]
            if cond < len(COND_MNEMS):
                mnemonic = COND_MNEMS[cond]
                imm8 = instr & 0xFF
                diff = (imm8 - 0x100 if imm8 & 0x80 else imm8) << 1
                target = (address + 4 + diff) & 0xFFFFFFFF
                return DisasmInstruction(
                    address=address,
                    raw_bytes=raw,
                    mnemonic=mnemonic,
                    operands=[f"0x{target:08X}"],
                    target_address=target,
                    is_branch=True,
                    is_conditional=True,
                )

        # ------------------------------------------------------------------
        # Format 18: Unconditional branch (B)
        # 11100_Offset11
        # ------------------------------------------------------------------
        if (instr >> 11) == 0b11100:
            imm11 = instr & 0x7FF
            diff = (imm11 - 0x800 if imm11 & 0x400 else imm11) << 1
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

    _OPCODES_65816 = {
        0x00: ("brk", "imm8"), 0x01: ("ora", "dpix"), 0x02: ("cop", "imm8"), 0x03: ("ora", "sr"),
        0x04: ("tsb", "dp"),   0x05: ("ora", "dp"),   0x06: ("asl", "dp"),   0x07: ("ora", "dpil"),
        0x08: ("php", "imp"),  0x09: ("ora", "imm_m"),0x0A: ("asl", "imp"),  0x0B: ("phd", "imp"),
        0x0C: ("tsb", "abs"),  0x0D: ("ora", "abs"),  0x0E: ("asl", "abs"),  0x0F: ("ora", "absl"),
        0x10: ("bpl", "rel"),  0x11: ("ora", "dpiy"), 0x12: ("ora", "dpi"),  0x13: ("ora", "sriy"),
        0x14: ("trb", "dp"),   0x15: ("ora", "dpx"),  0x16: ("asl", "dpx"),  0x17: ("ora", "dpily"),
        0x18: ("clc", "imp"),  0x19: ("ora", "aby"),  0x1A: ("inc", "imp"),  0x1B: ("tcs", "imp"),
        0x1C: ("trb", "abs"),  0x1D: ("ora", "abx"),  0x1E: ("asl", "abx"),  0x1F: ("ora", "abslx"),
        0x20: ("jsr", "abs"),  0x21: ("and", "dpix"), 0x22: ("jsl", "absl"), 0x23: ("and", "sr"),
        0x24: ("bit", "dp"),   0x25: ("and", "dp"),   0x26: ("rol", "dp"),   0x27: ("and", "dpil"),
        0x28: ("plp", "imp"),  0x29: ("and", "imm_m"),0x2A: ("rol", "imp"),  0x2B: ("pld", "imp"),
        0x2C: ("bit", "abs"),  0x2D: ("and", "abs"),  0x2E: ("rol", "abs"),  0x2F: ("and", "absl"),
        0x30: ("bmi", "rel"),  0x31: ("and", "dpiy"), 0x32: ("and", "dpi"),  0x33: ("and", "sriy"),
        0x34: ("bit", "dpx"),  0x35: ("and", "dpx"),  0x36: ("rol", "dpx"),  0x37: ("and", "dpily"),
        0x38: ("sec", "imp"),  0x39: ("and", "aby"),  0x3A: ("dec", "imp"),  0x3B: ("tsc", "imp"),
        0x3C: ("bit", "abx"),  0x3D: ("and", "abx"),  0x3E: ("rol", "abx"),  0x3F: ("and", "abslx"),
        0x40: ("rti", "imp"),  0x41: ("eor", "dpix"), 0x42: ("wdm", "imm8"), 0x43: ("eor", "sr"),
        0x44: ("mvp", "bm"),   0x45: ("eor", "dp"),   0x46: ("lsr", "dp"),   0x47: ("eor", "dpil"),
        0x48: ("pha", "imp"),  0x49: ("eor", "imm_m"),0x4A: ("lsr", "imp"),  0x4B: ("phk", "imp"),
        0x4C: ("jmp", "abs"),  0x4D: ("eor", "abs"),  0x4E: ("lsr", "abs"),  0x4F: ("eor", "absl"),
        0x50: ("bvc", "rel"),  0x51: ("eor", "dpiy"), 0x52: ("eor", "dpi"),  0x53: ("eor", "sriy"),
        0x54: ("mvn", "bm"),   0x55: ("eor", "dpx"),  0x56: ("lsr", "dpx"),  0x57: ("eor", "dpily"),
        0x58: ("cli", "imp"),  0x59: ("eor", "aby"),  0x5A: ("phy", "imp"),  0x5B: ("tcd", "imp"),
        0x5C: ("jml", "absl"), 0x5D: ("eor", "abx"),  0x5E: ("lsr", "abx"),  0x5F: ("eor", "abslx"),
        0x60: ("rts", "imp"),  0x61: ("adc", "dpix"), 0x62: ("per", "rell"), 0x63: ("adc", "sr"),
        0x64: ("stz", "dp"),   0x65: ("adc", "dp"),   0x66: ("ror", "dp"),   0x67: ("adc", "dpil"),
        0x68: ("pla", "imp"),  0x69: ("adc", "imm_m"),0x6A: ("ror", "imp"),  0x6B: ("rtl", "imp"),
        0x6C: ("jmp", "abi"),  0x6D: ("adc", "abs"),  0x6E: ("ror", "abs"),  0x6F: ("adc", "absl"),
        0x70: ("bvs", "rel"),  0x71: ("adc", "dpiy"), 0x72: ("adc", "dpi"),  0x73: ("adc", "sriy"),
        0x74: ("stz", "dpx"),  0x75: ("adc", "dpx"),  0x76: ("ror", "dpx"),  0x77: ("adc", "dpily"),
        0x78: ("sei", "imp"),  0x79: ("adc", "aby"),  0x7A: ("ply", "imp"),  0x7B: ("tdc", "imp"),
        0x7C: ("jmp", "abix"), 0x7D: ("adc", "abx"),  0x7E: ("ror", "abx"),  0x7F: ("adc", "abslx"),
        0x80: ("bra", "rel"),  0x81: ("sta", "dpix"), 0x82: ("brl", "rell"), 0x83: ("sta", "sr"),
        0x84: ("sty", "dp"),   0x85: ("sta", "dp"),   0x86: ("stx", "dp"),   0x87: ("sta", "dpil"),
        0x88: ("dey", "imp"),  0x89: ("bit", "imm_m"),0x8A: ("txa", "imp"),  0x8B: ("phb", "imp"),
        0x8C: ("sty", "abs"),  0x8D: ("sta", "abs"),  0x8E: ("stx", "abs"),  0x8F: ("sta", "absl"),
        0x90: ("bcc", "rel"),  0x91: ("sta", "dpiy"), 0x92: ("sta", "dpi"),  0x93: ("sta", "sriy"),
        0x94: ("sty", "dpx"),  0x95: ("sta", "dpx"),  0x96: ("stx", "dpy"),  0x97: ("sta", "dpily"),
        0x98: ("tya", "imp"),  0x99: ("sta", "aby"),  0x9A: ("txs", "imp"),  0x9B: ("txy", "imp"),
        0x9C: ("stz", "abs"),  0x9D: ("sta", "abx"),  0x9E: ("stz", "abx"),  0x9F: ("sta", "abslx"),
        0xA0: ("ldy", "imm_x"),0xA1: ("lda", "dpix"), 0xA2: ("ldx", "imm_x"),0xA3: ("lda", "sr"),
        0xA4: ("ldy", "dp"),   0xA5: ("lda", "dp"),   0xA6: ("ldx", "dp"),   0xA7: ("lda", "dpil"),
        0xA8: ("tay", "imp"),  0xA9: ("lda", "imm_m"),0xAA: ("tax", "imp"),  0xAB: ("plb", "imp"),
        0xAC: ("ldy", "abs"),  0xAD: ("lda", "abs"),  0xAE: ("ldx", "abs"),  0xAF: ("lda", "absl"),
        0xB0: ("bcs", "rel"),  0xB1: ("lda", "dpiy"), 0xB2: ("lda", "dpi"),  0xB3: ("lda", "sriy"),
        0xB4: ("ldy", "dpx"),  0xB5: ("lda", "dpx"),  0xB6: ("ldx", "dpy"),  0xB7: ("lda", "dpily"),
        0xB8: ("clv", "imp"),  0xB9: ("lda", "aby"),  0xBA: ("tsx", "imp"),  0xBB: ("tyx", "imp"),
        0xBC: ("ldy", "abx"),  0xBD: ("lda", "abx"),  0xBE: ("ldx", "aby"),  0xBF: ("lda", "abslx"),
        0xC0: ("cpy", "imm_x"),0xC1: ("cmp", "dpix"), 0xC2: ("rep", "imm8"), 0xC3: ("cmp", "sr"),
        0xC4: ("cpy", "dp"),   0xC5: ("cmp", "dp"),   0xC6: ("dec", "dp"),   0xC7: ("cmp", "dpil"),
        0xC8: ("iny", "imp"),  0xC9: ("cmp", "imm_m"),0xCA: ("dex", "imp"),  0xCB: ("wai", "imp"),
        0xCC: ("cpy", "abs"),  0xCD: ("cmp", "abs"),  0xCE: ("dec", "abs"),  0xCF: ("cmp", "absl"),
        0xD0: ("bne", "rel"),  0xD1: ("cmp", "dpiy"), 0xD2: ("cmp", "dpi"),  0xD3: ("cmp", "sriy"),
        0xD4: ("pei", "dpi"),  0xD5: ("cmp", "dpx"),  0xD6: ("dec", "dpx"),  0xD7: ("cmp", "dpily"),
        0xD8: ("cld", "imp"),  0xD9: ("cmp", "aby"),  0xDA: ("phx", "imp"),  0xDB: ("stp", "imp"),
        0xDC: ("jml", "abil"), 0xDD: ("cmp", "abx"),  0xDE: ("dec", "abx"),  0xDF: ("cmp", "abslx"),
        0xE0: ("cpx", "imm_x"),0xE1: ("sbc", "dpix"), 0xE2: ("sep", "imm8"), 0xE3: ("sbc", "sr"),
        0xE4: ("cpx", "dp"),   0xE5: ("sbc", "dp"),   0xE6: ("inc", "dp"),   0xE7: ("sbc", "dpil"),
        0xE8: ("inx", "imp"),  0xE9: ("sbc", "imm_m"),0xEA: ("nop", "imp"),  0xEB: ("xba", "imp"),
        0xEC: ("cpx", "abs"),  0xED: ("sbc", "abs"),  0xEE: ("inc", "abs"),  0xEF: ("sbc", "absl"),
        0xF0: ("beq", "rel"),  0xF1: ("sbc", "dpiy"), 0xF2: ("sbc", "dpi"),  0xF3: ("sbc", "sriy"),
        0xF4: ("pea", "imm16"),0xF5: ("sbc", "dpx"),  0xF6: ("inc", "dpx"),  0xF7: ("sbc", "dpily"),
        0xF8: ("sed", "imp"),  0xF9: ("sbc", "aby"),  0xFA: ("plx", "imp"),  0xFB: ("xce", "imp"),
        0xFC: ("jsr", "abix"), 0xFD: ("sbc", "abx"),  0xFE: ("inc", "abx"),  0xFF: ("sbc", "abslx"),
    }

    _OPCODES_6502_VALID = {
        0x00, 0x01, 0x05, 0x06, 0x08, 0x09, 0x0A, 0x0D, 0x0E,
        0x10, 0x11, 0x15, 0x16, 0x18, 0x19, 0x1D, 0x1E,
        0x20, 0x21, 0x24, 0x25, 0x26, 0x28, 0x29, 0x2A, 0x2C, 0x2D, 0x2E,
        0x30, 0x31, 0x35, 0x36, 0x38, 0x39, 0x3D, 0x3E,
        0x40, 0x41, 0x45, 0x46, 0x48, 0x49, 0x4A, 0x4C, 0x4D, 0x4E,
        0x50, 0x51, 0x55, 0x56, 0x58, 0x59, 0x5D, 0x5E,
        0x60, 0x61, 0x65, 0x66, 0x68, 0x69, 0x6A, 0x6C, 0x6D, 0x6E,
        0x70, 0x71, 0x75, 0x76, 0x78, 0x79, 0x7D, 0x7E,
        0x81, 0x84, 0x85, 0x86, 0x88, 0x8A, 0x8C, 0x8D, 0x8E,
        0x90, 0x91, 0x94, 0x95, 0x96, 0x98, 0x99, 0x9A, 0x9D,
        0xA0, 0xA1, 0xA2, 0xA4, 0xA5, 0xA6, 0xA8, 0xA9, 0xAA, 0xAC, 0xAD, 0xAE,
        0xB0, 0xB1, 0xB4, 0xB5, 0xB6, 0xB8, 0xB9, 0xBA, 0xBC, 0xBD, 0xBE,
        0xC0, 0xC1, 0xC4, 0xC5, 0xC6, 0xC8, 0xC9, 0xCA, 0xCC, 0xCD, 0xCE,
        0xD0, 0xD1, 0xD5, 0xD6, 0xD8, 0xD9, 0xDD, 0xDE,
        0xE0, 0xE1, 0xE4, 0xE5, 0xE6, 0xE8, 0xE9, 0xEA, 0xEC, 0xED, 0xEE,
        0xF0, 0xF1, 0xF5, 0xF6, 0xF8, 0xF9, 0xFD, 0xFE,
    }

    @classmethod
    def _disasm_6502(cls, address: int, data: bytes) -> DisasmInstruction:
        return cls._disasm_65816(address, data, m16=False, x16=False, is_6502=True)

    @classmethod
    def _disasm_65816(
        cls,
        address: int,
        data: bytes,
        m16: bool = False,
        x16: bool = False,
        is_6502: bool = False,
    ) -> DisasmInstruction:
        if not data:
            return DisasmInstruction(address, b"", ".byte", [])

        opcode = data[0]
        if is_6502 and opcode not in cls._OPCODES_6502_VALID:
            return DisasmInstruction(address, data[:1], ".byte", [f"0x{opcode:02X}"])

        entry = cls._OPCODES_65816.get(opcode)
        if not entry:
            return DisasmInstruction(address, data[:1], ".byte", [f"0x{opcode:02X}"])

        mnem, mode = entry

        if mode == "imp":
            size = 1
        elif mode in ("imm8", "dp", "dpx", "dpy", "dpi", "dpix", "dpiy", "dpil", "dpily", "sr", "sriy", "rel"):
            size = 2
        elif mode in ("imm16", "abs", "abx", "aby", "abi", "abix", "abil", "rell", "bm"):
            size = 3
        elif mode in ("absl", "abslx"):
            size = 4
        elif mode == "imm_m":
            size = 3 if m16 else 2
        elif mode == "imm_x":
            size = 3 if x16 else 2
        else:
            size = 1

        if len(data) < size:
            return DisasmInstruction(address, data, ".byte", [f"0x{b:02X}" for b in data])

        raw = data[:size]
        operands: List[str] = []
        target_addr: Optional[int] = None
        is_branch = False
        is_call = False
        is_return = False
        is_conditional = False

        if mode == "imp":
            if mnem in ("asl", "lsr", "rol", "ror", "dec", "inc") and opcode in (0x0A, 0x4A, 0x2A, 0x6A, 0x3A, 0x1A):
                operands = ["a"]
            else:
                operands = []
            if mnem in ("rts", "rtl", "rti"):
                is_return = True
                is_branch = True

        elif mode == "imm8":
            operands = [f"#${raw[1]:02X}"]
        elif mode == "imm16":
            val = raw[1] | (raw[2] << 8)
            operands = [f"#${val:04X}"]
        elif mode == "imm_m":
            if m16:
                val = raw[1] | (raw[2] << 8)
                operands = [f"#${val:04X}"]
            else:
                operands = [f"#${raw[1]:02X}"]
        elif mode == "imm_x":
            if x16:
                val = raw[1] | (raw[2] << 8)
                operands = [f"#${val:04X}"]
            else:
                operands = [f"#${raw[1]:02X}"]
        elif mode == "dp":
            operands = [f"${raw[1]:02X}"]
        elif mode == "dpx":
            operands = [f"${raw[1]:02X},x"]
        elif mode == "dpy":
            operands = [f"${raw[1]:02X},y"]
        elif mode == "dpi":
            operands = [f"(${raw[1]:02X})"]
        elif mode == "dpix":
            operands = [f"(${raw[1]:02X},x)"]
        elif mode == "dpiy":
            operands = [f"(${raw[1]:02X}),y"]
        elif mode == "dpil":
            operands = [f"[${raw[1]:02X}]"]
        elif mode == "dpily":
            operands = [f"[${raw[1]:02X}],y"]
        elif mode == "sr":
            operands = [f"${raw[1]:02X},s"]
        elif mode == "sriy":
            operands = [f"(${raw[1]:02X},s),y"]
        elif mode == "abs":
            val = raw[1] | (raw[2] << 8)
            operands = [f"${val:04X}"]
            if mnem in ("jsr", "jmp"):
                target_addr = val
                is_branch = True
                is_call = (mnem == "jsr")
        elif mode == "abx":
            val = raw[1] | (raw[2] << 8)
            operands = [f"${val:04X},x"]
        elif mode == "aby":
            val = raw[1] | (raw[2] << 8)
            operands = [f"${val:04X},y"]
        elif mode == "absl":
            val = raw[1] | (raw[2] << 8) | (raw[3] << 16)
            operands = [f"${val:06X}"]
            if mnem in ("jsl", "jml"):
                target_addr = val
                is_branch = True
                is_call = (mnem == "jsl")
        elif mode == "abslx":
            val = raw[1] | (raw[2] << 8) | (raw[3] << 16)
            operands = [f"${val:06X},x"]
        elif mode == "abi":
            val = raw[1] | (raw[2] << 8)
            operands = [f"(${val:04X})"]
            if mnem == "jmp":
                is_branch = True
        elif mode == "abix":
            val = raw[1] | (raw[2] << 8)
            operands = [f"(${val:04X},x)"]
            if mnem in ("jmp", "jsr"):
                is_branch = True
                is_call = (mnem == "jsr")
        elif mode == "abil":
            val = raw[1] | (raw[2] << 8)
            operands = [f"[${val:04X}]"]
            if mnem == "jml":
                is_branch = True
        elif mode == "rel":
            disp = struct.unpack("b", bytes([raw[1]]))[0]
            target = (address + 2 + disp) & (0xFFFF if is_6502 else 0xFFFFFF)
            operands = [f"0x{target:04X}"]
            target_addr = target
            is_branch = True
            is_conditional = (mnem != "bra")
        elif mode == "rell":
            disp16 = struct.unpack("<h", raw[1:3])[0]
            target = (address + 3 + disp16) & 0xFFFFFF
            operands = [f"0x{target:04X}"]
            target_addr = target
            is_branch = (mnem == "brl")
        elif mode == "bm":
            dst = raw[1]
            src = raw[2]
            operands = [f"${src:02X}", f"${dst:02X}"]

        return DisasmInstruction(
            address=address,
            raw_bytes=raw,
            mnemonic=mnem,
            operands=operands,
            target_address=target_addr,
            is_branch=is_branch,
            is_call=is_call,
            is_return=is_return,
            is_conditional=is_conditional,
        )

    @classmethod
    def _disassemble_impl(
        cls,
        data: bytes,
        base_address: int = 0,
        arch: str = "ppc",
        endian: Optional[str] = None,
        max_instructions: Optional[int] = None,
        m16: bool = False,
        x16: bool = False,
        **kwargs,
    ) -> List[DisasmInstruction]:
        """
        Disassemble a contiguous block of bytes into a list of DisasmInstruction objects.
        """
        instructions: List[DisasmInstruction] = []
        offset = 0
        arch_l = arch.lower()
        if arch_l in ("thumb", "arm_thumb", "m68k", "68000", "md", "genesis", "megadrive"):
            step = 2
        elif arch_l in ("sm83", "gb", "gbc", "gameboy", "6502", "nes", "famicom", "2a03", "65816", "snes", "sfc", "5a22", "w65c816"):
            step = 1
        else:
            step = 4

        curr_m16 = m16
        curr_x16 = x16

        while offset < len(data):
            if max_instructions and len(instructions) >= max_instructions:
                break
            chunk_len = min(4, len(data) - offset)
            ins = cls.disassemble_instruction(
                address=base_address + offset,
                raw_bytes=data[offset : offset + chunk_len],
                arch=arch,
                endian=endian,
                m16=curr_m16,
                x16=curr_x16,
            )
            instructions.append(ins)

            # Dynamically track 65816 accumulator & index size state
            if arch_l in ("65816", "snes", "sfc", "5a22", "w65c816"):
                if ins.mnemonic == "rep" and len(ins.raw_bytes) >= 2:
                    imm = ins.raw_bytes[1]
                    if imm & 0x20:
                        curr_m16 = True
                    if imm & 0x10:
                        curr_x16 = True
                elif ins.mnemonic == "sep" and len(ins.raw_bytes) >= 2:
                    imm = ins.raw_bytes[1]
                    if imm & 0x20:
                        curr_m16 = False
                    if imm & 0x10:
                        curr_x16 = False

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
