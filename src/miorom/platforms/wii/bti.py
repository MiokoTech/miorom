"""
miorom.platforms.wii.bti
~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo BTI (Binary Texture Image) Parser and Builder.
Standard standalone texture format used across Nintendo GameCube and Wii titles
(e.g., The Legend of Zelda: The Wind Waker, Super Mario Sunshine, Twilight Princess).
Pure Python, using MioROM declarative binary primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Optional, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, U8, U16, U32
from miorom.errors import ParseError
from miorom.compression.yaz0 import Yaz0
from miorom.platforms.wii.tpl import (
    TPL_FORMAT_NAMES,
    decode_gx_texture,
    encode_gx_texture,
    calc_gx_texture_size,
)

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class BTIHeaderStruct(BinaryStruct):
    _endian = ">"
    format_id = U8()             # 0x00: Texture format
    alpha_setting = U8()         # 0x01: Alpha setting
    width = U16()                # 0x02: Width in pixels
    height = U16()               # 0x04: Height in pixels
    wrap_s = U8()                # 0x06: Wrap mode S
    wrap_t = U8()                # 0x07: Wrap mode T
    palette_enabled = U8()       # 0x08: Palette enabled
    palette_format = U8()        # 0x09: Palette format
    palette_num_entries = U16()  # 0x0A: Number of palette entries
    palette_data_offset = U32()  # 0x0C: Offset to palette data
    mipmap_enabled = U8()        # 0x10: Mipmap enable
    edge_lod_enabled = U8()      # 0x11: Enable edge LOD
    bias_clamp = U8()            # 0x12: Clamp LOD bias
    max_anisotropy = U8()        # 0x13: Max anisotropy
    min_filter = U8()            # 0x14: Min filter
    mag_filter = U8()            # 0x15: Mag filter
    min_lod = U8()               # 0x16: Min LOD (scaled by 8)
    max_lod = U8()               # 0x17: Max LOD (scaled by 8)
    image_count = U8()           # 0x18: Total image count (mipmaps + 1)
    padding = U8()               # 0x19: Padding
    lod_bias = U16()             # 0x1A: LOD bias
    image_data_offset = U32()    # 0x1C: Offset to image data


@dataclass
class BTIImage:
    """
    Represents a Nintendo BTI (Binary Texture Image).
    """
    width: int
    height: int
    format_id: int
    raw_data: bytes
    alpha_setting: int = 0
    wrap_s: int = 0
    wrap_t: int = 0
    palette_enabled: int = 0
    palette_format: int = 0
    palette_num_entries: int = 0
    palette_data: bytes = b""
    mipmap_enabled: int = 0
    edge_lod_enabled: int = 0
    bias_clamp: int = 0
    max_anisotropy: int = 0
    min_filter: int = 1
    mag_filter: int = 1
    min_lod: int = 0
    max_lod: int = 0
    image_count: int = 1
    lod_bias: int = 0

    @property
    def format_name(self) -> str:
        return TPL_FORMAT_NAMES.get(self.format_id, f"Unknown (0x{self.format_id:X})")

    def __repr__(self) -> str:
        return (
            f"<BTIImage {self.width}x{self.height} "
            f"format={self.format_name} ({len(self.raw_data)} bytes)>"
        )

    @classmethod
    def from_file(cls, filepath: str) -> "BTIImage":
        with open(filepath, "rb") as f:
            data = f.read()
        return cls.from_bytes(data)

    @classmethod
    def from_bytes(cls, data: bytes) -> "BTIImage":
        # Handle transparent Yaz0 decompression
        if data.startswith(b"Yaz0"):
            data = Yaz0.decompress(data)

        if len(data) < BTIHeaderStruct.sizeof():
            raise ParseError(
                f"Data too short for BTI header: {len(data)} bytes "
                f"(expected at least {BTIHeaderStruct.sizeof()})."
            )

        header = BTIHeaderStruct.from_bytes(data, offset=0)

        expected_size = calc_gx_texture_size(header.width, header.height, header.format_id)
        data_offset = header.image_data_offset
        if data_offset == 0:
            data_offset = BTIHeaderStruct.sizeof()

        raw_data = data[data_offset : data_offset + expected_size]
        if len(raw_data) < expected_size:
            raw_data = data[data_offset:]

        palette_data = b""
        if header.palette_enabled and header.palette_data_offset > 0:
            pal_size = header.palette_num_entries * 2
            palette_data = data[header.palette_data_offset : header.palette_data_offset + pal_size]

        return cls(
            width=header.width,
            height=header.height,
            format_id=header.format_id,
            raw_data=raw_data,
            alpha_setting=header.alpha_setting,
            wrap_s=header.wrap_s,
            wrap_t=header.wrap_t,
            palette_enabled=header.palette_enabled,
            palette_format=header.palette_format,
            palette_num_entries=header.palette_num_entries,
            palette_data=palette_data,
            mipmap_enabled=header.mipmap_enabled,
            edge_lod_enabled=header.edge_lod_enabled,
            bias_clamp=header.bias_clamp,
            max_anisotropy=header.max_anisotropy,
            min_filter=header.min_filter,
            mag_filter=header.mag_filter,
            min_lod=header.min_lod,
            max_lod=header.max_lod,
            image_count=max(1, header.image_count),
            lod_bias=header.lod_bias,
        )

    def decode_rgba(self) -> bytes:
        """Decodes the tiled texture into linear uncompressed RGBA8888 byte stream."""
        return decode_gx_texture(self.raw_data, self.width, self.height, self.format_id)

    def to_image(self) -> "Image.Image":
        """Renders the BTI image to a PIL Image."""
        if not HAS_PIL:
            raise ImportError("Pillow is required for BTIImage.to_image().")
        rgba = self.decode_rgba()
        return Image.frombytes("RGBA", (self.width, self.height), rgba)

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, "Image.Image"],
        format_id: int = 5,
        wrap_s: int = 0,
        wrap_t: int = 0,
    ) -> "BTIImage":
        """Encodes an image (or file path) into a BTIImage."""
        if not HAS_PIL:
            raise ImportError("Pillow is required for BTIImage.from_image().")

        if isinstance(image_or_path, str):
            pil_img = Image.open(image_or_path)
        else:
            pil_img = image_or_path

        pil_img = pil_img.convert("RGBA")
        width, height = pil_img.size
        rgba_bytes = pil_img.tobytes()

        raw_data = encode_gx_texture(rgba_bytes, width, height, format_id)

        # Infer alpha setting
        has_translucency = any(a < 255 for a in rgba_bytes[3::4])
        alpha_setting = 2 if has_translucency else 0

        return cls(
            width=width,
            height=height,
            format_id=format_id,
            raw_data=raw_data,
            alpha_setting=alpha_setting,
            wrap_s=wrap_s,
            wrap_t=wrap_t,
        )

    def to_bytes(self, compress_yaz0: bool = False) -> bytes:
        """Serializes the BTIImage back into standard Nintendo BTI binary format."""
        writer = BinaryWriter(endian=">")

        # Header placeholder
        hdr = BTIHeaderStruct(
            format_id=self.format_id,
            alpha_setting=self.alpha_setting,
            width=self.width,
            height=self.height,
            wrap_s=self.wrap_s,
            wrap_t=self.wrap_t,
            palette_enabled=self.palette_enabled,
            palette_format=self.palette_format,
            palette_num_entries=self.palette_num_entries,
            palette_data_offset=0,
            mipmap_enabled=self.mipmap_enabled,
            edge_lod_enabled=self.edge_lod_enabled,
            bias_clamp=self.bias_clamp,
            max_anisotropy=self.max_anisotropy,
            min_filter=self.min_filter,
            mag_filter=self.mag_filter,
            min_lod=self.min_lod,
            max_lod=self.max_lod,
            image_count=self.image_count,
            padding=0,
            lod_bias=self.lod_bias,
            image_data_offset=0,
        )
        writer.write_struct(hdr)

        # Write palette if present
        pal_offset = 0
        if self.palette_enabled and self.palette_data:
            writer.align(32)
            pal_offset = writer.tell()
            writer.write_bytes(self.palette_data)

        # Write image data aligned to 32 bytes
        writer.align(32)
        img_offset = writer.tell()
        writer.write_bytes(self.raw_data)

        # Patch offsets in header
        with writer.at(0):
            patched_hdr = BTIHeaderStruct(
                format_id=self.format_id,
                alpha_setting=self.alpha_setting,
                width=self.width,
                height=self.height,
                wrap_s=self.wrap_s,
                wrap_t=self.wrap_t,
                palette_enabled=self.palette_enabled,
                palette_format=self.palette_format,
                palette_num_entries=self.palette_num_entries,
                palette_data_offset=pal_offset,
                mipmap_enabled=self.mipmap_enabled,
                edge_lod_enabled=self.edge_lod_enabled,
                bias_clamp=self.bias_clamp,
                max_anisotropy=self.max_anisotropy,
                min_filter=self.min_filter,
                mag_filter=self.mag_filter,
                min_lod=self.min_lod,
                max_lod=self.max_lod,
                image_count=self.image_count,
                padding=0,
                lod_bias=self.lod_bias,
                image_data_offset=img_offset,
            )
            writer.write_struct(patched_hdr)

        raw_output = writer.to_bytes()
        if compress_yaz0:
            return Yaz0.compress(raw_output)
        return raw_output

    def to_file(self, filepath: str, compress_yaz0: bool = False) -> None:
        data = self.to_bytes(compress_yaz0=compress_yaz0)
        with open(filepath, "wb") as f:
            f.write(data)
