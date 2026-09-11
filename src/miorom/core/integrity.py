"""
miorom.core.integrity
~~~~~~~~~~~~~~~~~~~~~
Universal ROM Integrity and Header Checksum Auto-Fixer.
Detects console platforms (NDS, GBA, GB/GBC, N64, Mega Drive, SNES) and provides
automated verification and header checksum repair for modified and translated ROMs.
"""

from miorom.result import MioRomResult
import struct
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.platforms.gba.rom import GBARom
from miorom.platforms.gb.rom import GBRom
from miorom.platforms.n64.checksum import (
    calculate_n64_checksum,
    fix_n64_checksum,
    verify_n64_checksum,
)
from miorom.platforms.md.rom import (
    calculate_md_checksum,
    deinterleave_smd,
    fix_md_checksum,
    is_smd,
    verify_md_checksum,
)
from miorom.platforms.snes.rom import SNESRom
from miorom.rom.handlers.nds import calculate_nds_crc16


@dataclass
class IntegrityReport(MioRomResult):
    """Detailed summary of ROM integrity verification and repair."""
    platform: str
    is_valid: bool
    expected_checksums: Dict[str, Any] = field(default_factory=dict)
    actual_checksums: Dict[str, Any] = field(default_factory=dict)
    repaired: bool = False
    details: str = ""


class RomIntegrityManager:
    """
    Universal multi-platform ROM integrity auditor and checksum auto-fixer.
    """

    SUPPORTED_PLATFORMS = ("NDS", "GBA", "GB", "N64", "MD", "SNES")

    @classmethod
    def auto_detect_platform(cls, data: bytes) -> Optional[str]:
        """Identifies console platform from binary header signatures."""
        if len(data) < 0xC0:
            return None

        # Nintendo 64 (.z64, .v64, .n64)
        if len(data) >= 4 and data[:4] in (
            b"\x80\x37\x12\x40",
            b"\x37\x80\x40\x12",
            b"\x40\x12\x37\x80",
        ):
            return "N64"

        # Sega Mega Drive / Genesis
        if len(data) >= 0x200:
            if data[0x100:0x104] == b"SEGA":
                return "MD"
            if len(data) >= 512 and is_smd(data):
                return "MD"

        # Nintendo DS (.nds)
        if len(data) >= 0x200:
            # Check unit_code at 0x12 and game_code at 0x0C
            if data[0x12] in (0, 2, 3) and data[0x0C:0x10].isalnum():
                return "NDS"

        # Game Boy Advance (.gba)
        if len(data) >= 0xC0:
            # Check logo prefix or complement check
            if data[0x04:0x20] == GBARom.NINTENDO_LOGO[:0x1C]:
                return "GBA"
            if data[0xB2:0xB4] == b"\x96\x00" and data[0xAC:0xB0].isalnum():
                return "GBA"

        # Game Boy and Game Boy Color (.gb, .gbc)
        if len(data) >= 0x150:
            if data[0x104:0x120] == GBRom.NINTENDO_LOGO[:0x1C]:
                return "GB"
            try:
                gb = GBRom(data[:0x150])
                if gb.is_header_checksum_valid():
                    return "GB"
            except Exception:
                pass

        # Super Nintendo (.sfc, .smc)
        if len(data) >= 0x8000:
            try:
                snes = SNESRom(data)
                if snes._score_header(snes.header_offset) >= 15:
                    return "SNES"
            except Exception:
                pass

        return None

    @classmethod
    def verify(cls, data: bytes, platform: Optional[str] = None) -> IntegrityReport:
        """
        Verifies ROM header and global checksums for the given or auto-detected platform.
        """
        plat = (platform or cls.auto_detect_platform(data) or "UNKNOWN").upper()

        if plat == "NDS":
            return cls._verify_nds(data)
        elif plat == "GBA":
            return cls._verify_gba(data)
        elif plat == "GB":
            return cls._verify_gb(data)
        elif plat == "N64":
            return cls._verify_n64(data)
        elif plat == "MD":
            return cls._verify_md(data)
        elif plat == "SNES":
            return cls._verify_snes(data)
        else:
            return IntegrityReport(
                platform="UNKNOWN",
                is_valid=False,
                details="Could not auto-detect ROM platform or platform unsupported.",
            )

    @classmethod
    def fix(cls, data: bytes, platform: Optional[str] = None) -> Tuple[bytes, IntegrityReport]:
        """
        Recalculates and patches ROM header checksums, returning the fixed byte buffer
        along with an IntegrityReport.
        """
        plat = (platform or cls.auto_detect_platform(data) or "UNKNOWN").upper()

        if plat == "NDS":
            return cls._fix_nds(data)
        elif plat == "GBA":
            return cls._fix_gba(data)
        elif plat == "GB":
            return cls._fix_gb(data)
        elif plat == "N64":
            return cls._fix_n64(data)
        elif plat == "MD":
            return cls._fix_md(data)
        elif plat == "SNES":
            return cls._fix_snes(data)
        else:
            return data, IntegrityReport(
                platform="UNKNOWN",
                is_valid=False,
                repaired=False,
                details="Cannot repair checksums: unknown or unsupported platform.",
            )

    # --- Platform-specific implementations ---

    @classmethod
    def _verify_nds(cls, data: bytes) -> IntegrityReport:
        if len(data) < 0x160:
            return IntegrityReport("NDS", False, details="Data too small for NDS header")
        expected_crc = struct.unpack_from("<H", data, 0x15E)[0]
        actual_crc = calculate_nds_crc16(data[:0x15E])
        valid = (expected_crc == actual_crc)
        return IntegrityReport(
            platform="NDS",
            is_valid=valid,
            expected_checksums={"header_crc16": f"0x{expected_crc:04X}"},
            actual_checksums={"header_crc16": f"0x{actual_crc:04X}"},
            details="Valid NDS header CRC16" if valid else "Corrupt or modified NDS header CRC16",
        )

    @classmethod
    def _fix_nds(cls, data: bytes) -> Tuple[bytes, IntegrityReport]:
        ba = bytearray(data)
        if len(ba) < 0x160:
            return bytes(ba), IntegrityReport("NDS", False, details="Data too small")
        actual_crc = calculate_nds_crc16(bytes(ba[:0x15E]))
        struct.pack_into("<H", ba, 0x15E, actual_crc)
        return bytes(ba), IntegrityReport(
            platform="NDS",
            is_valid=True,
            expected_checksums={"header_crc16": f"0x{actual_crc:04X}"},
            actual_checksums={"header_crc16": f"0x{actual_crc:04X}"},
            repaired=True,
            details=f"Patched NDS header CRC16 to 0x{actual_crc:04X}",
        )

    @classmethod
    def _verify_gba(cls, data: bytes) -> IntegrityReport:
        rom = GBARom(data)
        valid = rom.is_header_checksum_valid()
        return IntegrityReport(
            platform="GBA",
            is_valid=valid,
            expected_checksums={"header_complement": f"0x{rom.header_checksum:02X}"},
            actual_checksums={"header_complement": f"0x{rom.calculate_header_checksum():02X}"},
            details="Valid GBA header complement checksum" if valid else "Invalid GBA header complement checksum",
        )

    @classmethod
    def _fix_gba(cls, data: bytes) -> Tuple[bytes, IntegrityReport]:
        rom = GBARom(data)
        rom.fix_header_checksum()
        chk = rom.header_checksum
        return rom.to_bytes(), IntegrityReport(
            platform="GBA",
            is_valid=True,
            expected_checksums={"header_complement": f"0x{chk:02X}"},
            actual_checksums={"header_complement": f"0x{chk:02X}"},
            repaired=True,
            details=f"Patched GBA header complement to 0x{chk:02X}",
        )

    @classmethod
    def _verify_gb(cls, data: bytes) -> IntegrityReport:
        rom = GBRom(data)
        h_valid = rom.is_header_checksum_valid()
        g_valid = rom.is_global_checksum_valid()
        return IntegrityReport(
            platform="GB",
            is_valid=(h_valid and g_valid),
            expected_checksums={
                "header_checksum": f"0x{rom.header_checksum:02X}",
                "global_checksum": f"0x{rom.global_checksum:04X}",
            },
            actual_checksums={
                "header_checksum": f"0x{rom.calculate_header_checksum():02X}",
                "global_checksum": f"0x{rom.calculate_global_checksum():04X}",
            },
            details=f"Header: {'OK' if h_valid else 'FAIL'}, Global: {'OK' if g_valid else 'FAIL'}",
        )

    @classmethod
    def _fix_gb(cls, data: bytes) -> Tuple[bytes, IntegrityReport]:
        rom = GBRom(data)
        rom.fix_header_checksum()
        rom.fix_global_checksum()
        return rom.to_bytes(), IntegrityReport(
            platform="GB",
            is_valid=True,
            expected_checksums={
                "header_checksum": f"0x{rom.header_checksum:02X}",
                "global_checksum": f"0x{rom.global_checksum:04X}",
            },
            actual_checksums={
                "header_checksum": f"0x{rom.header_checksum:02X}",
                "global_checksum": f"0x{rom.global_checksum:04X}",
            },
            repaired=True,
            details="Patched GB header and global checksums",
        )

    @classmethod
    def _verify_n64(cls, data: bytes) -> IntegrityReport:
        if len(data) < 0x1000:
            return IntegrityReport("N64", False, details="Data too small for N64 bootcode")
        valid = verify_n64_checksum(data)
        exp1, exp2 = struct.unpack_from(">II", data, 0x10)
        act1, act2 = calculate_n64_checksum(data)
        return IntegrityReport(
            platform="N64",
            is_valid=valid,
            expected_checksums={"crc1": f"0x{exp1:08X}", "crc2": f"0x{exp2:08X}"},
            actual_checksums={"crc1": f"0x{act1:08X}", "crc2": f"0x{act2:08X}"},
            details="Valid N64 IPL3 boot checksum" if valid else "Invalid N64 IPL3 boot checksum",
        )

    @classmethod
    def _fix_n64(cls, data: bytes) -> Tuple[bytes, IntegrityReport]:
        fixed_bytes = fix_n64_checksum(data)
        c1, c2 = struct.unpack_from(">II", fixed_bytes, 0x10)
        return fixed_bytes, IntegrityReport(
            platform="N64",
            is_valid=True,
            expected_checksums={"crc1": f"0x{c1:08X}", "crc2": f"0x{c2:08X}"},
            actual_checksums={"crc1": f"0x{c1:08X}", "crc2": f"0x{c2:08X}"},
            repaired=True,
            details=f"Patched N64 CRC1=0x{c1:08X}, CRC2=0x{c2:08X}",
        )

    @classmethod
    def _verify_md(cls, data: bytes) -> IntegrityReport:
        raw = deinterleave_smd(data) if is_smd(data) else data
        valid = verify_md_checksum(raw)
        exp = struct.unpack_from(">H", raw, 0x018E)[0] if len(raw) >= 0x0190 else 0
        act = calculate_md_checksum(raw)
        return IntegrityReport(
            platform="MD",
            is_valid=valid,
            expected_checksums={"checksum": f"0x{exp:04X}"},
            actual_checksums={"checksum": f"0x{act:04X}"},
            details="Valid Mega Drive checksum" if valid else "Invalid Mega Drive checksum",
        )

    @classmethod
    def _fix_md(cls, data: bytes) -> Tuple[bytes, IntegrityReport]:
        was_smd = is_smd(data)
        raw = deinterleave_smd(data) if was_smd else data
        fixed_raw = fix_md_checksum(raw)
        chk = calculate_md_checksum(fixed_raw)
        return fixed_raw, IntegrityReport(
            platform="MD",
            is_valid=True,
            expected_checksums={"checksum": f"0x{chk:04X}"},
            actual_checksums={"checksum": f"0x{chk:04X}"},
            repaired=True,
            details=f"Patched Mega Drive checksum to 0x{chk:04X}",
        )

    @classmethod
    def _verify_snes(cls, data: bytes) -> IntegrityReport:
        rom = SNESRom(data)
        valid = rom.is_checksum_valid()
        return IntegrityReport(
            platform="SNES",
            is_valid=valid,
            expected_checksums={"checksum": f"0x{rom.rom_checksum:04X}", "complement": f"0x{rom.checksum_complement:04X}"},
            actual_checksums={"checksum": f"0x{rom.calculate_checksum():04X}", "complement": f"0x{rom.calculate_checksum() ^ 0xFFFF:04X}"},
            details="Valid SNES checksum & complement" if valid else "Invalid SNES checksum & complement",
        )

    @classmethod
    def _fix_snes(cls, data: bytes) -> Tuple[bytes, IntegrityReport]:
        rom = SNESRom(data)
        rom.fix_checksum()
        return rom.to_bytes(), IntegrityReport(
            platform="SNES",
            is_valid=True,
            expected_checksums={"checksum": f"0x{rom.rom_checksum:04X}", "complement": f"0x{rom.checksum_complement:04X}"},
            actual_checksums={"checksum": f"0x{rom.rom_checksum:04X}", "complement": f"0x{rom.checksum_complement:04X}"},
            repaired=True,
            details=f"Patched SNES checksum to 0x{rom.rom_checksum:04X}",
        )
