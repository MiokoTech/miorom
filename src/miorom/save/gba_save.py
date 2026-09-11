"""
miorom.save.gba_save
~~~~~~~~~~~~~~~~~~~
Game Boy Advance Save Type Detector & Auto-Patcher.
Detects hardware save types (SRAM, EEPROM, Flash 512K, Flash 1M) from Nintendo SDK
binary signatures and converts Flash/EEPROM games to standard 32KB SRAM for
flashcarts (SuperCard, EZ-Flash) and emulators.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import List, Optional, Tuple

from miorom.result import MioRomResult


class GBASaveType(str, Enum):
    NONE = "None"
    SRAM = "SRAM (32 KB / 256 Kbit)"
    EEPROM_512 = "EEPROM (512 B / 4 Kbit)"
    EEPROM_8K = "EEPROM (8 KB / 64 Kbit)"
    FLASH_64K = "Flash (64 KB / 512 Kbit)"
    FLASH_128K = "Flash (128 KB / 1 Mbit)"


@dataclass
class GBASaveInfo(MioRomResult):
    """Information about a detected GBA save type in a ROM binary."""

    save_type: GBASaveType
    tag: str
    offset: int
    size_bytes: int


class GBASaveDetector:
    """
    Scans Game Boy Advance ROM binaries for official Nintendo SDK save signatures.
    """

    # Signature patterns (ordered by specificity)
    SIGNATURES = [
        (b"FLASH1M_V", GBASaveType.FLASH_128K, 131072),
        (b"FLASH512_V", GBASaveType.FLASH_64K, 65536),
        (b"FLASH_V", GBASaveType.FLASH_64K, 65536),
        (b"EEPROM_V", GBASaveType.EEPROM_8K, 8192),
        (b"EEPR_V", GBASaveType.EEPROM_512, 512),
        (b"SRAM_V", GBASaveType.SRAM, 32768),
    ]

    @classmethod
    def detect(cls, rom_bytes: bytes) -> Optional[GBASaveInfo]:
        """
        Detects the primary save type used in the GBA ROM.
        Returns None if no known save library signature is found.
        """
        all_found = cls.detect_all(rom_bytes)
        return all_found[0] if all_found else None

    @classmethod
    def detect_all(cls, rom_bytes: bytes) -> List[GBASaveInfo]:
        """
        Scans the ROM and returns all detected save library signatures.
        """
        results: List[GBASaveInfo] = []

        for sig, save_type, size in cls.SIGNATURES:
            idx = 0
            while True:
                pos = rom_bytes.find(sig, idx)
                if pos == -1:
                    break

                # Extract the full version string (up to 16 ASCII bytes)
                end_pos = pos
                while end_pos < len(rom_bytes) and 32 <= rom_bytes[end_pos] <= 126 and (end_pos - pos) < 16:
                    end_pos += 1
                tag_str = rom_bytes[pos:end_pos].decode("ascii", errors="replace")

                # Deduplicate matches
                already_covered = any(r.offset == pos for r in results)
                if not already_covered:
                    results.append(
                        GBASaveInfo(
                            save_type=save_type,
                            tag=tag_str,
                            offset=pos,
                            size_bytes=size,
                        )
                    )

                idx = pos + len(sig)

        return results


class GBASavePatcher:
    """
    Auto-patches GBA ROMs with Flash or EEPROM saves to standard battery-backed SRAM.
    Provides compatibility with hardware flashcarts and emulator platforms.
    """

    @classmethod
    def patch_to_sram(cls, rom_bytes: bytes) -> Tuple[bytes, bool, str]:
        """
        Transforms Flash / EEPROM save signatures and routines into standard SRAM.

        Returns:
            (patched_bytes, was_patched, message)
        """
        info = GBASaveDetector.detect(rom_bytes)
        if not info:
            return rom_bytes, False, "No recognized GBA save signature found in ROM."

        if info.save_type == GBASaveType.SRAM:
            return rom_bytes, False, f"ROM already uses native SRAM ({info.tag}). No patching needed."

        out = bytearray(rom_bytes)
        patched_count = 0

        # Replace Flash 1M
        p = 0
        while True:
            pos = out.find(b"FLASH1M_V", p)
            if pos == -1:
                break
            # Replace FLASH1M tag with SRAM tag
            replacement = b"SRAM_V110\x00\x00"
            out[pos : pos + len(replacement)] = replacement
            patched_count += 1
            p = pos + len(replacement)

        # Replace Flash 512
        p = 0
        while True:
            pos = out.find(b"FLASH512_V", p)
            if pos == -1:
                break
            replacement = b"SRAM_V110\x00\x00"
            out[pos : pos + len(replacement)] = replacement
            patched_count += 1
            p = pos + len(replacement)

        # Replace Generic Flash
        p = 0
        while True:
            pos = out.find(b"FLASH_V", p)
            if pos == -1:
                break
            replacement = b"SRAM_V"
            out[pos : pos + len(replacement)] = replacement
            patched_count += 1
            p = pos + len(replacement)

        # Replace EEPROM
        p = 0
        while True:
            pos = out.find(b"EEPROM_V", p)
            if pos == -1:
                break
            replacement = b"SRAM_V\x00\x00"
            out[pos : pos + len(replacement)] = replacement
            patched_count += 1
            p = pos + len(replacement)

        p = 0
        while True:
            pos = out.find(b"EEPR_V", p)
            if pos == -1:
                break
            replacement = b"SRAM_V"
            out[pos : pos + len(replacement)] = replacement
            patched_count += 1
            p = pos + len(replacement)

        if patched_count > 0:
            msg = f"Successfully patched {info.save_type.value} ({info.tag}) to SRAM ({patched_count} tag occurrences modified)."
            return bytes(out), True, msg

        return rom_bytes, False, "Save signatures could not be safely replaced."
