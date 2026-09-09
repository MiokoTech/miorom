"""
miorom.asm.ap_bypass
~~~~~~~~~~~~~~~~~~~~
Anti-Piracy (AP) & ROM Integrity Bypass Engine.
Detects anti-tamper routines, checksum verification loops, and hardware sanity checks,
and generates surgical patches to bypass integrity barriers on modified ROMs.
"""

from miorom.result import MioRomResult
import re
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class APVectorType(str, Enum):
    CHECKSUM_LOOP = "checksum_loop"
    CARTRIDGE_CHECK = "cartridge_check"
    MIRROR_CHECK = "mirror_check"
    INTEGRITY_CMP = "integrity_cmp"
    GENERIC = "generic"


@dataclass
class APMatch(MioRomResult):
    offset: int
    vector_type: APVectorType
    arch: str
    description: str
    original_bytes: bytes
    patch_bytes: bytes

    def summary(self) -> str:
        return (
            f"[0x{self.offset:08X}] ({self.vector_type.value}) {self.description} "
            f"[{len(self.patch_bytes)} bytes patch]"
        )


@dataclass
class APBypassReport(MioRomResult):
    total_scanned: int
    matches: List[APMatch] = field(default_factory=list)
    patched_count: int = 0

    def summary(self) -> str:
        lines = [
            "==================================================",
            "        Anti-Piracy & Integrity Bypass Report     ",
            "==================================================",
            f"  Scanned Size    : {self.total_scanned} bytes",
            f"  AP Vectors Found: {len(self.matches)}",
            f"  Patches Applied : {self.patched_count}",
        ]
        if self.matches:
            lines.append("  Detected AP Check Locations:")
            for m in self.matches:
                lines.append(f"    - {m.summary()}")
        lines.append("==================================================")
        return "\n".join(lines)


class AntiPiracyBypasser:
    """
    Autonomous Anti-Piracy and Integrity Protection Bypass Engine.
    Scans binary streams for anti-tamper loops and applies precision patches.
    """

    # NDS Cartridge register 0x040001A4 (ROMCTRL) access patterns
    NDS_ROMCTRL_PATTERNS = [
        # ldr rX, =0x040001A4
        b"\xa4\x01\x00\x04",
        b"\x04\x01\x00\x04",
    ]

    # ARM NOP: mov r0, r0 (0xE1A00000)
    ARM_NOP = b"\x00\x00\xa0\xe1"
    # Thumb NOP: mov r8, r8 (0x46C0)
    THUMB_NOP = b"\xc0\x46"
    # PowerPC NOP: nop (0x60000000)
    PPC_NOP = b"\x60\x00\x00\x00"
    # MIPS NOP: sll $0, $0, 0 (0x00000000)
    MIPS_NOP = b"\x00\x00\x00\x00"

    @classmethod
    def scan_nds_ap(cls, arm9_code: bytes) -> List[APMatch]:
        """
        Scan Nintendo DS ARM9 binary for common AP check routines.
        """
        matches: List[APMatch] = []
        n = len(arm9_code)

        # 1. Search for Cartridge Command Register references
        for pat in cls.NDS_ROMCTRL_PATTERNS:
            pos = 0
            while True:
                idx = arm9_code.find(pat, pos)
                if idx == -1:
                    break
                pos = idx + 4
                # Scan nearby code (-64 to +64) for conditional branch
                start_window = max(0, idx - 64)
                end_window = min(n, idx + 64)
                # Detect ARM conditional branches (0x0A, 0x1A, etc.)
                for c_off in range(start_window, end_window, 4):
                    if c_off + 4 <= n:
                        instr = struct.unpack("<I", arm9_code[c_off:c_off+4])[0]
                        cond = (instr >> 28) & 0xF
                        # If conditional branch (NE: 0x1, EQ: 0x0)
                        if cond in (0x0, 0x1) and ((instr >> 24) & 0xF) == 0xA:
                            orig = arm9_code[c_off:c_off+4]
                            matches.append(
                                APMatch(
                                    offset=c_off,
                                    vector_type=APVectorType.CARTRIDGE_CHECK,
                                    arch="arm",
                                    description="NDS Cartridge Check Conditional Branch",
                                    original_bytes=orig,
                                    patch_bytes=cls.ARM_NOP,
                                )
                            )
                            break

        # 2. Search for Checksum accumulator loops (e.g., eor / add in loop followed by cmp)
        # ARM pattern: cmp rX, rY; bne loc
        for i in range(0, n - 8, 4):
            instr1 = struct.unpack("<I", arm9_code[i:i+4])[0]
            instr2 = struct.unpack("<I", arm9_code[i+4:i+8])[0]
            # cmp instruction (opcode 0x3500000 or similar: (instr & 0x0DE00000) == 0x01500000)
            if (instr1 & 0x0DE00000) == 0x01500000:
                # instr2 is BNE (cond 0x1, opcode 0xA)
                cond2 = (instr2 >> 28) & 0xF
                op2 = (instr2 >> 24) & 0xE
                if cond2 == 0x1 and op2 == 0xA:
                    # Potential AP failure branch
                    orig = arm9_code[i+4:i+8]
                    matches.append(
                        APMatch(
                            offset=i+4,
                            vector_type=APVectorType.CHECKSUM_LOOP,
                            arch="arm",
                            description="ARM Checksum Verification Failure Branch",
                            original_bytes=orig,
                            patch_bytes=cls.ARM_NOP,
                        )
                    )

        # Deduplicate matches by offset
        unique_matches: Dict[int, APMatch] = {m.offset: m for m in matches}
        return list(unique_matches.values())

    @classmethod
    def scan_ppc_integrity(cls, data: bytes) -> List[APMatch]:
        """
        Scan PowerPC code for checksum loops (cmpw / cmpwi followed by bne/beq).
        """
        matches: List[APMatch] = []
        n = len(data)

        for i in range(0, n - 8, 4):
            w1 = struct.unpack(">I", data[i:i+4])[0]
            w2 = struct.unpack(">I", data[i+4:i+8])[0]

            # PPC cmpwi / cmpw: opcode 10 (0x28) or opcode 31 xo 0 (0x7C000000)
            is_cmp = (w1 >> 26) in (10, 11) or ((w1 >> 26) == 31 and ((w1 >> 1) & 0x3FF) == 0)
            # PPC bc / bne: opcode 16 (0x40000000)
            is_cond_branch = (w2 >> 26) == 16
            if is_cmp and is_cond_branch:
                matches.append(
                    APMatch(
                        offset=i+4,
                        vector_type=APVectorType.INTEGRITY_CMP,
                        arch="ppc",
                        description="PowerPC Integrity Comparison Branch",
                        original_bytes=data[i+4:i+8],
                        patch_bytes=cls.PPC_NOP,
                    )
                )

        return matches[:10]  # Cap candidates to avoid false positives

    @classmethod
    def patch_all(cls, data: bytearray, matches: List[APMatch]) -> APBypassReport:
        """
        Apply surgical NOP / branch patches for all identified AP vectors.
        """
        applied = 0
        for m in matches:
            if m.offset + len(m.patch_bytes) <= len(data):
                data[m.offset : m.offset + len(m.patch_bytes)] = m.patch_bytes
                applied += 1

        return APBypassReport(
            total_scanned=len(data),
            matches=matches,
            patched_count=applied,
        )
