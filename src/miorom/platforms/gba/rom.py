"""
miorom.platforms.gba.rom
~~~~~~~~~~~~~~~~~~~~~~~~
Game Boy Advance (GBA) Cartridge ROM Engine.
Provides cartridge header parsing, complement checksum calculation and repair,
Nintendo logo validation, ROM capacity expansion & trimming, save-type detection
and patching, BIOS LZ77 and Sappy audio discovery, and synthetic ROM fixture generation.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.core.schema import (
    U8,
    BinaryStruct,
    FixedString,
    RawBytes,
    pack_into,
)
from miorom.errors import ParseError


class GBAHeaderStruct(BinaryStruct):
    _endian = "<"
    _reserved_0x00 = RawBytes(0xA0)
    title = FixedString(12)
    game_code = FixedString(4)
    maker_code = FixedString(2)
    _reserved_0xB2 = RawBytes(10)
    version = U8()
    header_checksum = U8()


def resolve_gba_region(game_code: str) -> str:
    """
    Resolve the regional territory from the 4th character of a GBA Game Code.
    Official Nintendo product code territory mapping:
    - 'E': USA / North America
    - 'P': Europe / PAL
    - 'J': Japan
    - 'D': Germany
    - 'F': France
    - 'I': Italy
    - 'S': Spain
    - 'U': Australia
    - 'K': Korea
    """
    clean = game_code.strip()
    if len(clean) >= 4:
        ch = clean[3].upper()
        mapping = {
            "E": "USA",
            "P": "EUR",
            "J": "JPN",
            "D": "GER",
            "F": "FRA",
            "I": "ITA",
            "S": "SPA",
            "U": "AUS",
            "K": "KOR",
        }
        return mapping.get(ch, "GLOBAL")
    return "UNKNOWN"


class GBARom:
    """
    Game Boy Advance ROM parser, header checksum validator/fixer, capacity expander,
    save-type detector, and multi-media asset scanner.
    """

    NINTENDO_LOGO = bytes([
        0x24, 0xFF, 0xAE, 0x51, 0x69, 0x9A, 0xA2, 0x21, 0x3D, 0x84, 0x82, 0x0A, 0x84, 0xE4, 0x09, 0xAD,
        0x11, 0x24, 0x8B, 0x98, 0xC0, 0x81, 0x7F, 0x21, 0xA3, 0x52, 0xBE, 0x19, 0x93, 0x09, 0xCE, 0x20,
        0x10, 0x46, 0x4A, 0x4A, 0xF8, 0x27, 0x31, 0xEC, 0x58, 0xC7, 0xE8, 0x33, 0x82, 0xE3, 0xCE, 0xBF,
        0x85, 0xF4, 0xDF, 0x94, 0xCE, 0x4B, 0x09, 0xC1, 0x94, 0x56, 0x8A, 0xC0, 0x13, 0x72, 0xA7, 0xFC,
        0x9F, 0x84, 0x4D, 0x73, 0xA3, 0xCA, 0x9A, 0x61, 0x58, 0x97, 0xA3, 0x27, 0xFC, 0x03, 0x98, 0x76,
        0x23, 0x1D, 0xC7, 0x61, 0x03, 0x04, 0xAE, 0x56, 0xBF, 0x38, 0x84, 0x00, 0x40, 0xA7, 0x0E, 0xFD,
        0xFF, 0x52, 0xFE, 0x03, 0x6F, 0x95, 0x30, 0xF1, 0x97, 0xFB, 0xC0, 0x85, 0x60, 0xD6, 0x80, 0x25,
        0xA9, 0x63, 0xBE, 0x03, 0x01, 0x4E, 0x38, 0xE2, 0xF9, 0xA2, 0x34, 0xFF, 0xBB, 0x3E, 0x03, 0x44,
        0x78, 0x00, 0x90, 0xCB, 0x88, 0x11, 0x3A, 0x94, 0x65, 0xC0, 0x7C, 0x63, 0x87, 0xF0, 0x3C, 0xAF,
        0xD6, 0x25, 0xE4, 0x8B, 0x38, 0x0A, 0xAC, 0x72, 0x21, 0xD4, 0xF8, 0x07,
    ])

    def __init__(self, data: bytes):
        if len(data) < 0xC0:
            raise ParseError("Data too small to contain a valid GBA ROM header.")
        self.data = bytearray(data)
        self._header = GBAHeaderStruct.from_bytes(self.data, offset=0)
        self._original_logo_and_entry = bytes(self.data[0:0xA0])

    @classmethod
    def from_file(cls, path: Union[str, os.PathLike]) -> "GBARom":
        with open(path, "rb") as f:
            return cls(f.read())

    @property
    def title(self) -> str:
        return self._header.title

    @title.setter
    def title(self, val: str):
        self._header.title = val
        self.data[0xA0:0xBE] = self._header.to_bytes()[0xA0:]

    @property
    def game_code(self) -> str:
        return self._header.game_code

    @game_code.setter
    def game_code(self, val: str):
        self._header.game_code = val
        self.data[0xA0:0xBE] = self._header.to_bytes()[0xA0:]

    @property
    def maker_code(self) -> str:
        return self._header.maker_code

    @property
    def version(self) -> int:
        return self._header.version

    @property
    def header_checksum(self) -> int:
        return self._header.header_checksum

    @property
    def region(self) -> str:
        """Distribution region resolved from the 4th character of the Game Code."""
        return resolve_gba_region(self.game_code)

    @property
    def entry_point(self) -> int:
        """
        Calculates the ARM execution entry point address from the 32-bit branch opcode at 0x00.
        GBA cartridge ROM space maps to 0x08000000..0x09FFFFFF.
        """
        if len(self.data) >= 4 and self.data[3] == 0xEA:
            # 24-bit relative word offset
            imm24 = self.data[0] | (self.data[1] << 8) | (self.data[2] << 16)
            if imm24 & 0x800000:
                imm24 -= 0x1000000
            return 0x08000000 + 8 + (imm24 << 2)
        return 0x08000000

    def calculate_header_checksum(self) -> int:
        """
        Calculates the GBA header complement check:
        SUM = 0
        FOR i = 0xA0 to 0xBC: SUM = SUM - [i]
        CHECKSUM = (SUM - 0x19) & 0xFF
        """
        chk = 0
        for b in self.data[0xA0:0xBD]:
            chk = (chk - b) & 0xFF
        return (chk - 0x19) & 0xFF

    def is_header_checksum_valid(self) -> bool:
        return self.header_checksum == self.calculate_header_checksum()

    def fix_header_checksum(self):
        """Recalculates and updates the complement check byte at 0xBD."""
        self._header.header_checksum = self.calculate_header_checksum()
        self.data[0xA0:0xBE] = self._header.to_bytes()[0xA0:]

    def fix_checksum(self):
        """Alias for fix_header_checksum."""
        self.fix_header_checksum()

    def validate_checksum(self) -> bool:
        """Alias for is_header_checksum_valid."""
        return self.is_header_checksum_valid()

    def is_logo_valid(self) -> bool:
        return self.data[0x04:0xA0] == self.NINTENDO_LOGO

    def fix_logo(self) -> None:
        """Restores the official 156-byte Nintendo logo into the ROM header (0x04..0x9F)."""
        self.data[0x04:0xA0] = self.NINTENDO_LOGO

    @property
    def has_rtc(self) -> bool:
        """Checks whether ROM contains a Real-Time Clock (RTC) library signature."""
        return b"SIIRTC_V" in bytes(self.data)

    def detect_save_type(self) -> str:
        """
        Inspects ROM strings for standard GBA backup library signatures:
        EEPROM (4K/64K), SRAM (256K), FLASH (512K/1M), and Real-Time Clock (RTC).
        """
        rom_bytes = bytes(self.data)
        rtc_suffix = " + RTC" if b"SIIRTC_V" in rom_bytes else ""
        if b"EEPROM_V" in rom_bytes:
            return f"EEPROM{rtc_suffix}"
        if b"SRAM_V" in rom_bytes or b"SRAM_F_V" in rom_bytes:
            return f"SRAM (256Kbit / 32KB){rtc_suffix}"
        if b"FLASH1M_V" in rom_bytes:
            return f"FLASH (1Mbit / 128KB){rtc_suffix}"
        if b"FLASH_V" in rom_bytes or b"FLASH512_V" in rom_bytes:
            return f"FLASH (512Kbit / 64KB){rtc_suffix}"
        if rtc_suffix:
            return f"UNKNOWN{rtc_suffix}"
        return "UNKNOWN / NONE"

    def patch_save_to_sram(self) -> bool:
        """
        Converts Flash/EEPROM save library signatures to standard 32KB SRAM
        for flashcarts and emulators. Returns True if modified.
        """
        from miorom.save.gba_save import GBASavePatcher

        patched_data, modified, _ = GBASavePatcher.patch_to_sram(bytes(self.data))
        if modified:
            self.data = bytearray(patched_data)
            return True
        return False

    def expand(self, target_size_mb: int) -> None:
        """
        Expands the ROM capacity to standard cartridge boundaries (1, 2, 4, 8, 16, 32, or 64 MB).
        Unused space is padded with 0xFF (unprogrammed flash memory).
        """
        if target_size_mb not in (1, 2, 4, 8, 16, 32, 64):
            raise ValueError(
                f"Invalid GBA ROM target size {target_size_mb} MB. Must be 1, 2, 4, 8, 16, 32, or 64 MB."
            )
        target_bytes = target_size_mb * 1024 * 1024
        if target_bytes < len(self.data):
            raise ValueError(
                f"Cannot shrink ROM from {len(self.data)} bytes to {target_bytes} bytes."
            )
        if target_bytes > len(self.data):
            pad_len = target_bytes - len(self.data)
            self.data.extend(b"\xFF" * pad_len)

    def trim(self, min_size: int = 0x20000) -> None:
        """
        Trims trailing 0xFF and 0x00 padding back to the smallest valid power-of-2 size.
        Maintains at least min_size bytes (default 128 KB).
        """
        last_non_pad = len(self.data)
        while last_non_pad > min_size:
            b = self.data[last_non_pad - 1]
            if b != 0xFF and b != 0x00:
                break
            last_non_pad -= 1

        size = min_size
        while size < last_non_pad and size < 64 * 1024 * 1024:
            size *= 2

        if size < len(self.data):
            self.data = self.data[:size]

    def find_lz10_streams(self, min_size: int = 16) -> List[Tuple[int, int]]:
        """
        Scans ROM for candidate Nintendo LZ77 Type 0x10 compressed data streams.
        Returns a list of (byte_offset, decompressed_size).
        """
        from miorom.compression.lz10 import LZ10

        results: List[Tuple[int, int]] = []
        data_len = len(self.data)
        for off in range(0xC0, data_len - 8, 4):
            if self.data[off] == 0x10:
                decomp_size = (
                    self.data[off + 1]
                    | (self.data[off + 2] << 8)
                    | (self.data[off + 3] << 16)
                )
                if min_size <= decomp_size <= 0x200000:
                    try:
                        decomp = LZ10.decompress(
                            bytes(self.data[off : min(data_len, off + decomp_size * 2 + 1024)])
                        )
                        if len(decomp) == decomp_size:
                            results.append((off, decomp_size))
                    except Exception:
                        pass
        return results

    def find_sappy_songs(self, min_consecutive: int = 3) -> List[int]:
        """
        Scans ROM for candidate Nintendo Sappy (Music Player 2000) song tables.
        Returns a list of table byte offsets.
        """
        from miorom.audio.sappy import SappyScanner

        return SappyScanner.scan_song_tables(
            bytes(self.data), min_consecutive_songs=min_consecutive
        )

    def ptr_to_offset(self, ptr: int) -> Optional[int]:
        """
        Converts a 32-bit GBA memory pointer (0x08xxxxxx, 0x09xxxxxx, etc.)
        to a ROM file byte offset. Returns None if pointer is outside ROM bounds.
        """
        base_byte = (ptr >> 24) & 0xFF
        if base_byte in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D):
            off = ptr & 0x01FFFFFF
            if off < len(self.data):
                return off
        return None

    def offset_to_ptr(self, offset: int, waitstate: int = 0) -> int:
        """
        Converts a ROM byte offset to a 32-bit GBA memory pointer.
        waitstate 0 = 0x08000000, 1 = 0x0A000000, 2 = 0x0C000000.
        """
        bases = {0: 0x08000000, 1: 0x0A000000, 2: 0x0C000000}
        base = bases.get(waitstate, 0x08000000)
        return base | (offset & 0x01FFFFFF)

    def find_pointers(self, target_offset: int, aligned: bool = True) -> List[int]:
        """
        Scans ROM for 32-bit little-endian pointers pointing to target_offset.
        Matches pointers referencing any standard GBA ROM waitstate space.
        """
        results: List[int] = []
        target_masked = target_offset & 0x01FFFFFF
        step = 4 if aligned else 1
        data_len = len(self.data)
        for off in range(0, data_len - 3, step):
            val = (
                self.data[off]
                | (self.data[off + 1] << 8)
                | (self.data[off + 2] << 16)
                | (self.data[off + 3] << 24)
            )
            base_byte = (val >> 24) & 0xFF
            if base_byte in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D):
                if (val & 0x01FFFFFF) == target_masked:
                    results.append(off)
        return results

    def relink_pointers(
        self, old_offset: int, new_offset: int, aligned: bool = True
    ) -> int:
        """
        Finds all 32-bit pointers pointing to old_offset and updates them to new_offset,
        preserving their original memory region/waitstate base.
        Returns the number of relinked pointers.
        """
        count = 0
        old_masked = old_offset & 0x01FFFFFF
        new_masked = new_offset & 0x01FFFFFF
        step = 4 if aligned else 1
        data_len = len(self.data)
        for off in range(0, data_len - 3, step):
            val = (
                self.data[off]
                | (self.data[off + 1] << 8)
                | (self.data[off + 2] << 16)
                | (self.data[off + 3] << 24)
            )
            base_byte = (val >> 24) & 0xFF
            if base_byte in (0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D):
                if (val & 0x01FFFFFF) == old_masked:
                    new_val = (base_byte << 24) | new_masked
                    self.data[off : off + 4] = new_val.to_bytes(4, "little")
                    count += 1
        return count

    def scan_swi_calls(
        self,
        thumb_mode: bool = True,
        start_offset: int = 0xC0,
        end_offset: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Scans ROM executable code for GBA BIOS software interrupt (SWI) calls
        (e.g., LZ77UnComp, CpuSet, ArcTan, SoundBias).
        """
        from miorom.platforms.gba.swi import GBASwiResolver

        end = end_offset if end_offset is not None else len(self.data)
        code_slice = bytes(self.data[start_offset:end])
        base_addr = self.offset_to_ptr(start_offset)
        return GBASwiResolver.scan_swi_calls(
            code_slice, thumb_mode=thumb_mode, base_addr=base_addr
        )

    def to_bytes(self) -> bytes:
        return bytes(self.data)

    def save(
        self,
        path: Union[str, os.PathLike],
        fix_checksum: bool = True,
    ) -> None:
        """Save the GBA ROM image to a file."""
        if fix_checksum:
            self.fix_header_checksum()
        with open(path, "wb") as f:
            f.write(self.data)


def fix_gba_checksum(data: bytes) -> bytes:
    """Helper to fix the header complement check byte of a GBA ROM."""
    gba = GBARom(data)
    gba.fix_header_checksum()
    return gba.to_bytes()


def create_synthetic_gba_rom(
    title: str = "TESTGAME",
    game_code: str = "AGBE",
    maker_code: str = "01",
    version: int = 0,
    size: int = 0x40000,
    save_type: str = "SRAM",
    with_lz10: bool = False,
    with_sappy: bool = False,
    with_rtc: bool = False,
) -> bytes:
    """
    Synthesize a valid Game Boy Advance ROM binary for testing.
    Includes ARM branch, Nintendo logo, title, game code, maker code,
    fixed 0x96 value, valid complement checksum, and optional components.
    """
    rom = bytearray(b"\xFF" * max(size, 0x100))

    # 1. ARM Branch at 0x00: b 0x080000C0
    rom[0:4] = b"\x2E\x00\x00\xEA"

    # 2. Nintendo Logo at 0x04..0x9F (156 bytes)
    rom[0x04:0xA0] = GBARom.NINTENDO_LOGO

    # 3. Game Title (12 bytes, uppercase ASCII)
    norm_title = (
        title[:12].upper().encode("ascii", errors="replace").ljust(12, b"\x00")
    )
    rom[0xA0:0xAC] = norm_title

    # 4. Game Code (4 bytes)
    norm_code = (
        game_code[:4].upper().encode("ascii", errors="replace").ljust(4, b"\x00")
    )
    rom[0xAC:0xB0] = norm_code

    # 5. Maker Code (2 bytes)
    norm_maker = (
        maker_code[:2].upper().encode("ascii", errors="replace").ljust(2, b"\x00")
    )
    rom[0xB0:0xB2] = norm_maker

    # 6. Fixed 0x96 byte
    rom[0xB2] = 0x96

    # 7. Main unit code (0x00) & Device type (0x00) & Reserved (0x00)
    rom[0xB3:0xBC] = b"\x00" * 9

    # 8. Version
    rom[0xBC] = version & 0xFF

    # 9. Header Checksum calculation
    chk = 0
    for b in rom[0xA0:0xBD]:
        chk = (chk - b) & 0xFF
    rom[0xBD] = (chk - 0x19) & 0xFF

    # 10. Reserved (2 bytes)
    rom[0xBE:0xC0] = b"\x00\x00"

    # 11. Optional Save Type Signature
    curr_off = 0xC0
    if save_type.upper() == "SRAM":
        sig = b"SRAM_V110\x00\x00\x00"
        rom[curr_off : curr_off + len(sig)] = sig
        curr_off += len(sig) + 16
    elif save_type.upper() == "FLASH1M":
        sig = b"FLASH1M_V102\x00\x00"
        rom[curr_off : curr_off + len(sig)] = sig
        curr_off += len(sig) + 16
    elif save_type.upper() == "EEPROM":
        sig = b"EEPROM_V111\x00\x00"
        rom[curr_off : curr_off + len(sig)] = sig
        curr_off += len(sig) + 16

    # 12. Optional RTC Signature
    if with_rtc:
        rtc_sig = b"SIIRTC_V001\x00\x00"
        rom[curr_off : curr_off + len(rtc_sig)] = rtc_sig
        curr_off += len(rtc_sig) + 16

    # 13. Optional LZ10 Stream
    if with_lz10:
        from miorom.compression.lz10 import LZ10

        raw_payload = b"GBA_COMPRESSED_GRAPHICS_TEST_PAYLOAD" * 8
        compressed = LZ10.compress(raw_payload)
        curr_off = (curr_off + 3) & ~3
        rom[curr_off : curr_off + len(compressed)] = compressed
        curr_off += len(compressed) + 16

    # 13. Optional Sappy Song Table
    if with_sappy:
        curr_off = (curr_off + 3) & ~3
        song_hdr_off = curr_off + 32
        for s in range(3):
            entry_ptr = 0x08000000 + song_hdr_off + s * 16
            pack_into("<IHH", rom, curr_off + s * 8, entry_ptr, 0, 0)
            rom[song_hdr_off + s * 16] = 1  # 1 track
            pack_into("<I", rom, song_hdr_off + s * 16 + 4, 0x08000000 + 0xC0)

    return bytes(rom)
