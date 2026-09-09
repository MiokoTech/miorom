from miorom.errors import ParseError
from miorom.core.schema import BinaryStruct, U16, U32
from typing import List, Optional, Tuple
from miorom.graphics.palette import Color, Palette


class TIMHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = U32()
    flag = U32()


class TIMSectionHeaderStruct(BinaryStruct):
    _endian = "<"
    size = U32()
    dx = U16()
    dy = U16()
    width = U16()
    height = U16()


class TIMColorStruct(BinaryStruct):
    _endian = "<"
    value = U16()


class TIMImage:
    """
    PlayStation 1 (PSX) TIM Texture Image parser and builder.
    Supports 4bpp, 8bpp indexed (with CLUT) and 16bpp/24bpp direct color.
    """

    MAGIC = 0x10

    def __init__(self, data: bytes):
        if len(data) < TIMHeaderStruct.sizeof():
            raise ParseError("Data too small for TIM header.")

        header = TIMHeaderStruct.from_bytes(data, offset=0)
        if header.magic != self.MAGIC:
            raise ParseError(f"Invalid TIM magic: {hex(header.magic)} (expected 0x10)")

        flag = header.flag
        self.bpp_mode = flag & 0x07
        self.bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(self.bpp_mode, 16)
        self.has_clut = bool(flag & 0x08)

        pos = TIMHeaderStruct.sizeof()
        self.clut_palettes: List[Palette] = []
        self.clut_dx = 0
        self.clut_dy = 0

        if self.has_clut:
            clut_header = TIMSectionHeaderStruct.from_bytes(data, offset=pos)
            clut_size = clut_header.size
            self.clut_dx = clut_header.dx
            self.clut_dy = clut_header.dy
            clut_w = clut_header.width
            clut_h = clut_header.height
            color_bytes = data[pos + TIMSectionHeaderStruct.sizeof() : pos + clut_size]
            pos += clut_size

            for pal_i in range(clut_h):
                pal_colors = []
                for col_i in range(clut_w):
                    c_off = (pal_i * clut_w + col_i) * TIMColorStruct.sizeof()
                    if c_off + TIMColorStruct.sizeof() <= len(color_bytes):
                        c16 = TIMColorStruct.from_bytes(color_bytes, offset=c_off).value
                        pal_colors.append(Color.from_bgr555(c16 & 0x7FFF))
                self.clut_palettes.append(Palette(pal_colors))

        img_header = TIMSectionHeaderStruct.from_bytes(data, offset=pos)
        img_size = img_header.size
        self.img_dx = img_header.dx
        self.img_dy = img_header.dy
        self.img_w_words = img_header.width
        self.height = img_header.height
        self.pixel_data = bytearray(
            data[pos + TIMSectionHeaderStruct.sizeof() : pos + img_size]
        )

        if self.bpp == 4:
            self.width = self.img_w_words * 4
        elif self.bpp == 8:
            self.width = self.img_w_words * 2
        elif self.bpp == 16:
            self.width = self.img_w_words
        elif self.bpp == 24:
            self.width = (self.img_w_words * 2) // 3
        else:
            self.width = self.img_w_words

    @property
    def palette(self) -> Optional[Palette]:
        """Returns the primary (first) palette if available."""
        return self.clut_palettes[0] if self.clut_palettes else None

    def to_bytes(self) -> bytes:
        flag = self.bpp_mode
        if self.has_clut:
            flag |= 0x08

        out = bytearray(TIMHeaderStruct(magic=self.MAGIC, flag=flag).to_bytes())

        if self.has_clut:
            clut_h = len(self.clut_palettes)
            clut_w = len(self.clut_palettes[0]) if clut_h > 0 else 0
            clut_colors_len = clut_w * clut_h * TIMColorStruct.sizeof()
            clut_total_size = TIMSectionHeaderStruct.sizeof() + clut_colors_len

            out.extend(
                TIMSectionHeaderStruct(
                    size=clut_total_size,
                    dx=self.clut_dx,
                    dy=self.clut_dy,
                    width=clut_w,
                    height=clut_h,
                ).to_bytes()
            )
            for pal in self.clut_palettes:
                for col in pal.colors:
                    out.extend(TIMColorStruct(value=col.to_bgr555()).to_bytes())

        img_total_size = TIMSectionHeaderStruct.sizeof() + len(self.pixel_data)
        out.extend(
            TIMSectionHeaderStruct(
                size=img_total_size,
                dx=self.img_dx,
                dy=self.img_dy,
                width=self.img_w_words,
                height=self.height,
            ).to_bytes()
        )
        out.extend(self.pixel_data)
        return bytes(out)
