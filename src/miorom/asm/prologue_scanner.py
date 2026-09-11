"""
miorom.asm.prologue_scanner
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automated Function Boundary Detection via Machine Code Prologue Preamble Masks.
Identifies function start addresses across MIPS, ARM, and PowerPC binaries
without relying solely on return instructions.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional
from miorom.result import MioRomResult


@dataclass
class DiscoveredFunction(MioRomResult):
    address: int
    architecture: str
    confidence: float
    prologue_mnemonic: str


class FunctionPrologueScanner:
    """
    Scans executable machine code for canonical function prologue patterns.
    """

    @classmethod
    def scan(
        cls,
        data: bytes,
        base_address: int = 0,
        arch: str = "mips",
        endian: Optional[str] = None,
    ) -> List[DiscoveredFunction]:
        arch_norm = arch.lower()
        if endian is None:
            end_char = "<" if any(a in arch_norm for a in ("arm", "thumb", "gba", "nds", "sm83")) else ">"
        else:
            end_char = ">" if endian in (">", "big", "be") else "<"
        funcs: List[DiscoveredFunction] = []

        if "mips" in arch_norm:
            # MIPS prologue: addiu $sp, $sp, -imm (0x27BDxxxx where xxxx >= 0x8000)
            fmt = f"{end_char}I"
            for i in range(0, len(data) - 3, 4):
                word = struct.unpack_from(fmt, data, i)[0]
                if (word >> 16) == 0x27BD and (word & 0x8000) != 0:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="mips",
                        confidence=0.95,
                        prologue_mnemonic="addiu $sp, $sp, -imm",
                    ))

        elif arch_norm in ("thumb", "arm_thumb"):
            # Thumb prologue: push {..., lr} -> 0xB5xx (16-bit halfword)
            fmt = f"{end_char}H"
            for i in range(0, len(data) - 1, 2):
                hword = struct.unpack_from(fmt, data, i)[0]
                if (hword & 0xFF00) == 0xB500:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="thumb",
                        confidence=0.95,
                        prologue_mnemonic="push {..., lr}",
                    ))

        elif "arm" in arch_norm:
            # ARM stmdb sp!, {..., lr}
            fmt = f"{end_char}I"
            for i in range(0, len(data) - 3, 4):
                word = struct.unpack_from(fmt, data, i)[0]
                if (word & 0xFFFF4000) == 0xE92D4000:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="arm",
                        confidence=0.95,
                        prologue_mnemonic="push {..., lr}",
                    ))

        elif arch_norm in ("ppc", "powerpc"):
            # PowerPC prologue: stwu r1, -imm(r1) -> 0x9421xxxx where xxxx is negative
            fmt = f"{end_char}I"
            for i in range(0, len(data) - 3, 4):
                word = struct.unpack_from(fmt, data, i)[0]
                if (word >> 16) == 0x9421 and (word & 0x8000) != 0:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="ppc",
                        confidence=0.95,
                        prologue_mnemonic="stwu r1, -imm(r1)",
                    ))

        elif arch_norm in ("65816", "snes", "sfc", "5a22", "w65c816"):
            # 65816 / SNES prologue patterns:
            # php; rep #$xx (0x08, 0xC2)
            # rep #$20; pha / rep #$30; pha (0xC2, 0x20/0x30, 0x48)
            # phb; phd (0x8B, 0x0B)
            for i in range(0, len(data) - 1):
                if data[i] == 0x08 and i + 1 < len(data) and data[i + 1] == 0xC2:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="65816",
                        confidence=0.95,
                        prologue_mnemonic="php; rep",
                    ))
                elif data[i] == 0xC2 and (data[i + 1] in (0x20, 0x30, 0x10)) and i + 2 < len(data) and data[i + 2] in (0x48, 0xDA, 0x5A, 0x8B):
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="65816",
                        confidence=0.95,
                        prologue_mnemonic="rep; pha",
                    ))
                elif data[i] == 0x8B and i + 1 < len(data) and data[i + 1] == 0x0B:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="65816",
                        confidence=0.90,
                        prologue_mnemonic="phb; phd",
                    ))

        elif arch_norm in ("6502", "nes", "famicom", "2a03"):
            # 6502 / NES prologue patterns:
            # php; pha (0x08, 0x48)
            # pha; txa; pha (0x48, 0x8A, 0x48)
            for i in range(0, len(data) - 1):
                if data[i] == 0x08 and data[i + 1] == 0x48:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="6502",
                        confidence=0.95,
                        prologue_mnemonic="php; pha",
                    ))
                elif data[i] == 0x48 and data[i + 1] == 0x8A and i + 2 < len(data) and data[i + 2] == 0x48:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="6502",
                        confidence=0.90,
                        prologue_mnemonic="pha; txa; pha",
                    ))

        return funcs
