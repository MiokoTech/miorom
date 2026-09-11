"""
miorom.text.vwf_injector
~~~~~~~~~~~~~~~~~~~~~~~~
Dynamic Variable-Width Font (VWF) Hook Synthesizer & Width Table Builder.
Transforms fixed-width (monospace 12x12/16x16) game font rendering routines
into proportional variable-width renderers by compiling glyph width lookup tables
and synthesizing assembly trampoline hooks (ARM, MIPS, 65816).
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.text.vwf import GlyphWidthTable


@dataclass
class VWFHookReport(MioRomResult):
    """Report on generated VWF width table and trampoline hook."""
    arch: str
    table_size: int
    table_bytes: bytes
    trampoline_bytes: bytes


class DynamicVWFInjector:
    """
    Generates binary width lookup tables and ASM hook stubs for proportional text rendering.
    """

    @classmethod
    def build_width_table_binary(
        cls,
        glyph_widths: Union[GlyphWidthTable, Dict[int, int]],
        default_width: int = 8,
        start_char: int = 0x20,
        count: int = 96,
    ) -> bytes:
        """
        Builds a contiguous binary table of glyph widths (1 byte per char).
        """
        table = bytearray(count)
        for i in range(count):
            char_code = start_char + i
            if isinstance(glyph_widths, GlyphWidthTable):
                fn = getattr(glyph_widths, "get_char_width", getattr(glyph_widths, "get_width", None))
                w = fn(chr(char_code)) if fn else default_width
            else:
                w = glyph_widths.get(char_code, default_width)

            table[i] = max(1, min(255, w if w > 0 else default_width))

        return bytes(table)

    @classmethod
    def generate_arm_vwf_hook(
        cls,
        table_vaddr: int,
        fallback_width: int = 12,
        endian: str = "<",
    ) -> bytes:
        """
        Generates an ARM32 assembly hook function for glyph width lookup:
        - Input: r0 = char code, r1 = cursor X position
        - Output: r1 = updated cursor X position (X += width[r0])
        """
        # Minimal ARM32 instructions:
        # 0x00: CMP r0, #0x20                 (0xE3500020)
        # 0x04: BLT fallback (PC+0x18)        (0xBA000004)
        # 0x08: SUB r0, r0, #0x20             (0xE2400020)
        # 0x0C: LDR r2, [PC, #8] -> table_vaddr (0xE59F2008)
        # 0x10: LDRB r3, [r2, r0]             (0xE7D23000)
        # 0x14: ADD r1, r1, r3                (0xE0811003)
        # 0x18: BX lr                         (0xE12FFF1E)
        # fallback:
        # 0x1C: ADD r1, r1, #fallback_width
        # 0x20: BX lr                         (0xE12FFF1E)
        # pool:
        # 0x24: table_vaddr (32-bit literal)
        buf = bytearray()
        buf.extend(struct.pack(f"{endian}I", 0xE3500020))
        buf.extend(struct.pack(f"{endian}I", 0xBA000004))
        buf.extend(struct.pack(f"{endian}I", 0xE2400020))
        buf.extend(struct.pack(f"{endian}I", 0xE59F2008))
        buf.extend(struct.pack(f"{endian}I", 0xE7D23000))
        buf.extend(struct.pack(f"{endian}I", 0xE0811003))
        buf.extend(struct.pack(f"{endian}I", 0xE12FFF1E))
        buf.extend(struct.pack(f"{endian}I", 0xE2811000 | (fallback_width & 0xFF)))
        buf.extend(struct.pack(f"{endian}I", 0xE12FFF1E))
        buf.extend(struct.pack(f"{endian}I", table_vaddr))
        return bytes(buf)

    @classmethod
    def generate_mips_vwf_hook(
        cls,
        table_vaddr: int,
        fallback_width: int = 12,
        endian: str = "<",
    ) -> bytes:
        """
        Generates a MIPS assembly hook function for glyph width lookup:
        - Input: $a0 = char code, $a1 = cursor X position
        - Output: $a1 = updated cursor X ($a1 += width)
        """
        # MIPS32 instructions:
        # lui $t0, %hi(table_vaddr)
        # addu $t0, $t0, $a0
        # lb $t1, %lo(table_vaddr)($t0)
        # addu $a1, $a1, $t1
        # jr $ra
        # nop
        hi = (table_vaddr >> 16) & 0xFFFF
        lo = table_vaddr & 0xFFFF
        if lo >= 0x8000:
            hi = (hi + 1) & 0xFFFF

        lui = 0x3C080000 | hi             # lui $t0, hi
        addu = 0x01044021                 # addu $t0, $t0, $a0
        lb = 0x81090000 | lo              # lb $t1, lo($t0)
        addu_res = 0x00A92821             # addu $a1, $a1, $t1
        jr = 0x03E00008                   # jr $ra
        nop = 0x00000000                  # nop

        buf = bytearray()
        for op in (lui, addu, lb, addu_res, jr, nop):
            buf.extend(struct.pack(f"{endian}I", op))
        return bytes(buf)

    @classmethod
    def generate_snes_vwf_hook(
        cls,
        table_bank: int,
        table_offset: int,
    ) -> bytes:
        """
        Generates a 65816 SNES assembly hook stub to lookup width from 24-bit far table.
        """
        return bytes([
            0x08,                      # PHP
            0xC2, 0x20,                # REP #$20 (16-bit A)
            0x8B,                      # PHB
            0xA9, table_bank, 0x00,    # LDA #table_bank
            0x48,                      # PHA
            0xAB,                      # PLB
            0xBF, table_offset & 0xFF, (table_offset >> 8) & 0xFF, table_bank,  # LDA.L table, X
            0xAB,                      # PLB
            0x28,                      # PLP
            0x6B,                      # RTL
        ])
