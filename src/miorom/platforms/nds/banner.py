"""
miorom.platforms.nds.banner
~~~~~~~~~~~~~~~~~~~~~~~~~~~
Nintendo DS Cartridge Banner (`banner.bin`) Parser, Editor, and Builder.

The Nintendo DS banner container (standard size 0x840 bytes, or larger for v2/v3/DSi)
is read by the Nintendo DS firmware and flashcard menus to display the game's icon
and multilingual titles.

Structure:
  0x0000..0x001F (32 bytes):  Banner Header (Version, CRC16 checksums, Reserved)
  0x0020..0x021F (512 bytes): 32x32 4bpp Tiled Icon Bitmap (16 tiles of 8x8 pixels)
  0x0220..0x023F (32 bytes):  16-color Icon Palette (BGR555, Color 0 is Transparent)
  0x0240..0x083F (1536 bytes): Multilingual Titles (6 languages @ 256 bytes UTF-16LE)
  0x0840..0x093F (256 bytes):  Version 2+ Chinese Title (optional)
  0x0940..0x0A3F (256 bytes):  Version 3+ Korean Title (optional)
  0x1240..0x23BF (4480 bytes): Version 0x0103 DSi Animated Icon & Palettes (optional)

Pure Python implementation using miorom.core.schema declarative models and zero
external runtime dependencies.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.core.checksum import RetroChecksum
from miorom.core.schema import U16, BinaryStruct, RawBytes
from miorom.errors import ParseError
from miorom.graphics.png_codec import PNGCodec, PNGImage

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


BANNER_LANGUAGES: Dict[int, str] = {
    0: "Japanese",
    1: "English",
    2: "French",
    3: "German",
    4: "Italian",
    5: "Spanish",
    6: "Chinese",
    7: "Korean",
}

LANGUAGE_NAME_TO_INDEX: Dict[str, int] = {
    "japanese": 0, "jp": 0, "ja": 0,
    "english": 1, "en": 1, "us": 1,
    "french": 2, "fr": 2,
    "german": 3, "de": 3, "ge": 3,
    "italian": 4, "it": 4,
    "spanish": 5, "es": 5,
    "chinese": 6, "zh": 6, "cn": 6,
    "korean": 7, "ko": 7, "kr": 7,
}


class NDSBannerHeaderStruct(BinaryStruct):
    """
    32-byte header located at offset 0x0000 of banner.bin.
    Contains format version, checksums, and zero-padding.
    """
    _endian = "<"
    version = U16()          # 0x0001 (NDS v1), 0x0002 (Chinese), 0x0003 (Korean), 0x0103 (DSi)
    crc_v1 = U16()           # CRC16 over 0x0020..0x083F (0x820 bytes)
    crc_v2 = U16()           # CRC16 over 0x0020..0x093F (0x920 bytes, for v2+)
    crc_v3 = U16()           # CRC16 over 0x0020..0x0A3F (0xA20 bytes, for v3+)
    crc_dsi = U16()          # CRC16 over 0x1240..0x23BF (0x1180 bytes, for v0x0103)
    _reserved = RawBytes(22) # 22 bytes of 0x00 padding


def rgb_to_bgr555(r: int, g: int, b: int) -> int:
    """Converts 8-bit RGB (0..255) to 15-bit BGR555 uint16."""
    r5 = (r >> 3) & 0x1F
    g5 = (g >> 3) & 0x1F
    b5 = (b >> 3) & 0x1F
    return r5 | (g5 << 5) | (b5 << 10)


def bgr555_to_rgb(val: int) -> Tuple[int, int, int]:
    """Converts 15-bit BGR555 uint16 to 8-bit RGB (0..255)."""
    r5 = val & 0x1F
    g5 = (val >> 5) & 0x1F
    b5 = (val >> 10) & 0x1F
    r8 = (r5 << 3) | (r5 >> 2)
    g8 = (g5 << 3) | (g5 >> 2)
    b8 = (b5 << 3) | (b5 >> 2)
    return (r8, g8, b8)


class NDSBanner:
    """
    High-level representation and editor for Nintendo DS banner.bin containers.
    """

    def __init__(
        self,
        version: int = 0x0001,
        icon_bitmap: Optional[bytes] = None,
        icon_palette: Optional[List[Tuple[int, int, int]]] = None,
        titles: Optional[Dict[int, str]] = None,
        dsi_extended_data: Optional[bytes] = None,
        header_crc_v1: Optional[int] = None,
        header_crc_v2: Optional[int] = None,
        header_crc_v3: Optional[int] = None,
        header_crc_dsi: Optional[int] = None,
    ):
        self.version = version
        self.icon_bitmap = bytearray(icon_bitmap or (b"\x00" * 512))
        # 16-color palette (RGB tuples, index 0 is transparent)
        self.icon_palette = list(icon_palette or ([(0, 0, 0)] * 16))
        while len(self.icon_palette) < 16:
            self.icon_palette.append((0, 0, 0))
        self.titles: Dict[int, str] = titles or {}
        self.dsi_extended_data = bytes(dsi_extended_data or b"")
        self.header_crc_v1 = header_crc_v1
        self.header_crc_v2 = header_crc_v2
        self.header_crc_v3 = header_crc_v3
        self.header_crc_dsi = header_crc_dsi

    @classmethod
    def from_bytes(cls, data: Union[bytes, bytearray]) -> "NDSBanner":
        """
        Parses an NDSBanner from raw banner.bin binary bytes.
        """
        if len(data) < 0x840:
            raise ParseError(
                f"Invalid NDS banner size: {len(data)} bytes (minimum 0x840 bytes required)."
            )

        header = NDSBannerHeaderStruct.from_bytes(data, offset=0)
        version = header.version

        # 1. 32x32 4bpp tiled icon bitmap (512 bytes)
        icon_bitmap = data[0x20:0x220]

        # 2. 16-color palette (32 bytes BGR555)
        raw_pal = data[0x220:0x240]
        icon_palette: List[Tuple[int, int, int]] = []
        for i in range(16):
            col_val = raw_pal[i * 2] | (raw_pal[i * 2 + 1] << 8)
            icon_palette.append(bgr555_to_rgb(col_val))

        # 3. Titles (up to 8 languages depending on version and file length)
        titles: Dict[int, str] = {}
        max_langs = 6
        if version >= 2 and len(data) >= 0x940:
            max_langs = 7
        if version >= 3 and len(data) >= 0xA40:
            max_langs = 8

        for lang in range(max_langs):
            start = 0x240 + (lang * 256)
            end = start + 256
            if end <= len(data):
                raw_title = data[start:end]
                null_idx = len(raw_title)
                for i in range(0, len(raw_title), 2):
                    if raw_title[i : i + 2] == b"\x00\x00":
                        null_idx = i
                        break
                raw_title = raw_title[:null_idx]
                try:
                    titles[lang] = raw_title.decode("utf-16-le").strip()
                except UnicodeDecodeError:
                    titles[lang] = raw_title.decode("latin-1", errors="replace").strip()

        # 4. DSi extended animated data (if present)
        dsi_data = b""
        if len(data) >= 0x23C0:
            dsi_data = bytes(data[0x1240:0x23C0])
        elif len(data) >= 0x1240:
            if data[0xA40:0x1240] == b"\x00" * 0x800:
                dsi_data = bytes(data[0x1240:])
            else:
                dsi_data = bytes(data[0xA40:])
        elif len(data) > 0xA40:
            dsi_data = bytes(data[0xA40:])

        return cls(
            version=version,
            icon_bitmap=icon_bitmap,
            icon_palette=icon_palette,
            titles=titles,
            dsi_extended_data=dsi_data,
            header_crc_v1=header.crc_v1,
            header_crc_v2=header.crc_v2,
            header_crc_v3=header.crc_v3,
            header_crc_dsi=header.crc_dsi,
        )

    @classmethod
    def from_file(cls, path: str) -> "NDSBanner":
        """Loads and parses an NDSBanner from a file on disk."""
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def save(self, path: str, recalc_crc: bool = True) -> None:
        """Serializes and saves the banner to a file on disk."""
        with open(path, "wb") as f:
            f.write(self.to_bytes(recalc_crc=recalc_crc))

    def _resolve_language_index(self, lang: Union[int, str]) -> int:
        if isinstance(lang, int):
            idx = lang
        else:
            key = str(lang).strip().lower()
            if key in LANGUAGE_NAME_TO_INDEX:
                idx = LANGUAGE_NAME_TO_INDEX[key]
            else:
                try:
                    idx = int(key)
                except ValueError:
                    raise KeyError(f"Unknown banner language identifier: '{lang}'.")
        if not (0 <= idx <= 7):
            raise IndexError(f"Banner language index out of range: {idx} (must be 0..7).")
        return idx

    def get_title(self, language: Union[int, str] = 1) -> str:
        """
        Gets game title string for the given language (default: 1 / English).
        Accepts integer ID (0..7) or language name string (e.g. 'English', 'Japanese').
        """
        idx = self._resolve_language_index(language)
        return self.titles.get(idx, "")

    def set_title(self, title: str, language: Union[int, str] = 1) -> None:
        """
        Sets game title string for the given language.
        Title may contain newline ('\n') for multiline display on the DS menu.
        """
        idx = self._resolve_language_index(language)
        # Update version if setting Chinese or Korean titles
        if idx == 6 and self.version < 2:
            self.version = 2
        elif idx == 7 and self.version < 3:
            self.version = 3
        self.titles[idx] = str(title)

    def to_bytes(self, recalc_crc: bool = True) -> bytes:
        """
        Serializes the banner to binary bytes, automatically computing all CRC16 checksums.
        """
        # Determine number of title slots based on version and populated titles
        if 7 in self.titles or self.version >= 3 or self.version == 0x0103 or self.dsi_extended_data:
            num_langs = 8
            if self.version < 3 and self.version != 0x0103:
                self.version = 3
        elif 6 in self.titles or self.version >= 2:
            num_langs = 7
            if self.version < 2:
                self.version = 2
        else:
            num_langs = 6

        payload = bytearray()

        # 1. 32x32 4bpp icon bitmap (512 bytes)
        raw_bitmap = bytearray(self.icon_bitmap[:512])
        while len(raw_bitmap) < 512:
            raw_bitmap.append(0)
        payload.extend(raw_bitmap)

        # 2. 16-color palette (32 bytes BGR555)
        for i in range(16):
            if i < len(self.icon_palette):
                r, g, b = self.icon_palette[i]
                bgr = rgb_to_bgr555(r, g, b)
            else:
                bgr = 0
            payload.append(bgr & 0xFF)
            payload.append((bgr >> 8) & 0xFF)

        # 3. Titles (each 256 bytes UTF-16LE)
        for lang in range(num_langs):
            title_text = self.titles.get(lang, "")
            enc = title_text.encode("utf-16-le")
            while len(enc) > 254:
                title_text = title_text[:-1]
                enc = title_text.encode("utf-16-le")
            title_buf = bytearray(enc)
            while len(title_buf) < 256:
                title_buf.append(0)
            payload.extend(title_buf)

        # Compute or preserve CRCs over payload (offset 0x20 in full file)
        if recalc_crc or self.header_crc_v1 is None:
            crc_v1 = RetroChecksum.crc16_modbus(payload[:0x820])
            crc_v2 = 0
            crc_v3 = 0
            crc_dsi = 0

            if self.version >= 2:
                # crc_v2 covers 0x0020..0x093F (2080 + 256 = 2336 = 0x920 bytes)
                crc_v2 = RetroChecksum.crc16_modbus(payload[:0x920])
            if self.version >= 3 or self.version == 0x0103:
                # crc_v3 covers 0x0020..0x0A3F (2336 + 256 = 2592 = 0xA20 bytes)
                crc_v3 = RetroChecksum.crc16_modbus(payload[:0xA20])
            if self.version == 0x0103 or self.dsi_extended_data:
                # crc_dsi covers 0x1240..0x23BF (0x1180 bytes = 4480 bytes)
                dsi_payload = self.dsi_extended_data
                if len(dsi_payload) >= 0x1980 and dsi_payload[:0x800] == b"\x00" * 0x800:
                    dsi_payload = dsi_payload[0x800:]
                padded_dsi = dsi_payload[:0x1180].ljust(0x1180, b"\x00")
                crc_dsi = RetroChecksum.crc16_modbus(padded_dsi)

            self.header_crc_v1 = crc_v1
            self.header_crc_v2 = crc_v2
            self.header_crc_v3 = crc_v3
            self.header_crc_dsi = crc_dsi
        else:
            crc_v1 = self.header_crc_v1
            crc_v2 = self.header_crc_v2 or 0
            crc_v3 = self.header_crc_v3 or 0
            crc_dsi = self.header_crc_dsi or 0

        header = NDSBannerHeaderStruct(
            version=self.version,
            crc_v1=crc_v1,
            crc_v2=crc_v2,
            crc_v3=crc_v3,
            crc_dsi=crc_dsi,
        )

        out = bytearray()
        out.extend(header.to_bytes())
        out.extend(payload)

        # Append DSi extended animated icon data if present (version 0x0103 or dsi_extended_data set)
        if self.dsi_extended_data or self.version == 0x0103:
            # Pad up to offset 0x1240 (0x800 bytes reserved for titles 8..15)
            if len(out) < 0x1240:
                out.extend(b"\x00" * (0x1240 - len(out)))
            dsi_payload = self.dsi_extended_data
            if len(dsi_payload) >= 0x1980 and dsi_payload[:0x800] == b"\x00" * 0x800:
                dsi_payload = dsi_payload[0x800:]
            out.extend(dsi_payload)
            # Standard DSi extended banner is 0x23C0 bytes (0x1240 + 0x1180)
            if len(out) < 0x23C0:
                out.extend(b"\x00" * (0x23C0 - len(out)))

        return bytes(out)

    def is_crc_valid(self) -> bool:
        """
        Verifies all CRC16 checksums in the banner header against the current payload.
        """
        raw = self.to_bytes(recalc_crc=False)
        header = NDSBannerHeaderStruct.from_bytes(raw, offset=0)

        # Check v1
        if len(raw) < 0x840:
            return False
        calc_v1 = RetroChecksum.crc16_modbus(raw[0x20:0x840])
        if header.crc_v1 != calc_v1:
            return False

        # Check v2
        if header.version >= 2 and len(raw) >= 0x940:
            calc_v2 = RetroChecksum.crc16_modbus(raw[0x20:0x940])
            if header.crc_v2 != calc_v2:
                return False

        # Check v3
        if (header.version >= 3 or header.version == 0x0103) and len(raw) >= 0xA40:
            calc_v3 = RetroChecksum.crc16_modbus(raw[0x20:0xA40])
            if header.crc_v3 != calc_v3:
                return False

        # Check DSi (version 0x0103)
        if header.version == 0x0103:
            if len(raw) < 0x23C0:
                return False
            calc_dsi = RetroChecksum.crc16_modbus(raw[0x1240:0x23C0])
            if header.crc_dsi != calc_dsi:
                return False

        return True

    def recalculate_crc(self) -> None:
        """Explicitly recomputes all CRC16 values."""
        self.to_bytes(recalc_crc=True)

    def get_pixel_indices(self) -> List[List[int]]:
        """
        Decodes the 512-byte 4bpp tiled bitmap into a 32x32 grid of palette indices (0..15).
        """
        pixels = [[0] * 32 for _ in range(32)]
        tile_idx = 0
        for ty in range(4):
            for tx in range(4):
                tile_start = tile_idx * 32
                for row in range(8):
                    y = ty * 8 + row
                    for col in range(4):
                        b = self.icon_bitmap[tile_start + row * 4 + col]
                        pixels[y][tx * 8 + col * 2] = b & 0x0F
                        pixels[y][tx * 8 + col * 2 + 1] = (b >> 4) & 0x0F
                tile_idx += 1
        return pixels

    def set_pixel_indices(self, pixels: List[List[int]]) -> None:
        """
        Encodes a 32x32 grid of palette indices (0..15) into 512 bytes of 4bpp tiles.
        """
        out = bytearray(512)
        tile_idx = 0
        for ty in range(4):
            for tx in range(4):
                tile_start = tile_idx * 32
                for row in range(8):
                    y = ty * 8 + row
                    for col in range(4):
                        p0 = pixels[y][tx * 8 + col * 2] & 0x0F
                        p1 = pixels[y][tx * 8 + col * 2 + 1] & 0x0F
                        out[tile_start + row * 4 + col] = p0 | (p1 << 4)
                tile_idx += 1
        self.icon_bitmap = out

    def to_rgba_bytes(self) -> bytes:
        """
        Converts the 32x32 icon into 4096 raw RGBA bytes (32 * 32 * 4).
        Index 0 is rendered with Alpha = 0 (transparent).
        """
        pixels = self.get_pixel_indices()
        out = bytearray(32 * 32 * 4)
        idx = 0
        for y in range(32):
            for x in range(32):
                pal_idx = pixels[y][x]
                if pal_idx == 0:
                    r, g, b = self.icon_palette[0] if self.icon_palette else (0, 0, 0)
                    a = 0  # Color 0 is transparent
                else:
                    r, g, b = self.icon_palette[pal_idx] if pal_idx < len(self.icon_palette) else (0, 0, 0)
                    a = 255
                out[idx] = r
                out[idx + 1] = g
                out[idx + 2] = b
                out[idx + 3] = a
                idx += 4
        return bytes(out)

    def to_png_bytes(self) -> bytes:
        """
        Encodes the 32x32 icon into PNG binary bytes using pure-Python PNGCodec.
        Zero external dependencies.
        """
        rgba = self.to_rgba_bytes()
        return PNGCodec.rgba_to_png(32, 32, rgba)

    def save_icon_png(self, path: Union[str, Path]) -> None:
        """
        Saves the 32x32 icon as a PNG image file on disk.
        Zero external dependencies.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "wb") as f:
            f.write(self.to_png_bytes())

    def to_image(self) -> Any:
        """
        Renders the 32x32 icon as a PIL Image in RGBA mode with transparency.
        Requires Pillow.
        """
        if not HAS_PIL:
            raise ImportError("Pillow is required for NDSBanner.to_image(). Use to_png_bytes() or save_icon_png() for zero-dependency output.")
        rgba = self.to_rgba_bytes()
        return Image.frombytes("RGBA", (32, 32), rgba)

    def set_image(self, image_or_rgba: Any) -> None:
        """
        Quantizes and encodes an image (PIL Image, PNGImage, file path, PNG bytes, or 4096 RGBA bytes)
        into a 16-color BGR555 palette and 32x32 4bpp tiled bitmap.
        Transparent pixels (alpha < 128) are mapped to palette index 0.
        Opaque pixels (alpha >= 128) are mapped to palette indices 1..15.
        """
        if HAS_PIL and isinstance(image_or_rgba, Image.Image):
            img = image_or_rgba.convert("RGBA")
            if img.size != (32, 32):
                img = img.resize((32, 32))
            rgba_bytes = img.tobytes()
        elif isinstance(image_or_rgba, PNGImage):
            if (image_or_rgba.width, image_or_rgba.height) != (32, 32):
                if HAS_PIL:
                    img = Image.frombytes("RGBA", (image_or_rgba.width, image_or_rgba.height), image_or_rgba.to_rgba_bytes()).resize((32, 32))
                    rgba_bytes = img.tobytes()
                else:
                    raise ValueError(f"PNG image must be 32x32 pixels without Pillow (got {image_or_rgba.width}x{image_or_rgba.height}).")
            else:
                rgba_bytes = image_or_rgba.to_rgba_bytes()
        elif isinstance(image_or_rgba, (bytes, bytearray)):
            raw_input = bytes(image_or_rgba)
            if raw_input.startswith(PNGCodec.PNG_SIGNATURE):
                w, h, rgba_bytes = PNGCodec.png_to_rgba(raw_input)
                if (w, h) != (32, 32):
                    if HAS_PIL:
                        img = Image.frombytes("RGBA", (w, h), rgba_bytes).resize((32, 32))
                        rgba_bytes = img.tobytes()
                    else:
                        raise ValueError(f"PNG image must be 32x32 pixels without Pillow (got {w}x{h}).")
            else:
                rgba_bytes = raw_input
        elif isinstance(image_or_rgba, (str, Path)):
            file_path = Path(image_or_rgba)
            if not file_path.is_file():
                raise FileNotFoundError(f"Image file not found: {file_path}")
            raw_bytes = file_path.read_bytes()
            if raw_bytes.startswith(PNGCodec.PNG_SIGNATURE):
                w, h, rgba_bytes = PNGCodec.png_to_rgba(raw_bytes)
                if (w, h) != (32, 32):
                    if HAS_PIL:
                        img = Image.open(file_path).convert("RGBA").resize((32, 32))
                        rgba_bytes = img.tobytes()
                    else:
                        raise ValueError(f"PNG image must be 32x32 pixels without Pillow (got {w}x{h}).")
            elif HAS_PIL:
                img = Image.open(file_path).convert("RGBA").resize((32, 32))
                rgba_bytes = img.tobytes()
            else:
                raise ImportError("Pillow is required to load non-PNG images from file path.")
        else:
            raise ValueError(f"Unsupported image type: {type(image_or_rgba)}")

        if len(rgba_bytes) != 32 * 32 * 4:
            raise ValueError(
                f"Expected 4096 RGBA bytes (32x32), got {len(rgba_bytes)} bytes."
            )

        # 1. Collect distinct colors and identify transparency
        raw_pixels: List[Tuple[int, int, int, int]] = []
        opaque_colors: Dict[Tuple[int, int, int], int] = {}

        for i in range(0, len(rgba_bytes), 4):
            r = rgba_bytes[i]
            g = rgba_bytes[i + 1]
            b = rgba_bytes[i + 2]
            a = rgba_bytes[i + 3]
            raw_pixels.append((r, g, b, a))
            if a >= 128:
                # Quantize to 15-bit BGR555 color space
                bgr555 = rgb_to_bgr555(r, g, b)
                rgb_q = bgr555_to_rgb(bgr555)
                opaque_colors[rgb_q] = opaque_colors.get(rgb_q, 0) + 1

        # 2. Build 16-color palette (Index 0 = transparent, Indices 1..15 = opaque)
        sorted_colors = sorted(opaque_colors.keys(), key=lambda c: opaque_colors[c], reverse=True)
        chosen_opaque = sorted_colors[:15]

        palette = [(0, 0, 0)] + chosen_opaque
        while len(palette) < 16:
            palette.append((0, 0, 0))
        self.icon_palette = palette

        # 3. Map pixels to palette indices
        def find_nearest_index(r: int, g: int, b: int) -> int:
            if not chosen_opaque:
                return 1
            best_idx = 1
            min_dist = float("inf")
            for idx in range(1, 1 + len(chosen_opaque)):
                pr, pg, pb = palette[idx]
                dist = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if dist < min_dist:
                    min_dist = dist
                    best_idx = idx
            return best_idx

        pixel_indices = [[0] * 32 for _ in range(32)]
        for y in range(32):
            for x in range(32):
                r, g, b, a = raw_pixels[y * 32 + x]
                if a < 128:
                    pixel_indices[y][x] = 0
                else:
                    bgr555 = rgb_to_bgr555(r, g, b)
                    rgb_q = bgr555_to_rgb(bgr555)
                    if rgb_q in chosen_opaque:
                        # Map to index 1..15, strictly avoiding index 0 (hardware transparent)
                        pixel_indices[y][x] = 1 + chosen_opaque.index(rgb_q)
                    else:
                        pixel_indices[y][x] = find_nearest_index(r, g, b)

        self.set_pixel_indices(pixel_indices)
