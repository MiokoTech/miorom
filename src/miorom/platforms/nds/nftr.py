import struct
from typing import Dict, List, Optional, Tuple
from miorom.graphics.tiles import Tile, decode_tile, encode_tile


class NFTRGlyph:
    def __init__(self, code: int, tile: Tile, advance: int):
        self.code = code
        self.tile = tile
        self.advance = advance


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
            raise ValueError("Data too short for NFTR font.")

        magic = data[:4]
        if magic not in (b"RTFN", b"NFTR"):
            raise ValueError(f"Invalid NFTR magic: {magic!r}")

        font = cls()
        pos = 16
        data_len = len(data)

        # Temporary holders
        glyph_bitmaps: List[bytes] = []
        cell_byte_size = 16
        cwdh_table: Dict[int, int] = {}
        code_to_glyph_idx: Dict[int, int] = {}

        while pos + 8 <= data_len:
            block_magic = data[pos : pos + 4]
            block_size = struct.unpack_from("<I", data, pos + 4)[0]
            if block_size == 0 or pos + block_size > data_len:
                break

            block_data = data[pos : pos + block_size]

            if block_magic in (b"HTNF", b"FNTH"):
                # Font header
                font.height = block_data[9]
                font.cell_width = block_data[11]
                font.bpp = block_data[12]

            elif block_magic in (b"CGLP", b"PLGC"):
                # Glyph bitmap data
                cell_w = block_data[8]
                cell_h = block_data[9]
                cell_byte_size = struct.unpack_from("<H", block_data, 10)[0]
                raw_glyphs = block_data[16:]

                glyph_bitmaps = []
                for gi in range(0, len(raw_glyphs) - cell_byte_size + 1, cell_byte_size):
                    glyph_bitmaps.append(raw_glyphs[gi : gi + cell_byte_size])

            elif block_magic in (b"HDWC", b"CWDH"):
                # Character width table
                first_code, last_code = struct.unpack_from("<HH", block_data, 8)
                w_pos = 16
                for c in range(first_code, last_code + 1):
                    if w_pos + 3 <= len(block_data):
                        adv = block_data[w_pos + 2]
                        cwdh_table[c] = adv
                        w_pos += 3

            elif block_magic in (b"PAMC", b"CMAP"):
                # Character map
                first_code, last_code = struct.unpack_from("<HH", block_data, 8)
                map_type = struct.unpack_from("<H", block_data, 12)[0]

                if map_type == 0:  # Direct index mapping
                    base_idx = struct.unpack_from("<H", block_data, 16)[0]
                    for offset_i, c in enumerate(range(first_code, last_code + 1)):
                        code_to_glyph_idx[c] = base_idx + offset_i
                elif map_type == 1:  # Table mapping
                    t_pos = 20  # entries start after 20-byte CMAP header
                    for c in range(first_code, last_code + 1):
                        if t_pos + 2 <= len(block_data):
                            g_idx = struct.unpack_from("<H", block_data, t_pos)[0]
                            if g_idx != 0xFFFF:
                                code_to_glyph_idx[c] = g_idx
                            t_pos += 2

            pos += block_size

        # Assemble glyphs
        for code, g_idx in code_to_glyph_idx.items():
            if g_idx < len(glyph_bitmaps):
                b_data = glyph_bitmaps[g_idx]
                tile = decode_tile(b_data, bpp=font.bpp)
                adv = cwdh_table.get(code, font.cell_width)
                font.glyphs[code] = NFTRGlyph(code=code, tile=tile, advance=adv)

        return font

    def get_glyph(self, char_or_code) -> Optional[NFTRGlyph]:
        code = ord(char_or_code) if isinstance(char_or_code, str) else char_or_code
        return self.glyphs.get(code)

    def set_glyph(self, char_or_code, tile: Tile, advance: Optional[int] = None):
        code = ord(char_or_code) if isinstance(char_or_code, str) else char_or_code
        adv = advance if advance is not None else self.cell_width
        self.glyphs[code] = NFTRGlyph(code=code, tile=tile, advance=adv)

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
        cell_size = {1: 8, 2: 16, 4: 32, 8: 64}.get(self.bpp, 16)
        glyph_data = bytearray()
        code_to_idx: Dict[int, int] = {}

        for idx, code in enumerate(sorted_codes):
            code_to_idx[code] = idx
            g = self.glyphs[code]
            glyph_data.extend(encode_tile(g.tile, bpp=self.bpp))

        plgc_block_len = 16 + len(glyph_data)
        plgc_header = struct.pack(
            "<4sIBBHBBH",
            b"PLGC",
            plgc_block_len,
            self.cell_width,
            self.height,
            cell_size,
            0,
            0,
            0,
        )
        plgc_block = plgc_header + bytes(glyph_data)

        # Build CWDH (Character widths) - 16 byte header
        cwdh_entries = bytearray()
        for c in range(first_code, last_code + 1):
            if c in self.glyphs:
                cwdh_entries.extend([0, self.glyphs[c].advance, self.glyphs[c].advance])
            else:
                cwdh_entries.extend([0, self.cell_width, self.cell_width])

        cwdh_block_len = 16 + len(cwdh_entries)
        pad = (4 - (cwdh_block_len % 4)) % 4
        cwdh_block_len += pad
        cwdh_header = struct.pack("<4sIHHI", b"CWDH", cwdh_block_len, first_code, last_code, 0)
        cwdh_block = cwdh_header + bytes(cwdh_entries) + (b"\x00" * pad)

        # Build CMAP (Table mapping) - 20 byte header
        cmap_entries = bytearray()
        for c in range(first_code, last_code + 1):
            if c in code_to_idx:
                cmap_entries.extend(struct.pack("<H", code_to_idx[c]))
            else:
                cmap_entries.extend(struct.pack("<H", 0xFFFF))

        cmap_block_len = 20 + len(cmap_entries)
        pad = (4 - (cmap_block_len % 4)) % 4
        cmap_block_len += pad
        cmap_header = struct.pack("<4sIHHII", b"CMAP", cmap_block_len, first_code, last_code, 1, 0)
        cmap_block = cmap_header + bytes(cmap_entries) + (b"\x00" * pad)

        # Build FNTH
        fnth_block_len = 16
        fnth_block = struct.pack(
            "<4sIBBBBBHB",
            b"FNTH",
            fnth_block_len,
            0,
            self.height,
            0,
            self.cell_width,
            self.bpp,
            0,
            0,
        )

        # File header (16 bytes)
        total_file_len = 16 + len(fnth_block) + len(plgc_block) + len(cwdh_block) + len(cmap_block)
        header = struct.pack(
            "<4sHHIHH",
            self.MAGIC,
            0xFEFF,  # Endian BOM
            0x0102,  # Version
            total_file_len,
            16,      # Header size
            4,       # Block count
        )

        return header + fnth_block + plgc_block + cwdh_block + cmap_block
