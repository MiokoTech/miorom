from miorom.result import MioRomResult
from miorom.errors import ParseError
from dataclasses import dataclass, field
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from typing import Dict, Optional, Tuple, List


@dataclass
class CharWidth(MioRomResult):
    left_bearing: int
    glyph_width: int
    char_advance: int

class BRFNTHeaderStruct(BinaryStruct):
    magic = RawBytes(4)
    byte_order_mark = U16()
    version = U16()
    file_size = U32()
    header_size = U16()
    num_sections = U16()

class BRFNTWidthHeaderStruct(BinaryStruct):
    magic = RawBytes(4)
    size = U32()
    first_glyph = U16()
    last_glyph = U16()
    next_section_offset = U32()

class BRFNTCharMapHeaderStruct(BinaryStruct):
    magic = RawBytes(4)
    size = U32()
    first_char = U16()
    last_char = U16()
    map_type = U16()
    _reserved = U16()
    next_section_offset = U32()


class BRFNTFont:
    """
    Nintendo Binary Revolution Font (BRFNT) and NDS Font Resource (NFTR) parser.
    Used across Wii, GameCube, and Nintendo DS games.
    Provides font metrics, character coverage audit, and proportional string width measurement.
    """

    MAGIC_RFNT = b"RFNT"  # Wii BRFNT
    MAGIC_NFTR = b"FONT"  # NDS NFTR

    def __init__(
        self,
        line_height: int = 16,
        ascent: int = 14,
        default_width: int = 8,
        max_width: int = 16,
        encoding: str = "utf-8",
        endian: str = ">"
    ):
        self.line_height = line_height
        self.ascent = ascent
        self.default_width = default_width
        self.max_width = max_width
        self.encoding = encoding
        self.endian = endian
        self.char_to_glyph: Dict[int, int] = {}
        self.glyph_widths: Dict[int, CharWidth] = {}

    @classmethod
    def from_file(cls, filepath: str) -> "BRFNTFont":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BRFNTFont":
        if len(data) < 16:
            raise ParseError("Data too short for Nintendo font header.")

        magic = data[:4]
        bom = U16(endian=">").unpack(data, 4, ">")[0]
        endian = ">" if bom == 0xFEFF else "<"
        header = BRFNTHeaderStruct.from_bytes(data, endian=endian)
        header_size = header.header_size
        num_sections = header.num_sections

        font = cls(endian=endian)
        pos = header_size

        for _ in range(num_sections):
            if pos + 8 > len(data):
                break
            sec_magic = data[pos:pos+4]
            sec_size = U32(endian=endian).unpack(data, pos + 4, endian)[0]
            sec_data = data[pos:pos+sec_size]

            if sec_magic == b"FINF":
                font._parse_finf(sec_data)
            elif sec_magic in (b"CWDH", b"CWDT"):
                font._parse_width(sec_data)
            elif sec_magic == b"CMAP":
                font._parse_cmap(sec_data)

            pos += sec_size

        return font

    def _parse_finf(self, data: bytes):
        endian = self.endian
        if len(data) < 20:
            return
        # FINF header: magic (4), size (4), font_type (1), line_feed (1),
        # alter_char_index (2), default_width (CharWidth: 3 bytes), encoding (1)
        font_type = data[8]
        self.line_height = data[9]
        self.default_width = data[12] if len(data) > 12 else 8
        enc_id = data[15] if len(data) > 15 else 0
        enc_map = {0: "utf-8", 1: "utf-16", 2: "shift_jis", 3: "cp1252"}
        self.encoding = enc_map.get(enc_id, "utf-8")

    def _parse_width(self, data: bytes):
        endian = self.endian
        if len(data) < 16:
            return
        # Magic (4), Size (4), First Glyph (2), Last Glyph (2), Next Section (4)
        width_header = BRFNTWidthHeaderStruct.from_bytes(data, endian=endian)
        first_glyph, last_glyph = width_header.first_glyph, width_header.last_glyph
        pos = 16
        for g_idx in range(first_glyph, last_glyph + 1):
            if pos + 3 <= len(data):
                lb = data[pos]
                gw = data[pos + 1]
                ca = data[pos + 2]
                self.glyph_widths[g_idx] = CharWidth(left_bearing=lb, glyph_width=gw, char_advance=ca)
                pos += 3

    def _parse_cmap(self, data: bytes):
        endian = self.endian
        if len(data) < 20:
            return
        # Magic (4), Size (4), First Char (2), Last Char (2), Map Type (2), Reserved (2), Next Section (4)
        charmap_header = BRFNTCharMapHeaderStruct.from_bytes(data, endian=endian)
        first_char = charmap_header.first_char
        last_char = charmap_header.last_char
        map_type = charmap_header.map_type
        pos = 20

        if map_type == 0:  # Direct sequential mapping
            index_offset = U16(endian=endian).unpack(data, pos, endian)[0]
            for c in range(first_char, last_char + 1):
                self.char_to_glyph[c] = index_offset + (c - first_char)
        elif map_type == 1:  # Table mapping
            for c in range(first_char, last_char + 1):
                if pos + 2 <= len(data):
                    g_idx = U16(endian=endian).unpack(data, pos, endian)[0]
                    if g_idx != 0xFFFF:
                        self.char_to_glyph[c] = g_idx
                    pos += 2
        elif map_type == 2:  # Key-value mapping
            count = U16(endian=endian).unpack(data, pos, endian)[0]
            pos += 2
            for _ in range(count):
                if pos + 4 <= len(data):
                    c = U16(endian=endian).unpack(data, pos, endian)[0]
                    g_idx = U16(endian=endian).unpack(data, pos + 2, endian)[0]
                    self.char_to_glyph[c] = g_idx
                    pos += 4

    def has_char(self, char: str) -> bool:
        """Checks if a character exists in the font."""
        code = ord(char)
        return code in self.char_to_glyph

    def get_char_width(self, char: str) -> int:
        """Returns the advance width of a character in pixels."""
        code = ord(char)
        glyph_idx = self.char_to_glyph.get(code)
        if glyph_idx is not None and glyph_idx in self.glyph_widths:
            return self.glyph_widths[glyph_idx].char_advance
        return self.default_width

    def get_text_width(self, text: str) -> int:
        """
        Calculates the exact total pixel width of a string rendered in this font.
        """
        total = 0
        for ch in text:
            if ch == "\n":
                continue
            total += self.get_char_width(ch)
        return total

    def audit_string(self, text: str) -> Tuple[bool, List[str]]:
        """
        Audits a string to check if all characters exist in the font.
        Returns (is_valid, list_of_missing_characters).
        """
        missing = []
        for ch in set(text):
            if ch not in ("\n", "\r", "\t") and not self.has_char(ch):
                missing.append(ch)
        return (len(missing) == 0, missing)
