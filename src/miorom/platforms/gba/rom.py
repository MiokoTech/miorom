from miorom.errors import ParseError
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U8
from typing import Optional, List

class GBAHeaderStruct(BinaryStruct):
    _endian = "<"
    _reserved_0x00 = RawBytes(0xA0)
    title = FixedString(12)
    game_code = FixedString(4)
    maker_code = FixedString(2)
    _reserved_0xB2 = RawBytes(10)
    version = U8()
    header_checksum = U8()


class GBARom:
    """
    Game Boy Advance ROM parser, header checksum validator/fixer, and save-type detector.
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
        0xD6, 0x25, 0xE4, 0x8B, 0x38, 0x0A, 0xAC, 0x72, 0x21, 0xD4, 0xF8, 0x07
    ])

    def __init__(self, data: bytes):
        if len(data) < 0xC0:
            raise ParseError("Data too small to contain a valid GBA ROM header.")
        self.data = bytearray(data)
        self._header = GBAHeaderStruct.from_bytes(self.data, offset=0)
        self._original_logo_and_entry = bytes(self.data[0:0xA0])

    @classmethod
    def from_file(cls, path: str) -> "GBARom":
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

    def detect_save_type(self) -> str:
        """
        Inspects ROM strings for standard GBA backup library signatures:
        EEPROM (4K/64K), SRAM (256K), FLASH (512K/1M).
        """
        rom_bytes = bytes(self.data)
        if b"EEPROM_V" in rom_bytes:
            return "EEPROM"
        if b"SRAM_V" in rom_bytes or b"SRAM_F_V" in rom_bytes:
            return "SRAM (256Kbit / 32KB)"
        if b"FLASH1M_V" in rom_bytes:
            return "FLASH (1Mbit / 128KB)"
        if b"FLASH_V" in rom_bytes or b"FLASH512_V" in rom_bytes:
            return "FLASH (512Kbit / 64KB)"
        return "UNKNOWN / NONE"

    def to_bytes(self) -> bytes:
        return bytes(self.data)


def fix_gba_checksum(data: bytes) -> bytes:
    """Helper to fix the header complement check byte of a GBA ROM."""
    gba = GBARom(data)
    gba.fix_header_checksum()
    return gba.to_bytes()
