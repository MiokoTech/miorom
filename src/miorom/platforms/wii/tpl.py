from miorom.result import MioRomResult
import os
from miorom.errors import ParseError
from dataclasses import dataclass, field
from miorom.core.schema import BinaryStruct, U32, U16
from typing import List, Optional, Tuple, Dict, Any


TPL_FORMAT_NAMES = {
    0: "I4",
    1: "I8",
    2: "IA4",
    3: "IA8",
    4: "RGB565",
    5: "RGB5A3",
    6: "RGBA8",
    8: "CI4",
    9: "CI8",
    10: "CI14X2",
    14: "CMPR",  # S3TC / DXT1
}


class TPLHeaderStruct(BinaryStruct):
    _endian = ">"
    magic = U32()
    num_images = U32()
    table_offset = U32()


class TPLImageTableEntryStruct(BinaryStruct):
    _endian = ">"
    image_header_offset = U32()
    palette_header_offset = U32()


class TPLImageHeaderStruct(BinaryStruct):
    _endian = ">"
    height = U16()
    width = U16()
    format_id = U32()
    data_offset = U32()
    wrap_s = U32()
    wrap_t = U32()
    min_filter = U32()
    mag_filter = U32()


class TPLColorStruct(BinaryStruct):
    _endian = ">"
    value = U16()


@dataclass
class TPLImage(MioRomResult):
    index: int
    width: int
    height: int
    format_id: int
    data_offset: int
    wrap_s: int = 0
    wrap_t: int = 0
    min_filter: int = 0
    mag_filter: int = 0
    palette_header_offset: int = 0
    raw_data: bytes = b""

    @property
    def format_name(self) -> str:
        return TPL_FORMAT_NAMES.get(self.format_id, f"Unknown (0x{self.format_id:X})")

    def __repr__(self) -> str:
        return (f"<TPLImage #{self.index} {self.width}x{self.height} "
                f"format={self.format_name} offset=0x{self.data_offset:06X} "
                f"({len(self.raw_data)} bytes)>")


class TPLFile:
    """
    Nintendo TPL (Texture Palette Library) reader and inspector.
    Standard texture image container used in Nintendo GameCube and Wii games.
    """

    MAGIC = 0x0020AF30

    def __init__(self, images: Optional[List[TPLImage]] = None):
        self.images: List[TPLImage] = images or []

    @classmethod
    def from_file(cls, filepath: str) -> "TPLFile":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "TPLFile":
        if len(data) < TPLHeaderStruct.sizeof():
            raise ParseError("Data too short for TPL header.")

        header = TPLHeaderStruct.from_bytes(data, offset=0)
        if header.magic != cls.MAGIC:
            raise ParseError(f"Invalid TPL magic: expected 0x0020AF30, got {hex(header.magic)}")

        images: List[TPLImage] = []

        for i in range(header.num_images):
            entry_offset = header.table_offset + i * TPLImageTableEntryStruct.sizeof()
            entry = TPLImageTableEntryStruct.from_bytes(data, offset=entry_offset)

            if entry.image_header_offset == 0:
                continue

            # Read 36-byte Image Header
            image_header = TPLImageHeaderStruct.from_bytes(data, offset=entry.image_header_offset)

            # Calculate raw texture data size
            data_size = cls._calculate_texture_size(
                image_header.width,
                image_header.height,
                image_header.format_id,
            )
            data_offset = image_header.data_offset
            raw_bytes = data[data_offset:data_offset + data_size] if data_offset + data_size <= len(data) else data[data_offset:]

            images.append(TPLImage(
                index=i,
                width=image_header.width,
                height=image_header.height,
                format_id=image_header.format_id,
                data_offset=image_header.data_offset,
                wrap_s=image_header.wrap_s,
                wrap_t=image_header.wrap_t,
                min_filter=image_header.min_filter,
                mag_filter=image_header.mag_filter,
                palette_header_offset=entry.palette_header_offset,
                raw_data=raw_bytes
            ))

        return cls(images)

    @classmethod
    def _calculate_texture_size(cls, width: int, height: int, format_id: int) -> int:
        # Tile dimensions based on format
        if format_id in (0, 8):  # I4, CI4 (8x8 tiles, 4 bpp = 32 bytes/tile)
            bw = (width + 7) // 8
            bh = (height + 7) // 8
            return bw * bh * 32
        elif format_id in (1, 2, 9):  # I8, IA4, CI8 (8x4 tiles, 8 bpp = 32 bytes/tile)
            bw = (width + 7) // 8
            bh = (height + 3) // 4
            return bw * bh * 32
        elif format_id in (3, 4, 5, 10):  # IA8, RGB565, RGB5A3, CI14X2 (4x4 tiles, 16 bpp = 32 bytes/tile)
            bw = (width + 3) // 4
            bh = (height + 3) // 4
            return bw * bh * 32
        elif format_id == 6:  # RGBA8 (4x4 tiles, 32 bpp = 64 bytes/tile, split AR/GB)
            bw = (width + 3) // 4
            bh = (height + 3) // 4
            return bw * bh * 64
        elif format_id == 14:  # CMPR (8x8 tile = four 4x4 DXT1 blocks = 32 bytes/tile)
            bw = (width + 7) // 8
            bh = (height + 7) // 8
            return bw * bh * 32
        else:
            return width * height * 4

    def decode_rgba(self, image_index: int = 0) -> bytes:
        """
        Decodes the specified texture image into linear uncompressed RGBA8888 byte stream.
        Supports standard formats: RGB5A3, RGB565, RGBA8, IA8, I8.
        """
        if image_index >= len(self.images):
            raise IndexError(f"Image index {image_index} out of range.")

        img = self.images[image_index]
        w, h, fmt = img.width, img.height, img.format_id
        raw = img.raw_data

        rgba_pixels = bytearray(w * h * 4)

        if fmt == 5:  # RGB5A3
            # 4x4 tiles
            tiles_x = (w + 3) // 4
            tiles_y = (h + 3) // 4
            in_pos = 0

            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    for py in range(4):
                        for px in range(4):
                            x = tx * 4 + px
                            y = ty * 4 + py
                            if in_pos + 2 <= len(raw) and x < w and y < h:
                                val = TPLColorStruct.from_bytes(raw, offset=in_pos).value
                                if (val & 0x8000):
                                    # RGB555 format (no alpha)
                                    r = ((val >> 10) & 0x1F) * 255 // 31
                                    g = ((val >> 5) & 0x1F) * 255 // 31
                                    b = (val & 0x1F) * 255 // 31
                                    a = 255
                                else:
                                    # ARGB3444 format (has alpha)
                                    a = ((val >> 12) & 0x07) * 255 // 7
                                    r = ((val >> 8) & 0x0F) * 255 // 15
                                    g = ((val >> 4) & 0x0F) * 255 // 15
                                    b = (val & 0x0F) * 255 // 15

                                out_idx = (y * w + x) * 4
                                rgba_pixels[out_idx] = r
                                rgba_pixels[out_idx + 1] = g
                                rgba_pixels[out_idx + 2] = b
                                rgba_pixels[out_idx + 3] = a
                            in_pos += 2

        elif fmt == 4:  # RGB565
            tiles_x = (w + 3) // 4
            tiles_y = (h + 3) // 4
            in_pos = 0

            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    for py in range(4):
                        for px in range(4):
                            x = tx * 4 + px
                            y = ty * 4 + py
                            if in_pos + 2 <= len(raw) and x < w and y < h:
                                val = TPLColorStruct.from_bytes(raw, offset=in_pos).value
                                r = ((val >> 11) & 0x1F) * 255 // 31
                                g = ((val >> 5) & 0x3F) * 255 // 63
                                b = (val & 0x1F) * 255 // 31
                                a = 255

                                out_idx = (y * w + x) * 4
                                rgba_pixels[out_idx] = r
                                rgba_pixels[out_idx + 1] = g
                                rgba_pixels[out_idx + 2] = b
                                rgba_pixels[out_idx + 3] = a
                            in_pos += 2

        elif fmt == 1:  # I8
            tiles_x = (w + 7) // 8
            tiles_y = (h + 3) // 4
            in_pos = 0

            for ty in range(tiles_y):
                for tx in range(tiles_x):
                    for py in range(4):
                        for px in range(8):
                            x = tx * 8 + px
                            y = ty * 4 + py
                            if in_pos < len(raw) and x < w and y < h:
                                val = raw[in_pos]
                                out_idx = (y * w + x) * 4
                                rgba_pixels[out_idx] = val
                                rgba_pixels[out_idx + 1] = val
                                rgba_pixels[out_idx + 2] = val
                                rgba_pixels[out_idx + 3] = 255
                            in_pos += 1

        return bytes(rgba_pixels)
