"""
miorom.graphics.n64_texture
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo 64 Fast3D texture decoder and encoder.
Supports RGBA16, RGBA32, IA16, IA8, IA4, I8, I4, CI8, and CI4 formats.
"""

from __future__ import annotations

import struct
from enum import Enum
from typing import Optional, Union

from miorom.errors import ParseError

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


class N64TextureFormat(Enum):
    RGBA16 = "rgba16"
    RGBA32 = "rgba32"
    IA16 = "ia16"
    IA8 = "ia8"
    IA4 = "ia4"
    I8 = "i8"
    I4 = "i4"
    CI8 = "ci8"
    CI4 = "ci4"


class N64TextureDecoder:
    """Decodes raw N64 Fast3D binary texture streams into 32-bit RGBA pixel buffers."""

    @classmethod
    def decode(
        cls,
        data: bytes,
        fmt: Union[N64TextureFormat, str],
        width: int,
        height: int,
        palette_data: Optional[bytes] = None,
    ) -> bytes:
        format_name = fmt.value if isinstance(fmt, N64TextureFormat) else fmt.lower()
        num_pixels = width * height
        out = bytearray(num_pixels * 4)

        if format_name == "rgba32":
            needed = num_pixels * 4
            out[:len(data)] = data[:needed]
            return bytes(out)

        elif format_name == "rgba16":
            needed = num_pixels * 2
            if len(data) < needed:
                data = data.ljust(needed, b"\x00")
            for idx in range(num_pixels):
                val = struct.unpack_from(">H", data, idx * 2)[0]
                r = ((val >> 11) & 0x1F) * 255 // 31
                g = ((val >> 6) & 0x1F) * 255 // 31
                b = ((val >> 1) & 0x1F) * 255 // 31
                a = 255 if (val & 1) else 0
                p = idx * 4
                out[p] = r
                out[p + 1] = g
                out[p + 2] = b
                out[p + 3] = a
            return bytes(out)

        elif format_name == "ia16":
            needed = num_pixels * 2
            if len(data) < needed:
                data = data.ljust(needed, b"\x00")
            for idx in range(num_pixels):
                intensity = data[idx * 2]
                alpha = data[idx * 2 + 1]
                p = idx * 4
                out[p] = intensity
                out[p + 1] = intensity
                out[p + 2] = intensity
                out[p + 3] = alpha
            return bytes(out)

        elif format_name == "ia8":
            needed = num_pixels
            if len(data) < needed:
                data = data.ljust(needed, b"\x00")
            for idx in range(num_pixels):
                byte = data[idx]
                intensity = ((byte >> 4) & 0x0F) * 255 // 15
                alpha = (byte & 0x0F) * 255 // 15
                p = idx * 4
                out[p] = intensity
                out[p + 1] = intensity
                out[p + 2] = intensity
                out[p + 3] = alpha
            return bytes(out)

        elif format_name == "ia4":
            needed = (num_pixels + 1) // 2
            if len(data) < needed:
                data = data.ljust(needed, b"\x00")
            for idx in range(num_pixels):
                byte = data[idx // 2]
                nibble = (byte >> 4) if (idx % 2 == 0) else (byte & 0x0F)
                intensity = ((nibble >> 1) & 0x07) * 255 // 7
                alpha = 255 if (nibble & 1) else 0
                p = idx * 4
                out[p] = intensity
                out[p + 1] = intensity
                out[p + 2] = intensity
                out[p + 3] = alpha
            return bytes(out)

        elif format_name == "i8":
            needed = num_pixels
            if len(data) < needed:
                data = data.ljust(needed, b"\x00")
            for idx in range(num_pixels):
                intensity = data[idx]
                p = idx * 4
                out[p] = intensity
                out[p + 1] = intensity
                out[p + 2] = intensity
                out[p + 3] = 255
            return bytes(out)

        elif format_name == "i4":
            needed = (num_pixels + 1) // 2
            if len(data) < needed:
                data = data.ljust(needed, b"\x00")
            for idx in range(num_pixels):
                byte = data[idx // 2]
                nibble = (byte >> 4) if (idx % 2 == 0) else (byte & 0x0F)
                intensity = nibble * 255 // 15
                p = idx * 4
                out[p] = intensity
                out[p + 1] = intensity
                out[p + 2] = intensity
                out[p + 3] = 255
            return bytes(out)

        elif format_name in ("ci8", "ci4"):
            if not palette_data:
                raise ParseError(f"Format {format_name.upper()} requires palette_data (RGBA16).")
            # Decode palette (RGBA16)
            pal_colors = []
            for pi in range(0, len(palette_data) - 1, 2):
                pval = struct.unpack_from(">H", palette_data, pi)[0]
                pr = ((pval >> 11) & 0x1F) * 255 // 31
                pg = ((pval >> 6) & 0x1F) * 255 // 31
                pb = ((pval >> 1) & 0x1F) * 255 // 31
                pa = 255 if (pval & 1) else 0
                pal_colors.append((pr, pg, pb, pa))

            for idx in range(num_pixels):
                if format_name == "ci8":
                    c_idx = data[idx] if idx < len(data) else 0
                else:
                    byte = data[idx // 2] if (idx // 2) < len(data) else 0
                    c_idx = (byte >> 4) if (idx % 2 == 0) else (byte & 0x0F)

                col = pal_colors[c_idx] if c_idx < len(pal_colors) else (0, 0, 0, 0)
                p = idx * 4
                out[p : p + 4] = col
            return bytes(out)

        else:
            raise ParseError(f"Unsupported N64 texture format: '{fmt}'")

    @classmethod
    def to_image(
        cls,
        data: bytes,
        fmt: Union[N64TextureFormat, str],
        width: int,
        height: int,
        palette_data: Optional[bytes] = None,
    ) -> "Image.Image":
        if not HAS_PIL:
            raise ImportError("Pillow is required. Install with 'pip install Pillow'.")
        rgba = cls.decode(data, fmt, width, height, palette_data)
        return Image.frombytes("RGBA", (width, height), rgba)

    @classmethod
    def to_png(
        cls,
        data: bytes,
        fmt: Union[N64TextureFormat, str],
        width: int,
        height: int,
        output_path: str,
        palette_data: Optional[bytes] = None,
    ) -> str:
        img = cls.to_image(data, fmt, width, height, palette_data)
        img.save(output_path, format="PNG")
        return output_path


class N64TextureEncoder:
    """Encodes standard 32-bit RGBA pixel buffers into native N64 Fast3D binary format."""

    @classmethod
    def encode(
        cls,
        rgba_bytes: bytes,
        fmt: Union[N64TextureFormat, str],
        width: int,
        height: int,
    ) -> bytes:
        format_name = fmt.value if isinstance(fmt, N64TextureFormat) else fmt.lower()
        num_pixels = width * height

        if format_name == "rgba32":
            return rgba_bytes[: num_pixels * 4]

        elif format_name == "rgba16":
            out = bytearray(num_pixels * 2)
            for idx in range(num_pixels):
                p = idx * 4
                r = rgba_bytes[p]
                g = rgba_bytes[p + 1]
                b = rgba_bytes[p + 2]
                a = rgba_bytes[p + 3]
                r5 = (r * 31 + 127) // 255
                g5 = (g * 31 + 127) // 255
                b5 = (b * 31 + 127) // 255
                a1 = 1 if a >= 128 else 0
                val = (r5 << 11) | (g5 << 6) | (b5 << 1) | a1
                struct.pack_into(">H", out, idx * 2, val)
            return bytes(out)

        elif format_name == "ia16":
            out = bytearray(num_pixels * 2)
            for idx in range(num_pixels):
                p = idx * 4
                intensity = (rgba_bytes[p] * 3 + rgba_bytes[p + 1] * 6 + rgba_bytes[p + 2]) // 10
                alpha = rgba_bytes[p + 3]
                out[idx * 2] = intensity
                out[idx * 2 + 1] = alpha
            return bytes(out)

        elif format_name == "i8":
            out = bytearray(num_pixels)
            for idx in range(num_pixels):
                p = idx * 4
                out[idx] = (rgba_bytes[p] * 3 + rgba_bytes[p + 1] * 6 + rgba_bytes[p + 2]) // 10
            return bytes(out)

        else:
            raise ParseError(f"Unsupported N64 texture encode format: '{fmt}'")

    @classmethod
    def from_image(
        cls,
        image_or_path: Union[str, "Image.Image"],
        fmt: Union[N64TextureFormat, str],
    ) -> bytes:
        if not HAS_PIL:
            raise ImportError("Pillow is required. Install with 'pip install Pillow'.")
        if isinstance(image_or_path, str):
            img = Image.open(image_or_path)
        else:
            img = image_or_path
        img = img.convert("RGBA")
        width, height = img.size
        rgba_bytes = img.tobytes()
        return cls.encode(rgba_bytes, fmt, width, height)
