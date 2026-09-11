from miorom.core.schema import BinaryStruct, RawBytes, U16, U32, U8
from miorom.errors import ParseError
from typing import Dict, List, Optional, Tuple, Union
from miorom.graphics.tiles import Tile, decode_tile, encode_tile


class NitroBlockHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    size = U32()

class NFTRFileHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    byte_order_mark = U16()
    version = U16()
    file_size = U32()
    header_size = U16()
    block_count = U16()

class NFTRFontHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    size = U32()
    font_type = U8()
    height = U8()
    _unknown_0x0A = U8()
    cell_width = U8()
    bpp = U8()
    baseline = U8()
    character_encoding = U8()
    _reserved_tail = U8()

class NFTRGlyphCellHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    size = U32()
    cell_width = U8()
    cell_height = U8()
    cell_byte_size = U16()
    _reserved = RawBytes(4)

class NFTRWidthHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    size = U32()
    first_code = U16()
    last_code = U16()
    next_block_offset = U32()

class NFTRCharMapHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    size = U32()
    first_code = U16()
    last_code = U16()
    map_type = U32()
    next_block_offset = U32()


class NFTRGlyph:
    def __init__(
        self,
        code: int,
        tile_or_pixels: Optional[Union[Tile, List[int]]] = None,
        advance: int = 8,
        width: int = 8,
        height: int = 8,
        glyph_index: int = 0,
        tile: Optional[Tile] = None,
    ):
        self.code = code
        self.advance = advance
        self.glyph_index = glyph_index

        target = tile if tile is not None else tile_or_pixels
        if target is None:
            target = [0] * (width * height)

        if isinstance(target, Tile):
            self.width = 8
            self.height = 8
            self.pixels = list(target.pixels)
        else:
            self.width = width
            self.height = height
            self.pixels = list(target)

    def get_pixel(self, x: int, y: int) -> int:
        if 0 <= x < self.width and 0 <= y < self.height:
            return self.pixels[y * self.width + x]
        return 0

    def set_pixel(self, x: int, y: int, val: int):
        if 0 <= x < self.width and 0 <= y < self.height:
            self.pixels[y * self.width + x] = val

    @property
    def tile(self) -> Tile:
        t_pix = [0] * 64
        for y in range(min(8, self.height)):
            for x in range(min(8, self.width)):
                t_pix[y * 8 + x] = self.get_pixel(x, y)
        return Tile(t_pix)


class NFTRFont:
    """
    Nitro Font Resource (.nftr) parser and builder for Nintendo DS games.
    Extracts, modifies, and measures proportional fonts used in NDS titles.
    """

    MAGIC = b"RTFN"

    def __init__(
        self,
        height: int = 12,
        cell_width: int = 8,
        bpp: int = 2,
    ):
        self.height = height
        self.cell_width = cell_width
        self.bpp = bpp
        self.glyphs: Dict[int, NFTRGlyph] = {}

    @classmethod
    def from_bytes(cls, data: bytes) -> "NFTRFont":
        if len(data) < 16:
            raise ParseError("Data too short for NFTR font.")

        magic = data[:4]
        if magic not in (b"RTFN", b"NFTR"):
            raise ParseError(f"Invalid NFTR magic: {magic!r}")

        font = cls()
        pos = 16
        data_len = len(data)

        glyph_bitmaps: List[bytes] = []
        cell_byte_size = 16
        cwdh_table: Dict[int, int] = {}
        code_to_glyph_idx: Dict[int, int] = {}

        while pos + 8 <= data_len:
            block_magic = data[pos : pos + 4]
            block_size = NitroBlockHeaderStruct.from_bytes(data, offset=pos).size
            if block_size == 0 or pos + block_size > data_len:
                break

            block_data = data[pos : pos + block_size]

            if block_magic in (b"FNTH", b"HTNF", b"FNIF", b"FINF"):
                font.height = block_data[9]
                font.cell_width = block_data[11] if len(block_data) > 11 else 8
                font.bpp = block_data[12] if len(block_data) > 12 else 2

            elif block_magic in (b"PLGC", b"CGLP"):
                cell_w = block_data[8]
                cell_h = block_data[9]
                cell_byte_size = U16().unpack(block_data, 10, "<")[0]
                bpp_cand = block_data[14] if len(block_data) > 14 and block_data[14] > 0 else font.bpp
                font.cell_width = cell_w
                font.height = cell_h
                font.bpp = bpp_cand

                raw_glyphs = block_data[16:]
                glyph_bitmaps = []
                if cell_byte_size > 0:
                    for gi in range(0, len(raw_glyphs) - cell_byte_size + 1, cell_byte_size):
                        glyph_bitmaps.append(raw_glyphs[gi : gi + cell_byte_size])

            elif block_magic in (b"CWDH", b"HDWC"):
                first_code = U16().unpack(block_data, 8, "<")[0]
                last_code = U16().unpack(block_data, 10, "<")[0]
                w_pos = 16
                for i in range(first_code, last_code + 1):
                    if w_pos + 3 <= len(block_data):
                        adv = block_data[w_pos + 2]
                        cwdh_table[i] = adv
                        w_pos += 3

            elif block_magic in (b"CMAP", b"PAMC"):
                first_code = U16().unpack(block_data, 8, "<")[0]
                last_code = U16().unpack(block_data, 10, "<")[0]
                map_type = U32().unpack(block_data, 12, "<")[0]

                if map_type == 0:  # Direct index mapping
                    base_idx = U16().unpack(block_data, 20, "<")[0]
                    for offset_i, c in enumerate(range(first_code, last_code + 1)):
                        code_to_glyph_idx[c] = base_idx + offset_i
                elif map_type == 1:  # Table mapping
                    t_pos = 20
                    for c in range(first_code, last_code + 1):
                        if t_pos + 2 <= len(block_data):
                            g_idx = U16().unpack(block_data, t_pos, "<")[0]
                            if g_idx != 0xFFFF:
                                code_to_glyph_idx[c] = g_idx
                            t_pos += 2
                elif map_type == 2:  # Scan list mapping
                    count = U16().unpack(block_data, 20, "<")[0]
                    s_pos = 22
                    for _ in range(count):
                        if s_pos + 4 <= len(block_data):
                            c = U16().unpack(block_data, s_pos, "<")[0]
                            g_idx = U16().unpack(block_data, s_pos + 2, "<")[0]
                            code_to_glyph_idx[c] = g_idx
                            s_pos += 4

            pos += block_size

        # Assemble glyphs using packed bitstream
        for code, g_idx in code_to_glyph_idx.items():
            if g_idx < len(glyph_bitmaps):
                b_data = glyph_bitmaps[g_idx]
                bits = "".join(f"{b:08b}" for b in b_data)
                pixels = []
                total_pixels = font.cell_width * font.height
                for idx in range(total_pixels):
                    b_idx = idx * font.bpp
                    if b_idx + font.bpp <= len(bits):
                        pixels.append(int(bits[b_idx : b_idx + font.bpp], 2))
                    else:
                        pixels.append(0)

                adv = cwdh_table.get(g_idx, cwdh_table.get(code, font.cell_width))
                font.glyphs[code] = NFTRGlyph(
                    code=code,
                    tile_or_pixels=pixels,
                    advance=adv,
                    width=font.cell_width,
                    height=font.height,
                    glyph_index=g_idx,
                )

        return font

    def get_glyph(self, char_or_code) -> Optional[NFTRGlyph]:
        code = ord(char_or_code) if isinstance(char_or_code, str) else char_or_code
        return self.glyphs.get(code)

    def set_glyph(self, char_or_code, tile_or_pixels: Union[Tile, List[int]], advance: Optional[int] = None):
        code = ord(char_or_code) if isinstance(char_or_code, str) else char_or_code
        adv = advance if advance is not None else self.cell_width
        if isinstance(tile_or_pixels, Tile):
            pixels = [0] * (self.cell_width * self.height)
            for y in range(min(8, self.height)):
                for x in range(min(8, self.cell_width)):
                    pixels[y * self.cell_width + x] = tile_or_pixels.get_pixel(x, y)
        else:
            pixels = list(tile_or_pixels)
            if len(pixels) < self.cell_width * self.height:
                pixels.extend([0] * (self.cell_width * self.height - len(pixels)))
        self.glyphs[code] = NFTRGlyph(
            code=code,
            tile_or_pixels=pixels,
            advance=adv,
            width=self.cell_width,
            height=self.height,
        )

    def measure_string(self, text: str) -> int:
        """Calculates exact rendered pixel width for text string."""
        total = 0
        for ch in text:
            g = self.get_glyph(ch)
            total += g.advance if g else self.cell_width
        return total

    def to_bytes(self) -> bytes:
        """Serializes font into a standard Nintendo DS NFTR file binary."""
        sorted_codes = sorted(self.glyphs.keys())
        first_code = sorted_codes[0] if sorted_codes else 0x20
        last_code = sorted_codes[-1] if sorted_codes else 0x20

        # Build PLGC (Glyph cell block)
        total_pixels = self.cell_width * self.height
        cell_size = (total_pixels * self.bpp + 7) // 8
        glyph_data = bytearray()
        code_to_idx: Dict[int, int] = {}

        for idx, code in enumerate(sorted_codes):
            code_to_idx[code] = idx
            g = self.glyphs[code]
            mask = (1 << self.bpp) - 1
            pix = list(g.pixels)
            if len(pix) < total_pixels:
                pix.extend([0] * (total_pixels - len(pix)))
            bits = "".join(f"{p & mask:0{self.bpp}b}" for p in pix[:total_pixels])
            pad = (8 - (len(bits) % 8)) % 8
            bits += "0" * pad
            glyph_bytes = bytes(int(bits[i : i + 8], 2) for i in range(0, len(bits), 8))
            if len(glyph_bytes) < cell_size:
                glyph_bytes += b"\x00" * (cell_size - len(glyph_bytes))
            glyph_data.extend(glyph_bytes[:cell_size])

        plgc_block_len = 16 + len(glyph_data)
        plgc_header = NFTRGlyphCellHeaderStruct(
            magic=b"PLGC",
            size=plgc_block_len,
            cell_width=self.cell_width,
            cell_height=self.height,
            cell_byte_size=cell_size,
        ).to_bytes()
        plgc_block = plgc_header + bytes(glyph_data)

        # Build CWDH (Character widths) - indexed by glyph index
        cwdh_entries = bytearray()
        for idx, code in enumerate(sorted_codes):
            adv = self.glyphs[code].advance
            cwdh_entries.extend([0, self.cell_width, adv])

        cwdh_block_len = 16 + len(cwdh_entries)
        pad = (4 - (cwdh_block_len % 4)) % 4
        cwdh_block_len += pad
        cwdh_header = NFTRWidthHeaderStruct(
            magic=b"CWDH",
            size=cwdh_block_len,
            first_code=0,
            last_code=max(0, len(sorted_codes) - 1),
            next_block_offset=0,
        ).to_bytes()
        cwdh_block = cwdh_header + bytes(cwdh_entries) + (b"\x00" * pad)

        # Build CMAP (Table mapping)
        cmap_entries = bytearray()
        for c in range(first_code, last_code + 1):
            if c in code_to_idx:
                cmap_entries.extend(U16().pack(code_to_idx[c], endian="<"))
            else:
                cmap_entries.extend(U16().pack(0xFFFF, endian="<"))

        cmap_block_len = 20 + len(cmap_entries)
        pad = (4 - (cmap_block_len % 4)) % 4
        cmap_block_len += pad
        cmap_header = NFTRCharMapHeaderStruct(
            magic=b"CMAP",
            size=cmap_block_len,
            first_code=first_code,
            last_code=last_code,
            map_type=1,
            next_block_offset=0,
        ).to_bytes()
        cmap_block = cmap_header + bytes(cmap_entries) + (b"\x00" * pad)

        # Build FNTH
        fnth_block_len = 16
        fnth_block = NFTRFontHeaderStruct(
            magic=b"FNTH",
            size=fnth_block_len,
            height=self.height,
            cell_width=self.cell_width,
            bpp=self.bpp,
        ).to_bytes()

        # File header (16 bytes)
        total_file_len = 16 + len(fnth_block) + len(plgc_block) + len(cwdh_block) + len(cmap_block)
        header = NFTRFileHeaderStruct(
            magic=self.MAGIC,
            byte_order_mark=0xFEFF,
            version=0x0102,
            file_size=total_file_len,
            header_size=16,
            block_count=4,
        ).to_bytes()

        return header + fnth_block + plgc_block + cwdh_block + cmap_block
