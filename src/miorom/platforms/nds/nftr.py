from miorom.core.schema import BinaryStruct, RawBytes, U16, U32, U8
from miorom.errors import ParseError
from typing import Any, Dict, List, Optional, Tuple, Union
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
    null_glyph = U8()
    default_width = U8()
    encoding = U8()
    cell_width = U8()
    cell_height = U8()
    bpp = U8()
    glyph_block_offset = U32()
    width_block_offset = U32()
    map_block_offset = U32()


class NFTRGlyphCellHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)
    size = U32()
    cell_width = U8()
    cell_height = U8()
    cell_byte_size = U16()
    baseline = U8()
    max_width = U8()
    bpp = U8()
    flags = U8()


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
        left_margin: int = 0,
        tile: Optional[Tile] = None,
    ):
        self.code = code
        self.advance = advance
        self.glyph_index = glyph_index
        self.left_margin = left_margin

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


def _decode_glyph_pixels(data: bytes, width: int, height: int, bpp: int) -> List[int]:
    total = width * height
    pixels = []
    if bpp == 2:
        for b in data:
            pixels.extend([(b >> 6) & 3, (b >> 4) & 3, (b >> 2) & 3, b & 3])
    elif bpp == 1:
        for b in data:
            for s in range(7, -1, -1):
                pixels.append((b >> s) & 1)
    elif bpp == 4:
        for b in data:
            pixels.extend([(b >> 4) & 0xF, b & 0xF])
    elif bpp == 8:
        pixels.extend(data)
    else:
        bits = "".join(f"{b:08b}" for b in data)
        for idx in range(total):
            b_idx = idx * bpp
            pixels.append(int(bits[b_idx : b_idx + bpp], 2) if b_idx + bpp <= len(bits) else 0)
    return pixels[:total]


def _encode_glyph_pixels(pixels: List[int], width: int, height: int, bpp: int, cell_byte_size: int) -> bytes:
    total = width * height
    pix = list(pixels[:total])
    if len(pix) < total:
        pix.extend([0] * (total - len(pix)))
    out = bytearray()
    if bpp == 2:
        for i in range(0, total, 4):
            chunk = pix[i : i + 4]
            b = 0
            for s_idx, p in enumerate(chunk):
                b |= (p & 3) << (6 - s_idx * 2)
            out.append(b)
    elif bpp == 1:
        for i in range(0, total, 8):
            chunk = pix[i : i + 8]
            b = 0
            for s_idx, p in enumerate(chunk):
                b |= (p & 1) << (7 - s_idx)
            out.append(b)
    elif bpp == 4:
        for i in range(0, total, 2):
            chunk = pix[i : i + 2]
            b = 0
            if len(chunk) > 0:
                b |= (chunk[0] & 0xF) << 4
            if len(chunk) > 1:
                b |= (chunk[1] & 0xF)
            out.append(b)
    elif bpp == 8:
        out.extend(p & 0xFF for p in pix)
    else:
        mask = (1 << bpp) - 1
        bits = "".join(f"{p & mask:0{bpp}b}" for p in pix)
        pad = (8 - (len(bits) % 8)) % 8
        bits += "0" * pad
        out = bytearray(int(bits[i : i + 8], 2) for i in range(0, len(bits), 8))

    if len(out) < cell_byte_size:
        out += b"\x00" * (cell_byte_size - len(out))
    return bytes(out[:cell_byte_size])


class NFTRFont:
    """
    Nitro Font Resource (.nftr) parser and builder for Nintendo DS games.
    Fully compliant with Nintendo Nitro SDK NNS_G2dFont binary specification.
    """

    MAGIC = b"RTFN"

    def __init__(
        self,
        height: int = 12,
        cell_width: int = 8,
        bpp: int = 2,
        baseline: Optional[int] = None,
        max_width: Optional[int] = None,
        encoding: int = 0,
    ):
        self.height = height
        self.cell_width = cell_width
        self.bpp = bpp
        self.baseline = baseline if baseline is not None else max(1, height - 2)
        self.max_width = max_width if max_width is not None else cell_width
        self.encoding = encoding
        self.font_type = 0
        self.null_char_glyph_index = 0
        self.default_width = 0
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
                if len(block_data) > 8:
                    font.font_type = block_data[8]
                if len(block_data) > 9:
                    font.height = block_data[9]
                if len(block_data) > 10:
                    font.null_char_glyph_index = block_data[10]
                if len(block_data) > 11:
                    font.default_width = block_data[11]
                if len(block_data) > 12:
                    font.encoding = block_data[12]
                if len(block_data) > 13 and block_data[13] > 0:
                    font.cell_width = block_data[13]
                if len(block_data) > 14 and block_data[14] > 0:
                    font.cell_height = block_data[14]

            elif block_magic in (b"PLGC", b"CGLP"):
                font.cell_width = block_data[8]
                font.height = block_data[9]
                cell_byte_size = U16().unpack(block_data, 10, "<")[0]
                if len(block_data) > 12:
                    font.baseline = block_data[12]
                if len(block_data) > 13:
                    font.max_width = block_data[13]
                if len(block_data) > 14 and block_data[14] > 0:
                    font.bpp = block_data[14]

                raw_glyphs = block_data[16:]
                glyph_bitmaps = []
                if cell_byte_size > 0:
                    for gi in range(0, len(raw_glyphs) - cell_byte_size + 1, cell_byte_size):
                        glyph_bitmaps.append(raw_glyphs[gi : gi + cell_byte_size])

            elif block_magic in (b"CWDH", b"HDWC"):
                first_code = U16().unpack(block_data, 8, "<")[0]
                last_code = U16().unpack(block_data, 10, "<")[0]
                w_pos = 16
                for gi in range(first_code, last_code + 1):
                    if w_pos + 3 <= len(block_data):
                        left_m = block_data[w_pos]
                        w_val = block_data[w_pos + 1]
                        adv = block_data[w_pos + 2]
                        cwdh_table[gi] = (left_m, w_val, adv)
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

        # Assemble glyphs using fast bitwise unpack
        for code, g_idx in code_to_glyph_idx.items():
            if g_idx < len(glyph_bitmaps):
                b_data = glyph_bitmaps[g_idx]
                pixels = _decode_glyph_pixels(b_data, font.cell_width, font.height, font.bpp)
                m_info = cwdh_table.get(g_idx, cwdh_table.get(code, (0, font.cell_width, font.cell_width)))
                left_m, w_val, adv = m_info
                font.glyphs[code] = NFTRGlyph(
                    code=code,
                    tile_or_pixels=pixels,
                    advance=adv,
                    width=w_val,
                    height=font.height,
                    glyph_index=g_idx,
                    left_margin=left_m,
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
        """
        Serializes font into a standard Nintendo DS NFTR file binary.
        Generates standard 28-byte FINF header with pre-resolved relative pointers to
        CGLP (PLGC), CWDH (HDWC), and multi-block chained CMAP (PAMC) blocks.
        """
        sorted_codes = sorted(self.glyphs.keys())
        if not sorted_codes:
            sorted_codes = [0x20]
            self.glyphs[0x20] = NFTRGlyph(code=0x20, width=self.cell_width, height=self.height, advance=self.cell_width)

        code_to_idx: Dict[int, int] = {code: idx for idx, code in enumerate(sorted_codes)}
        total_pixels = self.cell_width * self.height
        cell_byte_size = (total_pixels * self.bpp + 7) // 8

        # 1. Build PLGC (Glyph cell block)
        glyph_data = bytearray()
        for code in sorted_codes:
            g = self.glyphs[code]
            glyph_data.extend(_encode_glyph_pixels(g.pixels, self.cell_width, self.height, self.bpp, cell_byte_size))

        plgc_pad = (4 - (len(glyph_data) % 4)) % 4
        plgc_block_len = 16 + len(glyph_data) + plgc_pad
        baseline = getattr(self, "baseline", max(1, self.height - 2))
        max_width = getattr(self, "max_width", self.cell_width)

        plgc_header = NFTRGlyphCellHeaderStruct(
            magic=b"PLGC",
            size=plgc_block_len,
            cell_width=self.cell_width,
            cell_height=self.height,
            cell_byte_size=cell_byte_size,
            baseline=baseline,
            max_width=max_width,
            bpp=self.bpp,
            flags=0,
        ).to_bytes()
        plgc_block = plgc_header + bytes(glyph_data) + (b"\x00" * plgc_pad)

        # 2. Build HDWC (Character widths block)
        cwdh_entries = bytearray()
        for code in sorted_codes:
            g = self.glyphs[code]
            left_m = getattr(g, "left_margin", 0)
            w_val = g.width if g.width >= 0 else self.cell_width
            adv = g.advance
            cwdh_entries.extend([left_m, w_val, adv])

        cwdh_pad = (4 - (len(cwdh_entries) % 4)) % 4
        cwdh_block_len = 16 + len(cwdh_entries) + cwdh_pad
        cwdh_header = NFTRWidthHeaderStruct(
            magic=b"HDWC",
            size=cwdh_block_len,
            first_code=0,
            last_code=len(sorted_codes) - 1,
            next_block_offset=0,
        ).to_bytes()
        cwdh_block = cwdh_header + bytes(cwdh_entries) + (b"\x00" * cwdh_pad)

        # 3. Partition characters into CMAP blocks (PAMC)
        runs: List[List[int]] = []
        cur_run: List[int] = [sorted_codes[0]]
        for c in sorted_codes[1:]:
            if c == cur_run[-1] + 1 and code_to_idx[c] == code_to_idx[cur_run[-1]] + 1:
                cur_run.append(c)
            else:
                runs.append(cur_run)
                cur_run = [c]
        runs.append(cur_run)

        type0_runs = [r for r in runs if len(r) >= 4]
        singletons: List[int] = []
        for r in runs:
            if len(r) < 4:
                singletons.extend(r)

        plgc_offset = 16 + 28  # 0x2C
        cwdh_offset = plgc_offset + plgc_block_len
        first_cmap_offset = cwdh_offset + cwdh_block_len

        cmap_blocks_info: List[Dict[str, Any]] = []
        for r in type0_runs:
            cmap_blocks_info.append({
                "type": 0,
                "first": r[0],
                "last": r[-1],
                "base": code_to_idx[r[0]],
                "size": 24,
            })

        if singletons:
            s_payload_len = 2 + len(singletons) * 4
            s_pad = (4 - (s_payload_len % 4)) % 4
            cmap_blocks_info.append({
                "type": 2,
                "first": 0,
                "last": 0xFFFF,
                "codes": [(c, code_to_idx[c]) for c in singletons],
                "size": 20 + s_payload_len + s_pad,
                "pad": s_pad,
            })

        # Calculate offsets and chain pointers for each CMAP block
        cur_off = first_cmap_offset
        cmap_offsets: List[int] = []
        for info in cmap_blocks_info:
            cmap_offsets.append(cur_off)
            cur_off += info["size"]

        cmap_blocks_data = bytearray()
        for i, info in enumerate(cmap_blocks_info):
            p_next = (cmap_offsets[i + 1] + 8) if i + 1 < len(cmap_blocks_info) else 0
            if info["type"] == 0:
                hdr = NFTRCharMapHeaderStruct(
                    magic=b"PAMC",
                    size=info["size"],
                    first_code=info["first"],
                    last_code=info["last"],
                    map_type=0,
                    next_block_offset=p_next,
                ).to_bytes()
                payload = U16().pack(info["base"], endian="<") + b"\x00\x00"
                cmap_blocks_data.extend(hdr + payload)
            elif info["type"] == 2:
                hdr = NFTRCharMapHeaderStruct(
                    magic=b"PAMC",
                    size=info["size"],
                    first_code=info["first"],
                    last_code=info["last"],
                    map_type=2,
                    next_block_offset=p_next,
                ).to_bytes()
                payload = bytearray(U16().pack(len(info["codes"]), endian="<"))
                for c, g_idx in info["codes"]:
                    payload.extend(U16().pack(c, endian="<"))
                    payload.extend(U16().pack(g_idx, endian="<"))
                payload.extend(b"\x00" * info["pad"])
                cmap_blocks_data.extend(hdr + bytes(payload))

        # 4. Build FNIF (FINF block with exact resolved pointers)
        p_glyph = plgc_offset + 8
        p_width = cwdh_offset + 8
        p_map = first_cmap_offset + 8

        fnif_header = NFTRFontHeaderStruct(
            magic=b"FNIF",
            size=28,
            font_type=getattr(self, "font_type", 0),
            height=self.height,
            null_glyph=getattr(self, "null_char_glyph_index", 0),
            default_width=getattr(self, "default_width", 0),
            encoding=getattr(self, "encoding", 0),
            cell_width=self.cell_width,
            cell_height=getattr(self, "cell_height", self.cell_width),
            bpp=0,
            glyph_block_offset=p_glyph,
            width_block_offset=p_width,
            map_block_offset=p_map,
        ).to_bytes()

        # 5. File header (16 bytes)
        total_file_len = 16 + 28 + len(plgc_block) + len(cwdh_block) + len(cmap_blocks_data)
        file_header = NFTRFileHeaderStruct(
            magic=self.MAGIC,
            byte_order_mark=0xFEFF,
            version=0x0100,
            file_size=total_file_len,
            header_size=16,
            block_count=3 + len(cmap_blocks_info),
        ).to_bytes()

        return file_header + fnif_header + plgc_block + cwdh_block + bytes(cmap_blocks_data)
