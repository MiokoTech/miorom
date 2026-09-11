from miorom.errors import ParseError
from miorom.core.schema import BinaryStruct, U16, U32
from typing import List, Optional, Tuple, Union
from miorom.graphics.palette import Color, Palette

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


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

    def __init__(self, data: Optional[bytes] = None):
        if data is None:
            self.bpp_mode = 0
            self.bpp = 4
            self.has_clut = False
            self.clut_palettes: List[Palette] = []
            self.clut_dx = 0
            self.clut_dy = 0
            self.img_dx = 0
            self.img_dy = 0
            self.img_w_words = 0
            self.height = 0
            self.width = 0
            self.pixel_data = bytearray()
            return

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
            if pos + TIMSectionHeaderStruct.sizeof() > len(data):
                raise ParseError("Data too small for TIM CLUT section header.")
            clut_header = TIMSectionHeaderStruct.from_bytes(data, offset=pos)
            clut_size = clut_header.size
            if clut_size < TIMSectionHeaderStruct.sizeof() or pos + clut_size > len(data):
                raise ParseError(f"Malformed TIM CLUT section size: {clut_size}")
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

        if pos + TIMSectionHeaderStruct.sizeof() > len(data):
            raise ParseError("Data too small for TIM image section header.")
        img_header = TIMSectionHeaderStruct.from_bytes(data, offset=pos)
        img_size = img_header.size
        if img_size < TIMSectionHeaderStruct.sizeof() or pos + img_size > len(data):
            raise ParseError(f"Malformed TIM image section size: {img_size}")
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

    @classmethod
    def from_bytes(cls, data: bytes) -> "TIMImage":
        """Parses a TIMImage from raw binary bytes."""
        return cls(data)

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, "Image.Image"],
        bpp: int = 4,
        target_palette: Optional[Palette] = None,
        img_dx: int = 0,
        img_dy: int = 0,
        clut_dx: int = 0,
        clut_dy: int = 0,
    ) -> "TIMImage":
        """
        Creates a TIMImage from a PIL Image or image file path.
        Supports bpp=4, 8, and 16.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for TIMImage.from_image().")

        if isinstance(image_or_path, str):
            img = Image.open(image_or_path)
        else:
            img = image_or_path

        img = img.convert("RGBA")
        width, height = img.size

        if bpp not in (4, 8, 16):
            raise ValueError(f"Unsupported bpp for TIM export: {bpp} (must be 4, 8, or 16)")

        tim = cls()
        tim.height = height
        tim.img_dx = img_dx
        tim.img_dy = img_dy
        tim.clut_dx = clut_dx
        tim.clut_dy = clut_dy

        if bpp == 4:
            tim.bpp_mode = 0
            tim.bpp = 4
            tim.has_clut = True
            pad_w = (4 - (width % 4)) % 4
            actual_w = width + pad_w
            tim.width = actual_w
            tim.img_w_words = actual_w // 4

            if target_palette is None:
                unique_colors: List[Color] = []
                seen = set()
                for y in range(height):
                    for x in range(width):
                        c = Color(*img.getpixel((x, y)))
                        if c not in seen and len(unique_colors) < 16:
                            seen.add(c)
                            unique_colors.append(c)
                while len(unique_colors) < 16:
                    unique_colors.append(Color(0, 0, 0, 0))
                palette = Palette(unique_colors)
            else:
                palette = target_palette

            tim.clut_palettes = [palette]

            pixel_bytes = bytearray(tim.img_w_words * 2 * height)
            stride = tim.img_w_words * 2
            for y in range(height):
                row_start = y * stride
                for x in range(0, actual_w, 2):
                    c0 = Color(*img.getpixel((x, y))) if x < width else Color(0, 0, 0, 0)
                    c1 = Color(*img.getpixel((x + 1, y))) if x + 1 < width else Color(0, 0, 0, 0)
                    idx0 = palette.match_color(c0) & 0x0F
                    idx1 = palette.match_color(c1) & 0x0F
                    pixel_bytes[row_start + (x // 2)] = idx0 | (idx1 << 4)

            tim.pixel_data = pixel_bytes

        elif bpp == 8:
            tim.bpp_mode = 1
            tim.bpp = 8
            tim.has_clut = True
            pad_w = (2 - (width % 2)) % 2
            actual_w = width + pad_w
            tim.width = actual_w
            tim.img_w_words = actual_w // 2

            if target_palette is None:
                unique_colors: List[Color] = []
                seen = set()
                for y in range(height):
                    for x in range(width):
                        c = Color(*img.getpixel((x, y)))
                        if c not in seen and len(unique_colors) < 256:
                            seen.add(c)
                            unique_colors.append(c)
                while len(unique_colors) < 256:
                    unique_colors.append(Color(0, 0, 0, 0))
                palette = Palette(unique_colors)
            else:
                palette = target_palette

            tim.clut_palettes = [palette]

            pixel_bytes = bytearray(tim.img_w_words * 2 * height)
            stride = tim.img_w_words * 2
            for y in range(height):
                row_start = y * stride
                for x in range(actual_w):
                    c = Color(*img.getpixel((x, y))) if x < width else Color(0, 0, 0, 0)
                    idx = palette.match_color(c) & 0xFF
                    pixel_bytes[row_start + x] = idx

            tim.pixel_data = pixel_bytes

        elif bpp == 16:
            tim.bpp_mode = 2
            tim.bpp = 16
            tim.has_clut = False
            tim.clut_palettes = []
            tim.width = width
            tim.img_w_words = width

            pixel_bytes = bytearray(width * 2 * height)
            for y in range(height):
                row_start = y * (width * 2)
                for x in range(width):
                    r, g, b, a = img.getpixel((x, y))
                    if a < 128:
                        val = 0
                    else:
                        c = Color(r, g, b, 255)
                        val = c.to_bgr555()
                        if val == 0:
                            val = 0x8000
                    pixel_bytes[row_start + x * 2 : row_start + x * 2 + 2] = TIMColorStruct(value=val).to_bytes()

            tim.pixel_data = pixel_bytes

        return tim

    def to_image(self, palette_index: int = 0) -> "Image.Image":
        """
        Renders the TIM image to a PIL RGBA Image.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for TIMImage.to_image().")

        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        pixels = img.load()

        if self.bpp == 4:
            pal = (
                self.clut_palettes[palette_index]
                if (self.clut_palettes and palette_index < len(self.clut_palettes))
                else None
            )
            stride = self.img_w_words * 2
            for y in range(self.height):
                row_start = y * stride
                for x in range(self.width):
                    b_off = row_start + (x // 2)
                    if b_off < len(self.pixel_data):
                        b = self.pixel_data[b_off]
                        idx = (b & 0x0F) if (x % 2 == 0) else ((b >> 4) & 0x0F)
                        if pal and idx < len(pal):
                            c = pal[idx]
                            pixels[x, y] = (c.r, c.g, c.b, c.a)
                        else:
                            pixels[x, y] = (idx * 17, idx * 17, idx * 17, 255)

        elif self.bpp == 8:
            pal = (
                self.clut_palettes[palette_index]
                if (self.clut_palettes and palette_index < len(self.clut_palettes))
                else None
            )
            stride = self.img_w_words * 2
            for y in range(self.height):
                row_start = y * stride
                for x in range(self.width):
                    b_off = row_start + x
                    if b_off < len(self.pixel_data):
                        idx = self.pixel_data[b_off]
                        if pal and idx < len(pal):
                            c = pal[idx]
                            pixels[x, y] = (c.r, c.g, c.b, c.a)
                        else:
                            pixels[x, y] = (idx, idx, idx, 255)

        elif self.bpp == 16:
            stride = self.img_w_words * 2
            for y in range(self.height):
                row_start = y * stride
                for x in range(self.width):
                    b_off = row_start + x * 2
                    if b_off + 2 <= len(self.pixel_data):
                        val = TIMColorStruct.from_bytes(self.pixel_data, offset=b_off).value
                        if val == 0:
                            pixels[x, y] = (0, 0, 0, 0)
                        else:
                            c = Color.from_bgr555(val & 0x7FFF)
                            pixels[x, y] = (c.r, c.g, c.b, 255)

        return img
