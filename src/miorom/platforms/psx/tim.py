import struct
from typing import List, Optional, Tuple
from miorom.graphics.palette import Color, Palette


class TIMImage:
    """
    PlayStation 1 (PSX) TIM Texture Image parser and builder.
    Supports 4bpp, 8bpp indexed (with CLUT) and 16bpp/24bpp direct color.
    """

    MAGIC = 0x10

    def __init__(self, data: bytes):
        if len(data) < 8:
            raise ValueError("Data too small for TIM header.")

        magic, flag = struct.unpack_from("<II", data, 0)
        if magic != self.MAGIC:
            raise ValueError(f"Invalid TIM magic: {hex(magic)} (expected 0x10)")

        self.bpp_mode = flag & 0x07
        self.bpp = {0: 4, 1: 8, 2: 16, 3: 24}.get(self.bpp_mode, 16)
        self.has_clut = bool(flag & 0x08)

        pos = 8
        self.clut_palettes: List[Palette] = []
        self.clut_dx = 0
        self.clut_dy = 0

        if self.has_clut:
            clut_size, self.clut_dx, self.clut_dy, clut_w, clut_h = struct.unpack_from(
                "<IHHHH", data, pos
            )
            color_bytes = data[pos + 12 : pos + clut_size]
            pos += clut_size

            # Each palette has clut_w colors (2 bytes each)
            for pal_i in range(clut_h):
                pal_colors = []
                for col_i in range(clut_w):
                    c_off = (pal_i * clut_w + col_i) * 2
                    if c_off + 2 <= len(color_bytes):
                        c16 = struct.unpack_from("<H", color_bytes, c_off)[0]
                        # BGR555 + STP bit
                        pal_colors.append(Color.from_bgr555(c16 & 0x7FFF))
                self.clut_palettes.append(Palette(pal_colors))

        # Image section
        img_size, self.img_dx, self.img_dy, self.img_w_words, self.height = struct.unpack_from(
            "<IHHHH", data, pos
        )
        self.pixel_data = bytearray(data[pos + 12 : pos + img_size])

        # Calculate pixel width
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

        out = bytearray()
        out.extend(struct.pack("<II", self.MAGIC, flag))

        if self.has_clut:
            clut_h = len(self.clut_palettes)
            clut_w = len(self.clut_palettes[0]) if clut_h > 0 else 0
            clut_colors_len = clut_w * clut_h * 2
            clut_total_size = 12 + clut_colors_len

            out.extend(
                struct.pack(
                    "<IHHHH",
                    clut_total_size,
                    self.clut_dx,
                    self.clut_dy,
                    clut_w,
                    clut_h,
                )
            )
            for pal in self.clut_palettes:
                for col in pal.colors:
                    out.extend(struct.pack("<H", col.to_bgr555()))

        # Image block
        img_total_size = 12 + len(self.pixel_data)
        out.extend(
            struct.pack(
                "<IHHHH",
                img_total_size,
                self.img_dx,
                self.img_dy,
                self.img_w_words,
                self.height,
            )
        )
        out.extend(self.pixel_data)
        return bytes(out)
