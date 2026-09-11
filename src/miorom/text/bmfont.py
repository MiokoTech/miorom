"""
miorom.text.bmfont
~~~~~~~~~~~~~~~~~~
BMFont (AngelCode) Font Exporter and Importer.
Supports Text and XML .fnt formats, automated glyph atlas shelf packing,
bidirectional conversion with BitmapFont, and built-in pure Python PNG encoding/decoding.
"""

from __future__ import annotations

import re
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.result import MioRomResult
from miorom.errors import ParseError
from miorom.text.font_builder import BitmapFont, Glyph


# ---------------------------------------------------------------------------
# Pure Python Minimal PNG Codec (Stdlib zlib & struct only)
# ---------------------------------------------------------------------------

class PNGCodec:
    """Pure Python minimal PNG encoder and decoder using only standard library."""

    PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

    @classmethod
    def _make_chunk(cls, chunk_type: bytes, data: bytes) -> bytes:
        length = len(data)
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", length) + chunk_type + data + struct.pack(">I", crc)

    @classmethod
    def encode_grayscale(cls, width: int, height: int, pixels: bytes) -> bytes:
        """Encodes an 8-bit grayscale pixel buffer (row-major) into valid PNG bytes."""
        if len(pixels) != width * height:
            raise ValueError(f"Pixel buffer size ({len(pixels)}) does not match {width}x{height}")

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        chunks = [cls.PNG_SIGNATURE, cls._make_chunk(b"IHDR", ihdr)]

        raw_scanlines = bytearray()
        for y in range(height):
            raw_scanlines.append(0)  # Filter type 0 (None)
            row = pixels[y * width : (y + 1) * width]
            raw_scanlines.extend(row)

        compressed = zlib.compress(bytes(raw_scanlines), level=6)
        chunks.append(cls._make_chunk(b"IDAT", compressed))
        chunks.append(cls._make_chunk(b"IEND", b""))
        return b"".join(chunks)

    @classmethod
    def encode_rgba(cls, width: int, height: int, pixels: bytes) -> bytes:
        """Encodes an 8-bit RGBA pixel buffer (row-major, 4 bytes/pixel) into valid PNG bytes."""
        if len(pixels) != width * height * 4:
            raise ValueError(f"Pixel buffer size ({len(pixels)}) does not match {width}x{height}x4")

        ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
        chunks = [cls.PNG_SIGNATURE, cls._make_chunk(b"IHDR", ihdr)]

        raw_scanlines = bytearray()
        row_len = width * 4
        for y in range(height):
            raw_scanlines.append(0)  # Filter type 0 (None)
            row = pixels[y * row_len : (y + 1) * row_len]
            raw_scanlines.extend(row)

        compressed = zlib.compress(bytes(raw_scanlines), level=6)
        chunks.append(cls._make_chunk(b"IDAT", compressed))
        chunks.append(cls._make_chunk(b"IEND", b""))
        return b"".join(chunks)

    @classmethod
    def decode(cls, png_data: bytes) -> Tuple[int, int, bytes, int]:
        """
        Decodes a basic PNG stream.
        Returns (width, height, uncompressed_pixel_bytes, color_type).
        """
        if not png_data.startswith(cls.PNG_SIGNATURE):
            raise ParseError("Invalid PNG signature")

        offset = 8
        width = 0
        height = 0
        bit_depth = 8
        color_type = 0
        idat_parts = []

        while offset < len(png_data):
            length = struct.unpack_from(">I", png_data, offset)[0]
            chunk_type = png_data[offset + 4 : offset + 8]
            data = png_data[offset + 8 : offset + 8 + length]
            offset += 12 + length

            if chunk_type == b"IHDR":
                width, height, bit_depth, color_type = struct.unpack(">IIBB", data[:10])
            elif chunk_type == b"IDAT":
                idat_parts.append(data)
            elif chunk_type == b"IEND":
                break

        if not idat_parts or width == 0 or height == 0:
            raise ParseError("PNG contains no valid image data")

        decompressed = zlib.decompress(b"".join(idat_parts))
        bpp = 1 if color_type == 0 else (4 if color_type == 6 else (3 if color_type == 2 else 1))
        row_bytes = width * bpp
        stride = 1 + row_bytes

        out_pixels = bytearray(height * row_bytes)
        prev_row = bytearray(row_bytes)

        for y in range(height):
            line = decompressed[y * stride : (y + 1) * stride]
            filter_type = line[0]
            curr_row = bytearray(line[1:])

            if filter_type == 1:  # Sub
                for x in range(bpp, row_bytes):
                    curr_row[x] = (curr_row[x] + curr_row[x - bpp]) & 0xFF
            elif filter_type == 2:  # Up
                for x in range(row_bytes):
                    curr_row[x] = (curr_row[x] + prev_row[x]) & 0xFF
            elif filter_type == 3:  # Average
                for x in range(row_bytes):
                    a = curr_row[x - bpp] if x >= bpp else 0
                    b = prev_row[x]
                    curr_row[x] = (curr_row[x] + ((a + b) // 2)) & 0xFF
            elif filter_type == 4:  # Paeth
                for x in range(row_bytes):
                    a = curr_row[x - bpp] if x >= bpp else 0
                    b = prev_row[x]
                    c = prev_row[x - bpp] if x >= bpp else 0
                    p = a + b - c
                    pa = abs(p - a)
                    pb = abs(p - b)
                    pc = abs(p - c)
                    pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                    curr_row[x] = (curr_row[x] + pr) & 0xFF

            out_pixels[y * row_bytes : (y + 1) * row_bytes] = curr_row
            prev_row = curr_row

        return width, height, bytes(out_pixels), color_type


# ---------------------------------------------------------------------------
# BMFont Data Structures
# ---------------------------------------------------------------------------

@dataclass
class BMFontInfo(MioRomResult):
    face: str = "Font"
    size: int = 12
    bold: int = 0
    italic: int = 0
    charset: str = ""
    unicode: int = 1
    stretch_h: int = 100
    smooth: int = 1
    aa: int = 1
    padding: Tuple[int, int, int, int] = (0, 0, 0, 0)
    spacing: Tuple[int, int] = (0, 0)
    outline: int = 0


@dataclass
class BMFontCommon(MioRomResult):
    line_height: int = 12
    base: int = 10
    scale_w: int = 256
    scale_h: int = 256
    pages: int = 1
    packed: int = 0
    alpha_chnl: int = 0
    red_chnl: int = 0
    green_chnl: int = 0
    blue_chnl: int = 0


@dataclass
class BMFontPage(MioRomResult):
    id: int = 0
    file: str = "font_0.png"


@dataclass
class BMFontChar(MioRomResult):
    id: int
    x: int
    y: int
    width: int
    height: int
    xoffset: int = 0
    yoffset: int = 0
    xadvance: int = 8
    page: int = 0
    chnl: int = 15
    letter: str = ""


@dataclass
class BMFontKerning(MioRomResult):
    first: int
    second: int
    amount: int


class BMFont(MioRomResult):
    """
    Complete AngelCode BMFont description and atlas bridge.
    Supports reading and writing both Text and XML formats.
    """

    def __init__(
        self,
        info: Optional[BMFontInfo] = None,
        common: Optional[BMFontCommon] = None,
        pages: Optional[Dict[int, BMFontPage]] = None,
        chars: Optional[Dict[int, BMFontChar]] = None,
        kernings: Optional[List[BMFontKerning]] = None,
    ):
        self.info = info or BMFontInfo()
        self.common = common or BMFontCommon()
        self.pages: Dict[int, BMFontPage] = pages or {0: BMFontPage(0, "font_0.png")}
        self.chars: Dict[int, BMFontChar] = chars or {}
        self.kernings: List[BMFontKerning] = kernings or []

    # -----------------------------------------------------------------------
    # Text Format Serialization
    # -----------------------------------------------------------------------

    @classmethod
    def from_text(cls, text: str) -> "BMFont":
        """Parses AngelCode BMFont text (.fnt) format."""
        font = cls()
        font.chars.clear()
        font.pages.clear()
        font.kernings.clear()

        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue

            tag, *parts = line.split(" ", 1)
            params = cls._parse_key_value_pairs(parts[0] if parts else "")

            if tag == "info":
                paddings = tuple(map(int, params.get("padding", "0,0,0,0").split(",")))
                spacings = tuple(map(int, params.get("spacing", "0,0").split(",")))
                font.info = BMFontInfo(
                    face=params.get("face", "Font"),
                    size=int(params.get("size", 12)),
                    bold=int(params.get("bold", 0)),
                    italic=int(params.get("italic", 0)),
                    charset=params.get("charset", ""),
                    unicode=int(params.get("unicode", 1)),
                    stretch_h=int(params.get("stretchH", 100)),
                    smooth=int(params.get("smooth", 1)),
                    aa=int(params.get("aa", 1)),
                    padding=(paddings[0], paddings[1], paddings[2], paddings[3]),
                    spacing=(spacings[0], spacings[1]),
                    outline=int(params.get("outline", 0)),
                )

            elif tag == "common":
                font.common = BMFontCommon(
                    line_height=int(params.get("lineHeight", 12)),
                    base=int(params.get("base", 10)),
                    scale_w=int(params.get("scaleW", 256)),
                    scale_h=int(params.get("scaleH", 256)),
                    pages=int(params.get("pages", 1)),
                    packed=int(params.get("packed", 0)),
                )

            elif tag == "page":
                page_id = int(params.get("id", 0))
                font.pages[page_id] = BMFontPage(id=page_id, file=params.get("file", f"font_{page_id}.png"))

            elif tag == "char":
                char_id = int(params.get("id", 0))
                letter_val = params.get("letter", "")
                if not letter_val and 0 <= char_id <= 0x10FFFF:
                    try:
                        letter_val = chr(char_id)
                    except Exception:
                        pass

                font.chars[char_id] = BMFontChar(
                    id=char_id,
                    x=int(params.get("x", 0)),
                    y=int(params.get("y", 0)),
                    width=int(params.get("width", 0)),
                    height=int(params.get("height", 0)),
                    xoffset=int(params.get("xoffset", 0)),
                    yoffset=int(params.get("yoffset", 0)),
                    xadvance=int(params.get("xadvance", 0)),
                    page=int(params.get("page", 0)),
                    chnl=int(params.get("chnl", 15)),
                    letter=letter_val,
                )

            elif tag == "kerning":
                font.kernings.append(
                    BMFontKerning(
                        first=int(params.get("first", 0)),
                        second=int(params.get("second", 0)),
                        amount=int(params.get("amount", 0)),
                    )
                )

        return font

    def to_text(self) -> str:
        """Serializes BMFont into AngelCode text format."""
        lines = []
        pad_str = ",".join(map(str, self.info.padding))
        space_str = ",".join(map(str, self.info.spacing))
        lines.append(
            f'info face="{self.info.face}" size={self.info.size} bold={self.info.bold} italic={self.info.italic} '
            f'charset="{self.info.charset}" unicode={self.info.unicode} stretchH={self.info.stretch_h} '
            f'smooth={self.info.smooth} aa={self.info.aa} padding={pad_str} spacing={space_str} outline={self.info.outline}'
        )
        lines.append(
            f"common lineHeight={self.common.line_height} base={self.common.base} "
            f"scaleW={self.common.scale_w} scaleH={self.common.scale_h} pages={len(self.pages)} "
            f"packed={self.common.packed} alphaChnl={self.common.alpha_chnl} redChnl={self.common.red_chnl} "
            f"greenChnl={self.common.green_chnl} blueChnl={self.common.blue_chnl}"
        )
        for p in self.pages.values():
            lines.append(f'page id={p.id} file="{p.file}"')

        lines.append(f"chars count={len(self.chars)}")
        for c in sorted(self.chars.values(), key=lambda ch: ch.id):
            let_str = f' letter="{c.letter}"' if c.letter else ""
            lines.append(
                f"char id={c.id:<4} x={c.x:<5} y={c.y:<5} width={c.width:<4} height={c.height:<4} "
                f"xoffset={c.xoffset:<4} yoffset={c.yoffset:<4} xadvance={c.xadvance:<4} page={c.page:<2} chnl={c.chnl:<2}{let_str}"
            )

        if self.kernings:
            lines.append(f"kernings count={len(self.kernings)}")
            for k in self.kernings:
                lines.append(f"kerning first={k.first:<4} second={k.second:<4} amount={k.amount}")

        return "\n".join(lines) + "\n"

    # -----------------------------------------------------------------------
    # XML Format Serialization
    # -----------------------------------------------------------------------

    @classmethod
    def from_xml(cls, xml_str: str) -> "BMFont":
        """Parses AngelCode BMFont XML (.fnt) format."""
        root = ET.fromstring(xml_str)
        font = cls()
        font.chars.clear()
        font.pages.clear()
        font.kernings.clear()

        info_elem = root.find("info")
        if info_elem is not None:
            paddings = tuple(map(int, info_elem.attrib.get("padding", "0,0,0,0").split(",")))
            spacings = tuple(map(int, info_elem.attrib.get("spacing", "0,0").split(",")))
            font.info = BMFontInfo(
                face=info_elem.attrib.get("face", "Font"),
                size=int(info_elem.attrib.get("size", 12)),
                bold=int(info_elem.attrib.get("bold", 0)),
                italic=int(info_elem.attrib.get("italic", 0)),
                charset=info_elem.attrib.get("charset", ""),
                unicode=int(info_elem.attrib.get("unicode", 1)),
                stretch_h=int(info_elem.attrib.get("stretchH", 100)),
                smooth=int(info_elem.attrib.get("smooth", 1)),
                aa=int(info_elem.attrib.get("aa", 1)),
                padding=(paddings[0], paddings[1], paddings[2], paddings[3]),
                spacing=(spacings[0], spacings[1]),
                outline=int(info_elem.attrib.get("outline", 0)),
            )

        common_elem = root.find("common")
        if common_elem is not None:
            font.common = BMFontCommon(
                line_height=int(common_elem.attrib.get("lineHeight", 12)),
                base=int(common_elem.attrib.get("base", 10)),
                scale_w=int(common_elem.attrib.get("scaleW", 256)),
                scale_h=int(common_elem.attrib.get("scaleH", 256)),
                pages=int(common_elem.attrib.get("pages", 1)),
                packed=int(common_elem.attrib.get("packed", 0)),
            )

        pages_elem = root.find("pages")
        if pages_elem is not None:
            for p in pages_elem.findall("page"):
                pid = int(p.attrib.get("id", 0))
                font.pages[pid] = BMFontPage(id=pid, file=p.attrib.get("file", f"font_{pid}.png"))

        chars_elem = root.find("chars")
        if chars_elem is not None:
            for c in chars_elem.findall("char"):
                cid = int(c.attrib.get("id", 0))
                letter = c.attrib.get("letter", "")
                if not letter and 0 <= cid <= 0x10FFFF:
                    try:
                        letter = chr(cid)
                    except Exception:
                        pass
                font.chars[cid] = BMFontChar(
                    id=cid,
                    x=int(c.attrib.get("x", 0)),
                    y=int(c.attrib.get("y", 0)),
                    width=int(c.attrib.get("width", 0)),
                    height=int(c.attrib.get("height", 0)),
                    xoffset=int(c.attrib.get("xoffset", 0)),
                    yoffset=int(c.attrib.get("yoffset", 0)),
                    xadvance=int(c.attrib.get("xadvance", 0)),
                    page=int(c.attrib.get("page", 0)),
                    chnl=int(c.attrib.get("chnl", 15)),
                    letter=letter,
                )

        kernings_elem = root.find("kernings")
        if kernings_elem is not None:
            for k in kernings_elem.findall("kerning"):
                font.kernings.append(
                    BMFontKerning(
                        first=int(k.attrib.get("first", 0)),
                        second=int(k.attrib.get("second", 0)),
                        amount=int(k.attrib.get("amount", 0)),
                    )
                )

        return font

    def to_xml(self) -> str:
        """Serializes BMFont into XML format."""
        root = ET.Element("font")
        pad_str = ",".join(map(str, self.info.padding))
        space_str = ",".join(map(str, self.info.spacing))

        ET.SubElement(
            root,
            "info",
            face=self.info.face,
            size=str(self.info.size),
            bold=str(self.info.bold),
            italic=str(self.info.italic),
            charset=self.info.charset,
            unicode=str(self.info.unicode),
            stretchH=str(self.info.stretch_h),
            smooth=str(self.info.smooth),
            aa=str(self.info.aa),
            padding=pad_str,
            spacing=space_str,
            outline=str(self.info.outline),
        )

        ET.SubElement(
            root,
            "common",
            lineHeight=str(self.common.line_height),
            base=str(self.common.base),
            scaleW=str(self.common.scale_w),
            scaleH=str(self.common.scale_h),
            pages=str(len(self.pages)),
            packed=str(self.common.packed),
        )

        pages_elem = ET.SubElement(root, "pages")
        for p in self.pages.values():
            ET.SubElement(pages_elem, "page", id=str(p.id), file=p.file)

        chars_elem = ET.SubElement(root, "chars", count=str(len(self.chars)))
        for c in sorted(self.chars.values(), key=lambda ch: ch.id):
            attribs = {
                "id": str(c.id),
                "x": str(c.x),
                "y": str(c.y),
                "width": str(c.width),
                "height": str(c.height),
                "xoffset": str(c.xoffset),
                "yoffset": str(c.yoffset),
                "xadvance": str(c.xadvance),
                "page": str(c.page),
                "chnl": str(c.chnl),
            }
            if c.letter:
                attribs["letter"] = c.letter
            ET.SubElement(chars_elem, "char", **attribs)

        if self.kernings:
            kernings_elem = ET.SubElement(root, "kernings", count=str(len(self.kernings)))
            for k in self.kernings:
                ET.SubElement(
                    kernings_elem,
                    "kerning",
                    first=str(k.first),
                    second=str(k.second),
                    amount=str(k.amount),
                )

        return ET.tostring(root, encoding="utf-8").decode("utf-8")

    # -----------------------------------------------------------------------
    # BitmapFont Interoperability & Atlas Packing
    # -----------------------------------------------------------------------

    @classmethod
    def from_bitmap_font(
        cls,
        bm_font: BitmapFont,
        page_file: str = "font_0.png",
        texture_width: int = 256,
        texture_height: int = 256,
        padding: int = 1,
    ) -> Tuple["BMFont", bytes, bytes]:
        """
        Packs a BitmapFont into a 2D atlas texture sheet.
        Returns:
            (BMFont descriptor, raw_grayscale_bytes, png_bytes)
        """
        atlas = bytearray(texture_width * texture_height)
        font = cls()
        font.common.scale_w = texture_width
        font.common.scale_h = texture_height
        font.common.line_height = bm_font.default_height
        font.pages = {0: BMFontPage(0, page_file)}

        curr_x = padding
        curr_y = padding
        row_height = 0

        for char, glyph in sorted(bm_font.glyphs.items(), key=lambda item: ord(item[0])):
            cid = ord(char)
            gw = glyph.width
            gh = glyph.height

            # Wrap to next row if needed
            if curr_x + gw + padding > texture_width:
                curr_x = padding
                curr_y += row_height + padding
                row_height = 0

            if curr_y + gh + padding > texture_height:
                # Texture filled, clamp
                break

            # Copy pixels into atlas
            for gy in range(gh):
                for gx in range(gw):
                    px = glyph.get_pixel(gx, gy)
                    atlas[(curr_y + gy) * texture_width + (curr_x + gx)] = px

            font.chars[cid] = BMFontChar(
                id=cid,
                x=curr_x,
                y=curr_y,
                width=gw,
                height=gh,
                xoffset=0,
                yoffset=0,
                xadvance=glyph.advance,
                page=0,
                letter=char,
            )

            curr_x += gw + padding
            if gh > row_height:
                row_height = gh

        raw_bytes = bytes(atlas)
        png_bytes = PNGCodec.encode_grayscale(texture_width, texture_height, raw_bytes)
        return font, raw_bytes, png_bytes

    def to_bitmap_font(
        self,
        atlas_pixels: Optional[bytes] = None,
        atlas_width: Optional[int] = None,
    ) -> BitmapFont:
        """
        Reconstructs a BitmapFont from this BMFont descriptor and optional atlas pixels.
        """
        bm = BitmapFont(
            default_height=self.common.line_height,
            default_advance=self.chars[next(iter(self.chars))].xadvance if self.chars else 8,
        )
        aw = atlas_width or self.common.scale_w

        for ch in self.chars.values():
            char_symbol = ch.letter if ch.letter else chr(ch.id)
            bitmap: List[int] = []

            if atlas_pixels is not None and ch.width > 0 and ch.height > 0:
                for gy in range(ch.height):
                    row_off = (ch.y + gy) * aw + ch.x
                    for gx in range(ch.width):
                        idx = row_off + gx
                        val = atlas_pixels[idx] if idx < len(atlas_pixels) else 0
                        bitmap.append(val)
            else:
                bitmap = [255] * (ch.width * ch.height)

            bm.add_glyph(
                char=char_symbol,
                width=ch.width,
                height=ch.height,
                advance=ch.xadvance,
                bitmap=bitmap,
            )

        return bm

    @staticmethod
    def _parse_key_value_pairs(text: str) -> Dict[str, str]:
        """Parses key=value or key="value" pairs from a single BMFont line."""
        res = {}
        matches = re.findall(r'(\w+)=(?:"([^"]*)"|([^\s]+))', text)
        for k, v_quoted, v_unquoted in matches:
            res[k] = v_quoted if v_quoted != "" else v_unquoted
        return res
