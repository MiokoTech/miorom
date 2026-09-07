"""
miorom.text.transmuter
~~~~~~~~~~~~~~~~~~~~~~
2-Byte to 1-Byte Text Encoding Transmuter & ASM Narrowing Patcher.
Enables doubling text capacity in Japanese ROMs by transmuting 2-byte wide encodings
(Shift-JIS / UTF-16) to 1-byte single-byte Latin encodings, and synthesizing
ASM narrowing patches (LDRH -> LDRB) so game engines natively read 1 byte per character.
"""

from dataclasses import dataclass
import struct
from typing import Dict, List, Optional, Tuple, Union

from miorom.text.charmap import CharMap


class EncodingTransmuter:
    """
    Transmutes wide-character text streams to single-byte streams and patches renderers.
    """

    @classmethod
    def compress_utf16_to_latin1(cls, data: bytes, endian: str = "<") -> bytes:
        """
        Compresses UTF-16 text to 1-byte Latin-1/ASCII by taking the low byte
        of each 2-byte codepoint.
        """
        fmt = f"{endian}H"
        n_chars = len(data) // 2
        out = bytearray()
        for i in range(n_chars):
            val = struct.unpack_from(fmt, data, i * 2)[0]
            out.append(val & 0xFF)
        return bytes(out)

    @classmethod
    def expand_latin1_to_utf16(cls, text: str, endian: str = "<") -> bytes:
        """
        Expands 1-byte text into 2-byte UTF-16 representation.
        """
        fmt = f"{endian}H"
        out = bytearray()
        for char in text:
            val = ord(char) & 0xFFFF
            out.extend(struct.pack(fmt, val))
        return bytes(out)

    @classmethod
    def patch_arm_ldrh_to_ldrb(
        cls,
        code: bytearray,
        instruction_offset: int,
        endian: str = "<",
    ) -> bool:
        """
        Transmutes an ARM32 LDRH instruction to an LDRB instruction to switch
        from reading 2-byte characters to 1-byte characters.
        """
        if instruction_offset + 4 > len(code):
            return False

        word = struct.unpack_from(f"{endian}I", code, instruction_offset)[0]

        # Check if instruction is LDRH (bits 7..4 = 1011 = 0xB, bits 27..25 = 000)
        # ARM LDRH: cond 000 P U 0 W 1 Rn Rd imm4 1 0 1 1 imm4
        is_ldrh = ((word >> 25) & 0x7) == 0 and ((word >> 4) & 0xF) == 0xB
        if is_ldrh:
            cond = (word >> 28) & 0xF
            u_bit = (word >> 23) & 1
            rn = (word >> 16) & 0xF
            rd = (word >> 12) & 0xF
            imm_hi = (word >> 8) & 0xF
            imm_lo = word & 0xF
            offset_imm = (imm_hi << 4) | imm_lo

            # Synthesize LDRB Rd, [Rn, #offset_imm]
            # ARM LDRB immediate: cond 0101 U 1 0 1 Rn Rd offset_imm12
            u_flag = 0x00800000 if u_bit else 0
            new_opcode = (cond << 28) | 0x05500000 | u_flag | (rn << 16) | (rd << 12) | (offset_imm & 0xFFF)
            struct.pack_into(f"{endian}I", code, instruction_offset, new_opcode)
            return True

        return False
