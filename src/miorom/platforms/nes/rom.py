"""
miorom.platforms.nes.rom
~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Entertainment System (NES / Famicom) ROM Handler.
Supports iNES and NES 2.0 headers, mapper identification, trainer extraction/stripping,
PRG-ROM / CHR-ROM separation and re-injection.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple
from miorom.core.schema import BinaryStruct, RawBytes, U8
from miorom.errors import ParseError


class NESHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"NES\x1A"
    prg_rom_16kb = U8()
    chr_rom_8kb = U8()
    flags6 = U8()
    flags7 = U8()
    flags8 = U8()
    flags9 = U8()
    flags10 = U8()
    reserved = RawBytes(5)


class NESRom:
    """
    Nintendo Entertainment System (NES) and Family Computer (Famicom) ROM inspector and builder.
    Handles iNES and NES 2.0 formats, trainer blocks, PRG/CHR separation, and mapper resolution.
    """

    MAGIC = b"NES\x1a"
    HEADER_SIZE = 16
    TRAINER_SIZE = 512

    MAPPER_NAMES: Dict[int, str] = {
        0: "NROM",
        1: "MMC1 (SxROM)",
        2: "UNROM / UxROM",
        3: "CNROM",
        4: "MMC3 (TxROM)",
        5: "MMC5 (ExROM)",
        7: "AxROM",
        9: "MMC2 (PxROM)",
        10: "MMC4 (FxROM)",
        11: "Color Dreams",
        13: "CPROM",
        15: "100-in-1 Contra Function",
        16: "Bandai EPROM / 24C02",
        18: "Jaleco SS88006",
        19: "Namco 163 / 129",
        21: "Konami VRC4a/VRC4c",
        22: "Konami VRC2a",
        23: "Konami VRC2b/VRC4e/VRC4f",
        24: "Konami VRC6a",
        25: "Konami VRC4b/VRC4d",
        26: "Konami VRC6b",
        34: "BNROM / NINA-001",
        64: "Tengen RAMBO-1",
        66: "GxROM / MHROM",
        69: "Sunsoft FME-7",
        71: "Camerica / Codemasters",
        73: "Konami VRC3",
        75: "Konami VRC1",
        79: "American Video Entertainment",
        85: "Konami VRC7",
        163: "NanJing",
    }

    def __init__(self, data: bytes):
        if len(data) < self.HEADER_SIZE:
            raise ParseError("Data too small for NES header (minimum 16 bytes).")
        if data[:4] != self.MAGIC:
            raise ParseError(f"Invalid NES header magic: {data[:4]!r}, expected {self.MAGIC!r}")

        self.data = bytearray(data)
        self._header = NESHeaderStruct.from_bytes(self.data, offset=0)

    @classmethod
    def from_file(cls, path: str) -> "NESRom":
        with open(path, "rb") as f:
            return cls(f.read())

    @property
    def is_nes20(self) -> bool:
        """Returns True if the header adheres to the NES 2.0 specification."""
        return (self._header.flags7 & 0x0C) == 0x08

    @property
    def mapper_id(self) -> int:
        """Resolves the mapper number (0..4095)."""
        lower = (self._header.flags6 >> 4) & 0x0F
        upper = self._header.flags7 & 0xF0
        mapper = lower | upper
        if self.is_nes20:
            ext = (self._header.flags8 & 0x0F) << 8
            mapper |= ext
        return mapper

    @property
    def mapper_name(self) -> str:
        """Human-readable mapper name or fallback description."""
        mid = self.mapper_id
        return self.MAPPER_NAMES.get(mid, f"Mapper {mid}")

    @property
    def has_battery(self) -> bool:
        """True if battery-backed PRG-RAM is present."""
        return bool(self._header.flags6 & 0x02)

    @property
    def has_trainer(self) -> bool:
        """True if 512-byte trainer is present between header and PRG-ROM."""
        return bool(self._header.flags6 & 0x04)

    @property
    def mirroring(self) -> str:
        """Mirroring type: 'four_screen', 'vertical', or 'horizontal'."""
        if self._header.flags6 & 0x08:
            return "four_screen"
        return "vertical" if (self._header.flags6 & 0x01) else "horizontal"

    @property
    def prg_size(self) -> int:
        """PRG-ROM size in bytes."""
        units = self._header.prg_rom_16kb
        if self.is_nes20:
            msb = self._header.flags9 & 0x0F
            if msb == 0x0F:
                multiplier = (units & 0x03) * 2 + 1
                exponent = units >> 2
                return (2 ** exponent) * multiplier
            units |= msb << 8
        elif units == 0:
            # Archaic iNES: 0 indicates 256 banks (4MB)
            units = 256
        return units * 16384

    @property
    def chr_size(self) -> int:
        """CHR-ROM size in bytes (0 indicates CHR-RAM)."""
        units = self._header.chr_rom_8kb
        if self.is_nes20:
            msb = (self._header.flags9 & 0xF0) >> 4
            if msb == 0x0F:
                multiplier = (units & 0x03) * 2 + 1
                exponent = units >> 2
                return (2 ** exponent) * multiplier
            units |= msb << 8
        return units * 8192

    @property
    def has_chr_ram(self) -> bool:
        """True if cartridge uses CHR-RAM instead of CHR-ROM."""
        return self.chr_size == 0

    def _prg_offset(self) -> int:
        return self.HEADER_SIZE + (self.TRAINER_SIZE if self.has_trainer else 0)

    def _chr_offset(self) -> int:
        return self._prg_offset() + self.prg_size

    @property
    def trainer(self) -> Optional[bytes]:
        """Returns 512-byte trainer data if present, otherwise None."""
        if not self.has_trainer:
            return None
        return bytes(self.data[self.HEADER_SIZE : self.HEADER_SIZE + self.TRAINER_SIZE])

    @property
    def prg_rom(self) -> bytes:
        """Returns the raw PRG-ROM byte array."""
        start = self._prg_offset()
        end = start + self.prg_size
        return bytes(self.data[start:end])

    @property
    def chr_rom(self) -> bytes:
        """Returns the raw CHR-ROM byte array (empty if CHR-RAM)."""
        if self.has_chr_ram:
            return b""
        start = self._chr_offset()
        end = start + self.chr_size
        return bytes(self.data[start:end])

    def strip_trainer(self) -> bool:
        """Removes the 512-byte trainer if present and updates flags. Returns True if stripped."""
        if not self.has_trainer:
            return False
        start = self.HEADER_SIZE
        end = start + self.TRAINER_SIZE
        self.data = self.data[:start] + self.data[end:]
        self._header.flags6 &= ~0x04
        self.data[0:self.HEADER_SIZE] = self._header.to_bytes()
        return True

    def add_trainer(self, trainer_data: bytes) -> bool:
        """Prepends a 512-byte trainer and updates flags. Returns True if added."""
        if len(trainer_data) != self.TRAINER_SIZE:
            raise ParseError(f"Trainer must be exactly {self.TRAINER_SIZE} bytes (got {len(trainer_data)}).")
        if self.has_trainer:
            # Replace existing
            self.data[self.HEADER_SIZE : self.HEADER_SIZE + self.TRAINER_SIZE] = trainer_data
        else:
            self.data = self.data[:self.HEADER_SIZE] + bytearray(trainer_data) + self.data[self.HEADER_SIZE:]
            self._header.flags6 |= 0x04
            self.data[0:self.HEADER_SIZE] = self._header.to_bytes()
        return True

    def set_prg_rom(self, new_prg: bytes):
        """Replaces the PRG-ROM data and recalculates the header size field."""
        if len(new_prg) % 16384 != 0:
            raise ParseError(f"PRG-ROM must be a multiple of 16KB (16384 bytes). Got {len(new_prg)}.")
        prg_start = self._prg_offset()
        prg_end = prg_start + self.prg_size
        self.data = self.data[:prg_start] + bytearray(new_prg) + self.data[prg_end:]
        units = len(new_prg) // 16384
        self._header.prg_rom_16kb = units & 0xFF
        self.data[0:self.HEADER_SIZE] = self._header.to_bytes()

    def set_chr_rom(self, new_chr: bytes):
        """Replaces the CHR-ROM data and recalculates the header size field."""
        if len(new_chr) > 0 and len(new_chr) % 8192 != 0:
            raise ParseError(f"CHR-ROM must be a multiple of 8KB (8192 bytes). Got {len(new_chr)}.")
        chr_start = self._chr_offset()
        self.data = self.data[:chr_start] + bytearray(new_chr)
        units = len(new_chr) // 8192
        self._header.chr_rom_8kb = units & 0xFF
        self.data[0:self.HEADER_SIZE] = self._header.to_bytes()

    def to_bytes(self) -> bytes:
        """Returns the full ROM binary representation."""
        return bytes(self.data)

    def save(self, path: str):
        """Writes the ROM back to disk."""
        with open(path, "wb") as f:
            f.write(self.data)
