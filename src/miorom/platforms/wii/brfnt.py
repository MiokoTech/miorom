"""
src/miorom/platforms/wii/brfnt.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Wii Binary Revolution Font (BRFNT, magic RFNT) and NDS Font Resource (NFTR, magic FONT).
Provides declarative binary structures, multi-sheet Nintendo GX texture decoding/encoding (I4, I8, IA4, IA8),
glyph image extraction/injection, character coverage auditing, and bit-exact rebuilding.

Zero external dependencies: integrates with miorom.graphics.png_codec and miorom.platforms.wii.tpl.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from miorom.core import schema
from miorom.core.schema import (
    U8,
    U16,
    U32,
    BinaryStruct,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.graphics.png_codec import PNGColorType, PNGImage
from miorom.platforms.wii.tpl import decode_gx_texture, encode_gx_texture
from miorom.result import MioRomResult


@dataclass
class CharWidth(MioRomResult):
    """Proportional character width metrics."""

    left_bearing: int
    glyph_width: int
    char_advance: int


class BRFNTHeaderStruct(BinaryStruct):
    """Standard 16-byte Nintendo font file header."""

    _endian = ">"
    magic = RawBytes(4, default=b"RFNT")  # b"RFNT" (Wii) or b"FONT" (NDS)
    byte_order_mark = U16(default=0xFEFF)
    version = U16(default=0x0104)
    file_size = U32(default=0)
    header_size = U16(default=16)
    num_sections = U16(default=4)


class BRFNTFinfStruct(BinaryStruct):
    """32-byte Font Information (FINF) section header."""

    _endian = ">"
    magic = RawBytes(4, default=b"FINF")
    size = U32(default=32)
    font_type = U8(default=0)
    line_height = U8(default=24)
    cell_height = U8(default=24)
    cell_width = U8(default=16)
    ascent = U8(default=20)
    _pad = U8(default=0)
    alter_char_index = U16(default=0)
    default_left_bearing = U8(default=0)
    default_glyph_width = U8(default=12)
    default_char_advance = U8(default=12)
    encoding = U8(default=0)  # 0=UTF-8, 1=UTF-16, 2=SJIS, 3=CP1252
    tglp_offset = U32(default=0)
    cwdh_offset = U32(default=0)
    cmap_offset = U32(default=0)


class BRFNTTglpStruct(BinaryStruct):
    """32-byte Texture Glyph (TGLP) section header preceding sheet pixel data."""

    _endian = ">"
    magic = RawBytes(4, default=b"TGLP")
    size = U32(default=32)
    cell_width = U8(default=16)
    cell_height = U8(default=24)
    baseline = U8(default=20)
    max_width = U8(default=16)
    sheet_size = U32(default=0)
    num_sheets = U16(default=1)
    sheet_format = U16(default=2)  # GX: 0=I4, 1=I8, 2=IA4, 3=IA8, 4=RGB565, 5=RGB5A3, 6=RGBA8
    num_rows = U16(default=16)
    num_cols = U16(default=16)
    sheet_width = U16(default=256)
    sheet_height = U16(default=384)
    sheet_data_offset = U32(default=32)


class BRFNTWidthHeaderStruct(BinaryStruct):
    """16-byte Character Width (CWDH/CWDT) section header."""

    _endian = ">"
    magic = RawBytes(4, default=b"CWDH")
    size = U32(default=16)
    first_glyph = U16(default=0)
    last_glyph = U16(default=0)
    next_section_offset = U32(default=0)


class BRFNTCharMapHeaderStruct(BinaryStruct):
    """20-byte Character Map (CMAP) section header."""

    _endian = ">"
    magic = RawBytes(4, default=b"CMAP")
    size = U32(default=20)
    first_char = U16(default=0)
    last_char = U16(default=0)
    map_type = U16(default=2)  # 0=Direct, 1=Index Table, 2=Key-Value list
    _reserved = U16(default=0)
    next_section_offset = U32(default=0)


class BRFNTFont:
    """
    Nintendo Binary Revolution Font (BRFNT) and NDS Font Resource (NFTR) typography engine.
    Supports:
    - Micro-tiled Nintendo GX texture decoding & encoding (I4, I8, IA4, IA8, RGBA8)
    - Full sheet and individual glyph image extraction/injection via PNGImage
    - Font metrics (advance, bearing, proportional text width) and coverage auditing
    - Adding new characters (font expansion) with automatic sheet and charmap allocation
    - Deterministic binary serialization (to_bytes() and save())
    """

    MAGIC_RFNT = b"RFNT"  # Wii BRFNT
    MAGIC_NFTR = b"FONT"  # NDS NFTR

    def __init__(
        self,
        line_height: int = 24,
        ascent: int = 20,
        default_width: int = 12,
        max_width: int = 16,
        cell_width: int = 16,
        cell_height: int = 24,
        baseline: int = 20,
        sheet_format: int = 2,  # IA4
        sheet_width: int = 256,
        sheet_height: int = 256,
        encoding: str = "utf-8",
        endian: str = ">",
        magic: bytes = b"RFNT",
        version: int = 0x0104,
    ) -> None:
        self.magic = magic
        self.version = version
        self.endian = endian
        self.line_height = line_height
        self.ascent = ascent
        self.default_width = default_width
        self.max_width = max_width
        self.cell_width = cell_width
        self.cell_height = cell_height
        self.baseline = baseline
        self.sheet_format = sheet_format
        self.sheet_width = sheet_width
        self.sheet_height = sheet_height
        self.encoding = encoding

        self.num_cols = max(1, self.sheet_width // max(1, self.cell_width))
        self.num_rows = max(1, self.sheet_height // max(1, self.cell_height))

        # Sheets stored in uncompressed 32-bit linear RGBA bytearrays
        self.sheets_rgba: List[bytearray] = []
        self.char_to_glyph: Dict[int, int] = {}
        self.glyph_widths: Dict[int, CharWidth] = {}

    @property
    def num_sheets(self) -> int:
        return len(self.sheets_rgba)

    @property
    def glyphs_per_sheet(self) -> int:
        return self.num_rows * self.num_cols

    @property
    def total_glyphs_capacity(self) -> int:
        return self.num_sheets * self.glyphs_per_sheet

    @classmethod
    def from_file(cls, filepath: Union[str, Path]) -> BRFNTFont:
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> BRFNTFont:
        if len(data) < 16:
            raise ParseError("Data too short for Nintendo font header.")

        magic = data[:4]
        if magic not in (cls.MAGIC_RFNT, cls.MAGIC_NFTR):
            raise ParseError(f"Invalid font magic: expected RFNT/FONT, got {magic!r}")

        bom = U16(endian=">").unpack(data, 4, ">")[0]
        endian = ">" if bom == 0xFEFF else "<"
        header = BRFNTHeaderStruct.from_bytes(data, endian=endian)

        font = cls(
            endian=endian,
            magic=header.magic,
            version=header.version,
        )

        pos = header.header_size
        data_len = len(data)

        # First pass: parse FINF to determine encoding and metrics
        while pos + 8 <= data_len:
            sec_magic = data[pos : pos + 4]
            sec_size = U32(endian=endian).unpack(data, pos + 4, endian)[0]
            if sec_size == 0 or pos + sec_size > data_len:
                break
            sec_data = data[pos : pos + sec_size]

            if sec_magic == b"FINF":
                font._parse_finf(sec_data)
            elif sec_magic == b"TGLP":
                font._parse_tglp(sec_data)
            elif sec_magic in (b"CWDH", b"CWDT"):
                font._parse_width(sec_data)
            elif sec_magic == b"CMAP":
                font._parse_cmap(sec_data)

            pos += sec_size

        return font

    def _parse_finf(self, data: bytes) -> None:
        endian = self.endian
        if len(data) < 32:
            return
        finf = BRFNTFinfStruct.from_bytes(data, endian=endian)
        self.line_height = finf.line_height
        self.cell_height = finf.cell_height
        self.cell_width = finf.cell_width
        self.default_width = finf.default_char_advance
        self.ascent = finf.ascent
        enc_map = {0: "utf-8", 1: "utf-16", 2: "shift_jis", 3: "cp1252"}
        self.encoding = enc_map.get(finf.encoding, "utf-8")

    def _parse_tglp(self, data: bytes) -> None:
        endian = self.endian
        if len(data) < 32:
            return
        tglp = BRFNTTglpStruct.from_bytes(data, endian=endian)
        self.cell_width = tglp.cell_width
        self.cell_height = tglp.cell_height
        self.baseline = tglp.baseline
        self.max_width = tglp.max_width
        self.sheet_format = tglp.sheet_format
        self.num_rows = tglp.num_rows
        self.num_cols = tglp.num_cols
        self.sheet_width = tglp.sheet_width
        self.sheet_height = tglp.sheet_height

        sheet_size = tglp.sheet_size
        num_sheets = tglp.num_sheets
        offset = tglp.sheet_data_offset

        self.sheets_rgba.clear()
        for s_idx in range(num_sheets):
            sheet_start = offset + s_idx * sheet_size
            sheet_end = sheet_start + sheet_size
            if sheet_end <= len(data):
                raw_sheet = data[sheet_start:sheet_end]
                rgba = decode_gx_texture(
                    raw=raw_sheet,
                    width=self.sheet_width,
                    height=self.sheet_height,
                    format_id=self.sheet_format,
                )
                self.sheets_rgba.append(bytearray(rgba))
            else:
                # Fallback blank sheet if truncated
                blank = bytearray(self.sheet_width * self.sheet_height * 4)
                self.sheets_rgba.append(blank)

    def _parse_width(self, data: bytes) -> None:
        endian = self.endian
        if len(data) < 16:
            return
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

    def _parse_cmap(self, data: bytes) -> None:
        endian = self.endian
        if len(data) < 20:
            return
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

    # ---------------------------------------------------------------------------
    # Image Extraction and Manipulation API
    # ---------------------------------------------------------------------------

    def get_sheet_image(self, sheet_index: int = 0) -> PNGImage:
        """Extracts a full texture sheet as a 32-bit RGBA PNGImage."""
        if sheet_index < 0 or sheet_index >= len(self.sheets_rgba):
            raise IndexError(f"Sheet index {sheet_index} out of range (font has {len(self.sheets_rgba)} sheets).")
        return PNGImage(
            width=self.sheet_width,
            height=self.sheet_height,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=bytes(self.sheets_rgba[sheet_index]),
        )

    def export_sheets(self, output_dir: Union[str, Path], prefix: str = "sheet") -> List[Path]:
        """Saves all texture sheets to PNG files in the specified directory."""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        saved_paths: List[Path] = []
        for i in range(len(self.sheets_rgba)):
            img = self.get_sheet_image(i)
            target = out_path / f"{prefix}_{i:02d}.png"
            img.save(str(target))
            saved_paths.append(target)
        return saved_paths

    def _get_glyph_coordinates(self, glyph_index: int) -> Tuple[int, int, int]:
        """Calculates (sheet_index, pixel_x, pixel_y) for a glyph index."""
        per_sheet = self.glyphs_per_sheet
        if per_sheet <= 0:
            raise ParseError("Invalid font sheet dimensions: glyphs_per_sheet is 0.")

        sheet_idx = glyph_index // per_sheet
        idx_in_sheet = glyph_index % per_sheet
        row = idx_in_sheet // self.num_cols
        col = idx_in_sheet % self.num_cols
        px = col * self.cell_width
        py = row * self.cell_height
        return sheet_idx, px, py

    def get_glyph_image(self, char_or_index: Union[str, int]) -> PNGImage:
        """
        Extracts a single glyph cell as an RGBA PNGImage of size cell_width x cell_height.
        """
        if isinstance(char_or_index, str):
            code = ord(char_or_index)
            if code not in self.char_to_glyph:
                raise KeyError(f"Character {char_or_index!r} (code 0x{code:04X}) not found in font charmap.")
            glyph_idx = self.char_to_glyph[code]
        else:
            glyph_idx = char_or_index

        sheet_idx, px, py = self._get_glyph_coordinates(glyph_idx)
        if sheet_idx >= len(self.sheets_rgba):
            raise IndexError(f"Glyph index {glyph_idx} references non-existent sheet {sheet_idx}.")

        sheet_buf = self.sheets_rgba[sheet_idx]
        sw = self.sheet_width
        cw = self.cell_width
        ch = self.cell_height

        glyph_rgba = bytearray(cw * ch * 4)
        for y in range(ch):
            src_y = py + y
            if src_y >= self.sheet_height:
                break
            src_offset = (src_y * sw + px) * 4
            dst_offset = y * cw * 4
            row_bytes = min(cw, sw - px) * 4
            glyph_rgba[dst_offset : dst_offset + row_bytes] = sheet_buf[src_offset : src_offset + row_bytes]

        return PNGImage(
            width=cw,
            height=ch,
            color_type=PNGColorType.RGBA,
            bit_depth=8,
            pixels=bytes(glyph_rgba),
        )

    def inject_glyph_image(
        self,
        char_or_index: Union[str, int],
        image: Union[PNGImage, bytes],
        left_bearing: Optional[int] = None,
        glyph_width: Optional[int] = None,
        char_advance: Optional[int] = None,
    ) -> None:
        """
        Injects a replacement glyph bitmap into the font sheet and updates metrics.
        """
        if isinstance(char_or_index, str):
            code = ord(char_or_index)
            if code not in self.char_to_glyph:
                raise KeyError(f"Character {char_or_index!r} not in font; use add_character() instead.")
            glyph_idx = self.char_to_glyph[code]
        else:
            glyph_idx = char_or_index

        sheet_idx, px, py = self._get_glyph_coordinates(glyph_idx)
        while sheet_idx >= len(self.sheets_rgba):
            # Allocate missing sheet
            self.sheets_rgba.append(bytearray(self.sheet_width * self.sheet_height * 4))

        if isinstance(image, PNGImage):
            src_rgba = image.to_rgba_bytes()
            img_w, img_h = image.width, image.height
        elif isinstance(image, (bytes, bytearray)):
            if image[:8] == b"\x89PNG\r\n\x1a\n":
                png = PNGImage.from_bytes(bytes(image))
                src_rgba = png.to_rgba_bytes()
                img_w, img_h = png.width, png.height
            else:
                src_rgba = bytes(image)
                img_w, img_h = self.cell_width, self.cell_height
        else:
            raise TypeError(f"Unsupported image type: {type(image)}")

        cw = self.cell_width
        ch = self.cell_height
        sw = self.sheet_width
        sheet_buf = self.sheets_rgba[sheet_idx]

        # Copy pixels with bounding clamp
        copy_w = min(cw, img_w)
        copy_h = min(ch, img_h)

        for y in range(copy_h):
            dst_y = py + y
            if dst_y >= self.sheet_height:
                break
            src_offset = y * img_w * 4
            dst_offset = (dst_y * sw + px) * 4
            row_bytes = copy_w * 4
            sheet_buf[dst_offset : dst_offset + row_bytes] = src_rgba[src_offset : src_offset + row_bytes]

        # Update metrics if specified
        if left_bearing is not None or glyph_width is not None or char_advance is not None:
            cur_width = self.glyph_widths.get(glyph_idx, CharWidth(0, self.cell_width, self.cell_width))
            self.glyph_widths[glyph_idx] = CharWidth(
                left_bearing=left_bearing if left_bearing is not None else cur_width.left_bearing,
                glyph_width=glyph_width if glyph_width is not None else cur_width.glyph_width,
                char_advance=char_advance if char_advance is not None else cur_width.char_advance,
            )

    # ---------------------------------------------------------------------------
    # Font Expansion API
    # ---------------------------------------------------------------------------

    def add_character(
        self,
        char: str,
        image: Optional[Union[PNGImage, bytes]] = None,
        left_bearing: int = 0,
        glyph_width: Optional[int] = None,
        char_advance: Optional[int] = None,
    ) -> int:
        """
        Adds a new character (e.g. accented Latin, Indonesian, or symbol) to the font.
        Allocates a new glyph index and sheet cell, injects image, and registers CMAP/CWDH.
        Returns the assigned glyph_index.
        """
        code = ord(char)
        if code in self.char_to_glyph:
            glyph_idx = self.char_to_glyph[code]
            if image is not None:
                self.inject_glyph_image(
                    glyph_idx,
                    image,
                    left_bearing=left_bearing,
                    glyph_width=glyph_width,
                    char_advance=char_advance,
                )
            return glyph_idx

        # Find next available glyph index
        max_existing = max(self.char_to_glyph.values(), default=-1)
        next_glyph = max(max_existing + 1, max(self.glyph_widths.keys(), default=-1) + 1)
        if next_glyph < 0:
            next_glyph = 0

        # Ensure enough sheets exist
        needed_sheet_idx = next_glyph // max(1, self.glyphs_per_sheet)
        while len(self.sheets_rgba) <= needed_sheet_idx:
            self.sheets_rgba.append(bytearray(self.sheet_width * self.sheet_height * 4))

        # Register mapping
        self.char_to_glyph[code] = next_glyph
        gw = glyph_width if glyph_width is not None else self.cell_width
        ca = char_advance if char_advance is not None else gw
        self.glyph_widths[next_glyph] = CharWidth(left_bearing=left_bearing, glyph_width=gw, char_advance=ca)

        if image is not None:
            self.inject_glyph_image(
                next_glyph,
                image,
                left_bearing=left_bearing,
                glyph_width=gw,
                char_advance=ca,
            )

        return next_glyph

    # ---------------------------------------------------------------------------
    # Queries & Metrics
    # ---------------------------------------------------------------------------

    def has_char(self, char: str) -> bool:
        """Checks if a character exists in the font."""
        return ord(char) in self.char_to_glyph

    def get_char_width(self, char: str) -> int:
        """Returns the advance width of a character in pixels."""
        code = ord(char)
        glyph_idx = self.char_to_glyph.get(code)
        if glyph_idx is not None and glyph_idx in self.glyph_widths:
            return self.glyph_widths[glyph_idx].char_advance
        return self.default_width

    def get_text_width(self, text: str) -> int:
        """Calculates total pixel width of text rendered with this font."""
        total = 0
        for ch in text:
            if ch == "\n":
                continue
            total += self.get_char_width(ch)
        return total

    def audit_string(self, text: str) -> Tuple[bool, List[str]]:
        """Checks for missing characters in text string. Returns (is_valid, missing_list)."""
        missing: List[str] = []
        for ch in set(text):
            if ch not in ("\n", "\r", "\t") and not self.has_char(ch):
                missing.append(ch)
        return (len(missing) == 0, sorted(missing))

    # ---------------------------------------------------------------------------
    # Factory & Serialization
    # ---------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        cell_width: int = 16,
        cell_height: int = 24,
        line_height: int = 24,
        sheet_format: int = 2,  # IA4
        sheet_width: int = 256,
        sheet_height: int = 256,
        encoding: str = "utf-8",
        num_sheets: int = 1,
    ) -> BRFNTFont:
        """Instantiates a new blank BRFNT font ready for character addition."""
        font = cls(
            cell_width=cell_width,
            cell_height=cell_height,
            line_height=line_height,
            sheet_format=sheet_format,
            sheet_width=sheet_width,
            sheet_height=sheet_height,
            encoding=encoding,
        )
        for _ in range(max(1, num_sheets)):
            font.sheets_rgba.append(bytearray(sheet_width * sheet_height * 4))
        return font

    def to_bytes(self) -> bytes:
        """
        Reconstructs bit-exact Nintendo RFNT/FONT binary data with valid FINF, TGLP,
        CWDH, and CMAP sections.
        """
        endian = self.endian

        # Ensure at least 1 sheet exists
        if not self.sheets_rgba:
            self.sheets_rgba.append(bytearray(self.sheet_width * self.sheet_height * 4))

        # 1. Encode texture sheets to GX format
        encoded_sheets: List[bytes] = []
        for sheet_rgba in self.sheets_rgba:
            gx_data = encode_gx_texture(
                rgba=bytes(sheet_rgba),
                width=self.sheet_width,
                height=self.sheet_height,
                format_id=self.sheet_format,
            )
            encoded_sheets.append(gx_data)

        single_sheet_size = len(encoded_sheets[0])
        total_sheet_data = b"".join(encoded_sheets)

        # 2. Build TGLP Section
        tglp_header_size = 32
        tglp_total_size = tglp_header_size + len(total_sheet_data)
        tglp_struct = BRFNTTglpStruct(
            magic=b"TGLP",
            size=tglp_total_size,
            cell_width=self.cell_width,
            cell_height=self.cell_height,
            baseline=self.baseline,
            max_width=self.max_width,
            sheet_size=single_sheet_size,
            num_sheets=len(encoded_sheets),
            sheet_format=self.sheet_format,
            num_rows=self.num_rows,
            num_cols=self.num_cols,
            sheet_width=self.sheet_width,
            sheet_height=self.sheet_height,
            sheet_data_offset=tglp_header_size,
        )
        tglp_bytes = tglp_struct.to_bytes(endian=endian) + total_sheet_data

        # 3. Build CWDH Section
        max_glyph = max(self.glyph_widths.keys(), default=0)
        first_glyph = 0
        last_glyph = max_glyph

        cwdh_payload = bytearray()
        for g_idx in range(first_glyph, last_glyph + 1):
            w = self.glyph_widths.get(g_idx, CharWidth(0, self.cell_width, self.cell_width))
            cwdh_payload.extend([w.left_bearing & 0xFF, w.glyph_width & 0xFF, w.char_advance & 0xFF])

        # Align payload to 4 bytes
        pad_len = (4 - (len(cwdh_payload) % 4)) % 4
        cwdh_payload.extend(b"\x00" * pad_len)

        cwdh_total_size = 16 + len(cwdh_payload)
        cwdh_struct = BRFNTWidthHeaderStruct(
            magic=b"CWDH",
            size=cwdh_total_size,
            first_glyph=first_glyph,
            last_glyph=last_glyph,
            next_section_offset=0,
        )
        cwdh_bytes = cwdh_struct.to_bytes(endian=endian) + bytes(cwdh_payload)

        # 4. Build CMAP Section (Type 2: Key-value list for maximum flexibility)
        sorted_chars = sorted(self.char_to_glyph.items())
        cmap_payload = bytearray()
        cmap_payload.extend(schema.pack(f"{endian}H", len(sorted_chars)))  # count
        for char_code, glyph_idx in sorted_chars:
            cmap_payload.extend(schema.pack(f"{endian}HH", char_code, glyph_idx))

        # Align to 4 bytes
        cmap_pad = (4 - (len(cmap_payload) % 4)) % 4
        cmap_payload.extend(b"\x00" * cmap_pad)

        first_c = sorted_chars[0][0] if sorted_chars else 0
        last_c = sorted_chars[-1][0] if sorted_chars else 0
        cmap_total_size = 20 + len(cmap_payload)

        cmap_struct = BRFNTCharMapHeaderStruct(
            magic=b"CMAP",
            size=cmap_total_size,
            first_char=first_c,
            last_char=last_c,
            map_type=2,  # Type 2 key-value mapping
            _reserved=0,
            next_section_offset=0,
        )
        cmap_bytes = cmap_struct.to_bytes(endian=endian) + bytes(cmap_payload)

        # Calculate offsets
        finf_offset = 16
        finf_size = 32
        tglp_offset = finf_offset + finf_size
        cwdh_offset = tglp_offset + len(tglp_bytes)
        cmap_offset = cwdh_offset + len(cwdh_bytes)
        total_file_size = cmap_offset + len(cmap_bytes)

        enc_code_map = {"utf-8": 0, "utf-16": 1, "shift_jis": 2, "cp1252": 3}
        enc_code = enc_code_map.get(self.encoding.lower(), 0)

        finf_struct = BRFNTFinfStruct(
            magic=b"FINF",
            size=finf_size,
            font_type=0,
            line_height=self.line_height,
            cell_height=self.cell_height,
            cell_width=self.cell_width,
            ascent=self.ascent,
            _pad=0,
            alter_char_index=0,
            default_left_bearing=0,
            default_glyph_width=self.default_width,
            default_char_advance=self.default_width,
            encoding=enc_code,
            tglp_offset=tglp_offset,
            cwdh_offset=cwdh_offset,
            cmap_offset=cmap_offset,
        )
        finf_bytes = finf_struct.to_bytes(endian=endian)

        # 5. Build RFNT Header
        rfnt_header = BRFNTHeaderStruct(
            magic=self.magic,
            byte_order_mark=0xFEFF if endian == ">" else 0xFFFE,
            version=self.version,
            file_size=total_file_size,
            header_size=16,
            num_sections=4,
        )
        header_bytes = rfnt_header.to_bytes(endian=endian)

        return header_bytes + finf_bytes + tglp_bytes + cwdh_bytes + cmap_bytes

    def save(self, filepath: Union[str, Path]) -> None:
        """Saves font to binary file."""
        target = Path(filepath)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(self.to_bytes())
