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
        endian: str = ">",
    ) -> List[DiscoveredFunction]:
        arch_norm = arch.lower()
        funcs: List[DiscoveredFunction] = []

        if "mips" in arch_norm:
            # MIPS prologue: addiu $sp, $sp, -imm (0x27BDxxxx where xxxx >= 0x8000)
            fmt = f"{endian}I"
            for i in range(0, len(data) - 3, 4):
                word = struct.unpack_from(fmt, data, i)[0]
                if (word >> 16) == 0x27BD and (word & 0x8000) != 0:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="mips",
                        confidence=0.95,
                        prologue_mnemonic="addiu $sp, $sp, -imm",
                    ))

        elif "arm" in arch_norm:
            # ARM prologue: push {..., lr} (stmdb sp!, {...}) -> 0xE92D4xxx or 0xE92D5xxx
            fmt = f"{endian}I"
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
            fmt = f"{endian}I"
            for i in range(0, len(data) - 3, 4):
                word = struct.unpack_from(fmt, data, i)[0]
                if (word >> 16) == 0x9421 and (word & 0x8000) != 0:
                    funcs.append(DiscoveredFunction(
                        address=base_address + i,
                        architecture="ppc",
                        confidence=0.95,
                        prologue_mnemonic="stwu r1, -imm(r1)",
                    ))

        return funcs
