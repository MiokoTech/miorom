"""
miorom.asm.m68k
~~~~~~~~~~~~~~~
Sega Genesis / Mega Drive Motorola 68000 disassembler.
"""

import struct
from dataclasses import dataclass
from typing import List, Optional, Union

from miorom.result import MioRomResult


@dataclass
class M68kInstruction(MioRomResult):
    """A single decoded 68000 instruction."""

    offset: int
    bytes_: bytes
    mnemonic: str
    operands: str
    size: int
    is_branch: bool = False
    is_call: bool = False
    is_return: bool = False
    branch_target: Optional[int] = None

    @property
    def text(self) -> str:
        return f"{self.mnemonic} {self.operands}".strip()


# Bcc condition code names indexed by condition field (bits 11:8 of opcode)
_BCC_NAMES = [
    "BRA", "BSR", "BHI", "BLS", "BCC", "BCS", "BNE", "BEQ",
    "BVC", "BVS", "BPL", "BMI", "BGE", "BLT", "BGT", "BLE",
]

# Size suffix table for MOVE/ADD/SUB size field encoding
_SIZE_SUFFIX = {0b00: ".b", 0b01: ".w", 0b10: ".l"}

# Standard size suffix for ADD/SUB/CMP opword size field
_SZ2_SUFFIX = {0b00: ".b", 0b01: ".w", 0b10: ".l"}

# Data register names
_DREG = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]
# Address register names
_AREG = ["A0", "A1", "A2", "A3", "A4", "A5", "A6", "SP"]


def _read_word(data: Union[bytes, bytearray], offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _read_long(data: Union[bytes, bytearray], offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _sign_ext(value: int, bits: int) -> int:
    """Sign-extend an integer from 'bits' wide to Python int."""
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def _ea_operand(
    mode: int,
    reg: int,
    data: Union[bytes, bytearray],
    ext_offset: int,
    sz: Optional[str] = None,
) -> tuple:
    """
    Decode an effective address operand.
    Returns (operand_text, bytes_consumed).
    ext_offset is the file offset of the first extension word.
    """
    consumed = 0

    if mode == 0b000:
        return _DREG[reg], 0
    if mode == 0b001:
        return _AREG[reg], 0
    if mode == 0b010:
        return f"({_AREG[reg]})", 0
    if mode == 0b011:
        return f"({_AREG[reg]})+", 0
    if mode == 0b100:
        return f"-({_AREG[reg]})", 0
    if mode == 0b101:
        if ext_offset + 2 > len(data):
            return "?", 0
        disp = _sign_ext(_read_word(data, ext_offset), 16)
        consumed = 2
        return f"{disp}({_AREG[reg]})", consumed
    if mode == 0b110:
        if ext_offset + 2 > len(data):
            return "?", 0
        ext = _read_word(data, ext_offset)
        disp = _sign_ext(ext & 0xFF, 8)
        ireg = (ext >> 12) & 7
        itype = "A" if (ext >> 15) & 1 else "D"
        consumed = 2
        return f"{disp}({_AREG[reg]},{itype}{ireg})", consumed

    if mode == 0b111:
        if reg == 0b000:
            if ext_offset + 2 > len(data):
                return "?", 0
            addr = _read_word(data, ext_offset)
            consumed = 2
            return f"${addr:04X}.w", consumed
        if reg == 0b001:
            if ext_offset + 4 > len(data):
                return "?", 0
            addr = _read_long(data, ext_offset)
            consumed = 4
            return f"${addr:08X}.l", consumed
        if reg == 0b100:
            if sz == ".l":
                if ext_offset + 4 > len(data):
                    return "?", 0
                imm = _read_long(data, ext_offset)
                consumed = 4
                return f"#${imm:08X}", consumed
            else:
                if ext_offset + 2 > len(data):
                    return "?", 0
                imm = _read_word(data, ext_offset)
                consumed = 2
                if sz == ".b":
                    return f"#{imm & 0xFF}", consumed
                return f"#{imm}", consumed
        if reg == 0b010:
            if ext_offset + 2 > len(data):
                return "?", 0
            disp = _sign_ext(_read_word(data, ext_offset), 16)
            consumed = 2
            return f"{disp}(PC)", consumed
        if reg == 0b011:
            if ext_offset + 2 > len(data):
                return "?", 0
            ext = _read_word(data, ext_offset)
            disp = _sign_ext(ext & 0xFF, 8)
            ireg = (ext >> 12) & 7
            itype = "A" if (ext >> 15) & 1 else "D"
            consumed = 2
            return f"{disp}(PC,{itype}{ireg})", consumed

    return "?", 0


class M68kDisassembler:
    """Motorola 68000 disassembler targeting Sega Genesis / Mega Drive ROMs."""

    SIZE_SUFFIX = {0b00: ".b", 0b01: ".w", 0b10: ".l"}

    def disassemble_one(
        self, data: Union[bytes, bytearray], offset: int = 0
    ) -> M68kInstruction:
        """Decode a single M68K instruction at offset within data."""
        if offset + 2 > len(data):
            raw = bytes(data[offset : offset + 2]) if offset < len(data) else b""
            return M68kInstruction(
                offset=offset, bytes_=raw, mnemonic="DC.W",
                operands="?", size=2,
            )

        word = _read_word(data, offset)
        top4 = (word >> 12) & 0xF
        ext = offset + 2

        # --- NOP ---
        if word == 0x4E71:
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="NOP", operands="", size=2,
            )

        # --- ILLEGAL ---
        if word == 0x4AFC:
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="ILLEGAL", operands="", size=2,
            )

        # --- RTS ---
        if word == 0x4E75:
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="RTS", operands="", size=2, is_return=True,
            )

        # --- RTR ---
        if word == 0x4E77:
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="RTR", operands="", size=2, is_return=True,
            )

        # --- RTE ---
        if word == 0x4E73:
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="RTE", operands="", size=2, is_return=True,
            )

        # --- TRAP #n (0x4E40..0x4E4F) ---
        if 0x4E40 <= word <= 0x4E4F:
            vec = word & 0xF
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="TRAP", operands=f"#{vec}", size=2,
            )

        # --- Bcc / BRA / BSR (opcode top nibble 0x6) ---
        if top4 == 0x6:
            cond = (word >> 8) & 0xF
            mnem = _BCC_NAMES[cond]
            disp8 = word & 0xFF
            is_call = mnem == "BSR"
            sz = 2
            if disp8 == 0x00:
                if ext + 2 > len(data):
                    return M68kInstruction(
                        offset=offset, bytes_=bytes(data[offset:ext]),
                        mnemonic=mnem, operands="?", size=2,
                        is_branch=(not is_call), is_call=is_call,
                    )
                disp16 = _sign_ext(_read_word(data, ext), 16)
                target = (offset + 2) + disp16
                sz = 4
                raw = bytes(data[offset : offset + sz])
                return M68kInstruction(
                    offset=offset, bytes_=raw, mnemonic=mnem,
                    operands=f"${target:08X}", size=sz,
                    is_branch=(not is_call), is_call=is_call,
                    branch_target=target,
                )
            elif disp8 == 0xFF:
                if ext + 4 > len(data):
                    return M68kInstruction(
                        offset=offset, bytes_=bytes(data[offset:ext]),
                        mnemonic=mnem, operands="?", size=2,
                        is_branch=(not is_call), is_call=is_call,
                    )
                disp32 = _sign_ext(_read_long(data, ext), 32)
                target = (offset + 2) + disp32
                sz = 6
                raw = bytes(data[offset : offset + sz])
                return M68kInstruction(
                    offset=offset, bytes_=raw, mnemonic=mnem,
                    operands=f"${target:08X}", size=sz,
                    is_branch=(not is_call), is_call=is_call,
                    branch_target=target,
                )
            else:
                disp = _sign_ext(disp8, 8)
                target = (offset + 2) + disp
                raw = bytes(data[offset : offset + 2])
                return M68kInstruction(
                    offset=offset, bytes_=raw, mnemonic=mnem,
                    operands=f"${target:08X}", size=2,
                    is_branch=(not is_call), is_call=is_call,
                    branch_target=target,
                )

        # --- MOVEQ (0x7xxx) ---
        if top4 == 0x7 and not (word & 0x0100):
            dn = (word >> 9) & 7
            imm8 = _sign_ext(word & 0xFF, 8)
            return M68kInstruction(
                offset=offset, bytes_=bytes(data[offset:ext]),
                mnemonic="MOVEQ", operands=f"#{imm8}, {_DREG[dn]}", size=2,
            )

        # --- JSR / JMP (0x4Exx) ---
        if 0x4E80 <= word <= 0x4EFF:
            is_jsr = word <= 0x4EBF
            mnem = "JSR" if is_jsr else "JMP"
            mode = (word >> 3) & 7
            reg = word & 7
            op_text, consumed = _ea_operand(mode, reg, data, ext)
            total = 2 + consumed
            raw = bytes(data[offset : offset + total])
            target: Optional[int] = None
            if mode == 0b111 and reg == 0b001 and consumed == 4:
                target = _read_long(data, ext)
            elif mode == 0b111 and reg == 0b000 and consumed == 2:
                target = _read_word(data, ext)
            return M68kInstruction(
                offset=offset, bytes_=raw, mnemonic=mnem,
                operands=op_text, size=total,
                is_call=is_jsr, is_branch=(not is_jsr),
                branch_target=target,
            )

        # --- LEA (0x4xx7 where bits 8:6 = 111) ---
        if top4 == 0x4 and (word & 0x01C0) == 0x01C0 and ((word >> 9) & 0x7) <= 7:
            an = (word >> 9) & 7
            mode = (word >> 3) & 7
            reg = word & 7
            op_text, consumed = _ea_operand(mode, reg, data, ext)
            total = 2 + consumed
            raw = bytes(data[offset : offset + total])
            return M68kInstruction(
                offset=offset, bytes_=raw, mnemonic="LEA",
                operands=f"{op_text}, {_AREG[an]}", size=total,
            )

        # --- MOVE.b (0x1), MOVE.l (0x2), MOVE.w (0x3) ---
        if top4 in (0x1, 0x2, 0x3):
            sz_map = {0x1: ".b", 0x2: ".l", 0x3: ".w"}
            sfx = sz_map[top4]
            src_mode = (word >> 3) & 7
            src_reg = word & 7
            dst_reg = (word >> 9) & 7
            dst_mode = (word >> 6) & 7

            src_text, src_consumed = _ea_operand(src_mode, src_reg, data, ext, sz=sfx)
            ext2 = ext + src_consumed
            dst_text, dst_consumed = _ea_operand(dst_mode, dst_reg, data, ext2, sz=sfx)
            total = 2 + src_consumed + dst_consumed

            is_movea = (dst_mode == 0b001)
            mnem = f"MOVEA{sfx}" if is_movea else f"MOVE{sfx}"

            raw = bytes(data[offset : offset + total])
            return M68kInstruction(
                offset=offset, bytes_=raw, mnemonic=mnem,
                operands=f"{src_text}, {dst_text}", size=total,
            )

        # --- ADD / ADDA / SUB / SUBA (top4 0xD=ADD/ADDA, 0x9=SUB/SUBA) ---
        if top4 in (0x9, 0xD):
            mnem_base = "ADD" if top4 == 0xD else "SUB"
            dn = (word >> 9) & 7
            direction = (word >> 8) & 1
            sz_bits = (word >> 6) & 3
            mode = (word >> 3) & 7
            reg = word & 7

            if sz_bits == 0b11:
                sfx = ".l" if direction else ".w"
                op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
                total = 2 + consumed
                raw = bytes(data[offset : offset + total])
                return M68kInstruction(
                    offset=offset, bytes_=raw,
                    mnemonic=f"{mnem_base}A{sfx}",
                    operands=f"{op_text}, {_AREG[dn]}", size=total,
                )

            sfx = _SZ2_SUFFIX.get(sz_bits, "")
            op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
            total = 2 + consumed
            raw = bytes(data[offset : offset + total])
            if direction == 0:
                operands = f"{op_text}, {_DREG[dn]}"
            else:
                operands = f"{_DREG[dn]}, {op_text}"
            return M68kInstruction(
                offset=offset, bytes_=raw,
                mnemonic=f"{mnem_base}{sfx}", operands=operands, size=total,
            )

        # --- CMP / CMPA (top4 0xB) ---
        if top4 == 0xB:
            dn = (word >> 9) & 7
            opmode = (word >> 6) & 7
            mode = (word >> 3) & 7
            reg = word & 7

            if opmode in (0b011, 0b111):
                sfx = ".l" if opmode == 0b111 else ".w"
                op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
                total = 2 + consumed
                raw = bytes(data[offset : offset + total])
                return M68kInstruction(
                    offset=offset, bytes_=raw,
                    mnemonic=f"CMPA{sfx}",
                    operands=f"{op_text}, {_AREG[dn]}", size=total,
                )

            sz_bits = opmode & 3
            sfx = _SZ2_SUFFIX.get(sz_bits, "")
            op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
            total = 2 + consumed
            raw = bytes(data[offset : offset + total])
            return M68kInstruction(
                offset=offset, bytes_=raw,
                mnemonic=f"CMP{sfx}",
                operands=f"{op_text}, {_DREG[dn]}", size=total,
            )

        # --- CMPI (0x0C) ---
        if top4 == 0x0 and (word >> 8) == 0x0C:
            sz_bits = (word >> 6) & 3
            sfx = _SZ2_SUFFIX.get(sz_bits, "")
            mode = (word >> 3) & 7
            reg = word & 7
            imm_text, imm_consumed = _ea_operand(7, 4, data, ext, sz=sfx)
            ext2 = ext + imm_consumed
            ea_text, ea_consumed = _ea_operand(mode, reg, data, ext2, sz=sfx)
            total = 2 + imm_consumed + ea_consumed
            raw = bytes(data[offset : offset + total])
            return M68kInstruction(
                offset=offset, bytes_=raw,
                mnemonic=f"CMPI{sfx}",
                operands=f"{imm_text}, {ea_text}", size=total,
            )

        # --- ADDI (0x06) / SUBI (0x04) ---
        if top4 == 0x0 and (word >> 8) in (0x04, 0x06):
            kind = "ADDI" if (word >> 8) == 0x06 else "SUBI"
            sz_bits = (word >> 6) & 3
            sfx = _SZ2_SUFFIX.get(sz_bits, "")
            mode = (word >> 3) & 7
            reg = word & 7
            imm_text, imm_consumed = _ea_operand(7, 4, data, ext, sz=sfx)
            ext2 = ext + imm_consumed
            ea_text, ea_consumed = _ea_operand(mode, reg, data, ext2, sz=sfx)
            total = 2 + imm_consumed + ea_consumed
            raw = bytes(data[offset : offset + total])
            return M68kInstruction(
                offset=offset, bytes_=raw,
                mnemonic=f"{kind}{sfx}",
                operands=f"{imm_text}, {ea_text}", size=total,
            )

        # --- AND (top4 0xC) ---
        if top4 == 0xC:
            dn = (word >> 9) & 7
            direction = (word >> 8) & 1
            sz_bits = (word >> 6) & 3
            mode = (word >> 3) & 7
            reg = word & 7
            if sz_bits == 0b11:
                pass
            else:
                sfx = _SZ2_SUFFIX.get(sz_bits, "")
                op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
                total = 2 + consumed
                raw = bytes(data[offset : offset + total])
                if direction == 0:
                    operands = f"{op_text}, {_DREG[dn]}"
                else:
                    operands = f"{_DREG[dn]}, {op_text}"
                return M68kInstruction(
                    offset=offset, bytes_=raw,
                    mnemonic=f"AND{sfx}", operands=operands, size=total,
                )

        # --- OR (top4 0x8) ---
        if top4 == 0x8:
            dn = (word >> 9) & 7
            direction = (word >> 8) & 1
            sz_bits = (word >> 6) & 3
            mode = (word >> 3) & 7
            reg = word & 7
            if sz_bits == 0b11:
                pass
            else:
                sfx = _SZ2_SUFFIX.get(sz_bits, "")
                op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
                total = 2 + consumed
                raw = bytes(data[offset : offset + total])
                if direction == 0:
                    operands = f"{op_text}, {_DREG[dn]}"
                else:
                    operands = f"{_DREG[dn]}, {op_text}"
                return M68kInstruction(
                    offset=offset, bytes_=raw,
                    mnemonic=f"OR{sfx}", operands=operands, size=total,
                )

        # --- EOR (top4 0xB, direction=1) ---
        if top4 == 0xB and ((word >> 8) & 1) == 1:
            dn = (word >> 9) & 7
            sz_bits = (word >> 6) & 3
            mode = (word >> 3) & 7
            reg = word & 7
            sfx = _SZ2_SUFFIX.get(sz_bits, "")
            op_text, consumed = _ea_operand(mode, reg, data, ext, sz=sfx)
            total = 2 + consumed
            raw = bytes(data[offset : offset + total])
            return M68kInstruction(
                offset=offset, bytes_=raw,
                mnemonic=f"EOR{sfx}",
                operands=f"{_DREG[dn]}, {op_text}", size=total,
            )

        # Fallback: DC.W
        raw = bytes(data[offset:ext])
        return M68kInstruction(
            offset=offset, bytes_=raw,
            mnemonic="DC.W", operands=f"${word:04X}", size=2,
        )

    def disassemble(
        self,
        data: Union[bytes, bytearray],
        start: int = 0,
        count: Optional[int] = None,
        end: Optional[int] = None,
    ) -> List[M68kInstruction]:
        """Disassemble up to count instructions or until end offset."""
        instructions: List[M68kInstruction] = []
        pos = start
        limit = end if end is not None else len(data)

        while pos < limit:
            if count is not None and len(instructions) >= count:
                break
            instr = self.disassemble_one(data, pos)
            instructions.append(instr)
            pos += instr.size

        return instructions

    def format_listing(
        self, instructions: List[M68kInstruction], base_offset: int = 0
    ) -> str:
        """Format instructions as a hex+text listing."""
        lines = []
        for instr in instructions:
            addr = instr.offset + base_offset
            hex_bytes = " ".join(
                f"{instr.bytes_[i:i+2].hex().upper():4s}"
                for i in range(0, len(instr.bytes_), 2)
            )
            text = instr.text
            lines.append(f"{addr:06X}: {hex_bytes:<20} {text}")
        return "\n".join(lines)
