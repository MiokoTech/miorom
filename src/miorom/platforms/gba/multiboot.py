"""
miorom.platforms.gba.multiboot
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Game Boy Advance Multiboot (.mb) payload generator and validator.

Multiboot programs are 256KB EWRAM executables transferred over the GBA link cable
or GameCube-GBA Joybus cable to slave consoles without a cartridge inserted.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, Optional

from miorom.errors import ParseError
from miorom.platforms.gba.rom import GBARom
from miorom.result import MioRomResult


MULTIBOOT_HEADER_SIZE = 0xE0
EWRAM_BASE = 0x02000000


class GBAMultiboot(MioRomResult):
    """
    Builder, validator, and unpacker for GBA Multiboot (.mb) executables.
    """

    @classmethod
    def calculate_header_checksum(cls, header: bytes) -> int:
        """Calculates GBA complement checksum over header bytes 0xA0..0xBC."""
        chk = 0
        for i in range(0xA0, 0xBD):
            chk = (chk - header[i]) & 0xFF
        return (chk - 0x19) & 0xFF

    @classmethod
    def create_payload(
        cls,
        code_bytes: bytes,
        title: str = "MULTIBOOT",
        game_code: str = "MB01",
        maker_code: str = "01",
    ) -> bytes:
        """
        Synthesizes a compliant GBA multiboot binary with valid header, Nintendo logo,
        and complement checksum.
        """
        if len(code_bytes) > (256 * 1024 - MULTIBOOT_HEADER_SIZE):
            raise ValueError("Payload exceeds 256KB GBA EWRAM limit.")

        buf = bytearray(MULTIBOOT_HEADER_SIZE + len(code_bytes))

        # Branch to entrypoint 0x020000E0 (B 0xE0)
        struct.pack_into("<I", buf, 0, 0xEA000036)

        # Insert Nintendo logo
        logo = GBARom.NINTENDO_LOGO
        buf[4 : 4 + len(logo)] = logo

        # Set game metadata
        title_bytes = title.encode("ascii", errors="replace")[:12].ljust(12, b"\x00")
        buf[0xA0:0xAC] = title_bytes

        game_code_bytes = game_code.encode("ascii", errors="replace")[:4].ljust(4, b"\x00")
        buf[0xAC:0xB0] = game_code_bytes

        maker_code_bytes = maker_code.encode("ascii", errors="replace")[:2].ljust(2, b"\x00")
        buf[0xB0:0xB2] = maker_code_bytes

        buf[0xB2] = 0x96  # Fixed GBA magic
        buf[0xB3] = 0x00  # Main unit code
        buf[0xB4] = 0x00  # Device type
        buf[0xBC] = 0x00  # Version

        # Calculate complement checksum
        buf[0xBD] = cls.calculate_header_checksum(bytes(buf))

        # Multiboot parameters
        buf[0xC0] = 0x00  # Boot mode
        buf[0xC4] = 0x01  # Slave ID

        # Copy executable code payload at 0xE0
        buf[MULTIBOOT_HEADER_SIZE:] = code_bytes

        return bytes(buf)

    @classmethod
    def parse(cls, data: bytes) -> Dict[str, Any]:
        """Parses multiboot header and validates integrity."""
        if len(data) < MULTIBOOT_HEADER_SIZE:
            raise ParseError("Data too small for GBA Multiboot header (minimum 224 bytes).")

        title = data[0xA0:0xAC].decode("ascii", errors="replace").rstrip("\x00 ")
        game_code = data[0xAC:0xB0].decode("ascii", errors="replace").rstrip("\x00 ")
        maker_code = data[0xB0:0xB2].decode("ascii", errors="replace").rstrip("\x00 ")
        expected_chk = cls.calculate_header_checksum(data)
        actual_chk = data[0xBD]
        valid_chk = expected_chk == actual_chk

        return {
            "title": title,
            "game_code": game_code,
            "maker_code": maker_code,
            "is_valid_checksum": valid_chk,
            "payload_size": len(data) - MULTIBOOT_HEADER_SIZE,
            "entry_point": EWRAM_BASE + MULTIBOOT_HEADER_SIZE,
        }

    @classmethod
    def verify(cls, data: bytes) -> bool:
        """Verifies if binary contains a valid GBA Multiboot header."""
        if len(data) < MULTIBOOT_HEADER_SIZE:
            return False
        if data[0xB2] != 0x96:
            return False
        expected_chk = cls.calculate_header_checksum(data)
        return expected_chk == data[0xBD]
