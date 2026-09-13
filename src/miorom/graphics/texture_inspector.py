"""
miorom.graphics.texture_inspector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Forensic Texture Inspector and Mathematical Visual Regression Diffing.
Analyzes game texture formats (TPL, BTI, PNG), inspects palettes, validates
tile dimensions, and computes pixel-level diff reports between original and modified textures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import io
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from miorom.errors import ParseError
from miorom.result import MioRomResult
from miorom.platforms.wii.tpl import TPLFile, TPL_FORMAT_NAMES, TPL_PALETTE_FORMAT_NAMES, calc_gx_texture_size

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


@dataclass
class TextureInspectReport(MioRomResult):
    """Forensic report containing deep structural inspection of a texture."""
    container_type: str
    width: int
    height: int
    format_name: str
    format_id: int
    is_paletted: bool
    palette_format: Optional[str] = None
    palette_color_count: int = 0
    unique_colors_count: int = 0
    data_size: int = 0
    tile_dimensions: Tuple[int, int] = (8, 8)
    warnings: List[str] = field(default_factory=list)
    images_count: int = 1

    def summary(self) -> str:
        lines = [
            "=" * 64,
            f"MioROM Forensic Texture Inspection: {self.container_type}",
            "=" * 64,
            f"Dimensions:          {self.width}x{self.height} (Tile Grid: {self.tile_dimensions[0]}x{self.tile_dimensions[1]})",
            f"Format:              {self.format_name} (0x{self.format_id:02X})",
            f"Paletted:            {'Yes' if self.is_paletted else 'No'}",
        ]
        if self.is_paletted:
            lines.append(f"Palette Format:      {self.palette_format or 'N/A'}")
            lines.append(f"Palette Capacity:    {self.palette_color_count} colors")
        lines.append(f"Unique Colors:       {self.unique_colors_count}")
        lines.append(f"Payload Data Size:   {self.data_size} bytes")
        if self.images_count > 1:
            lines.append(f"Image Count:         {self.images_count}")
        if self.warnings:
            lines.append("-" * 64)
            lines.append(f"Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        lines.append("=" * 64)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "container_type": self.container_type,
            "width": self.width,
            "height": self.height,
            "format_name": self.format_name,
            "format_id": self.format_id,
            "is_paletted": self.is_paletted,
            "palette_format": self.palette_format,
            "palette_color_count": self.palette_color_count,
            "unique_colors_count": self.unique_colors_count,
            "data_size": self.data_size,
            "tile_dimensions": list(self.tile_dimensions),
            "warnings": self.warnings,
            "images_count": self.images_count,
        }


@dataclass
class TextureDiffReport(MioRomResult):
    """Mathematical visual regression diff between original and modified textures."""
    orig_dims: Tuple[int, int]
    mod_dims: Tuple[int, int]
    dimensions_match: bool
    orig_format: str
    mod_format: str
    formats_match: bool
    total_pixels: int
    modified_pixel_count: int
    modified_pixel_pct: float
    max_delta: int
    alpha_preserved: bool
    bounding_box: Optional[Tuple[int, int, int, int]] = None
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        dim_status = "Exact Match" if self.dimensions_match else "MISMATCH"
        fmt_status = "Exact Match" if self.formats_match else "MISMATCH"
        lines = [
            "=" * 64,
            "MioROM Forensic Texture Diff",
            "=" * 64,
            f"Dimensions:          Orig: {self.orig_dims[0]}x{self.orig_dims[1]} | Mod: {self.mod_dims[0]}x{self.mod_dims[1]} ({dim_status})",
            f"Format Parity:       Orig: {self.orig_format} | Mod: {self.mod_format} ({fmt_status})",
            f"Total Pixels:        {self.total_pixels:,}",
            f"Modified Pixels:     {self.modified_pixel_count:,} ({self.modified_pixel_pct:.2f}%)",
            f"Max Channel Delta:   {self.max_delta}",
            f"Alpha Integrity:     {'Preserved' if self.alpha_preserved else 'DEGRADED / CHANGED'}",
        ]
        if self.bounding_box:
            min_x, min_y, max_x, max_y = self.bounding_box
            lines.append(f"Bounding Box:        (x: {min_x}..{max_x}, y: {min_y}..{max_y})")
        else:
            lines.append("Bounding Box:        None (Identical)")
        if self.warnings:
            lines.append("-" * 64)
            lines.append(f"Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                lines.append(f"  [!] {w}")
        lines.append("=" * 64)
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "orig_dims": list(self.orig_dims),
            "mod_dims": list(self.mod_dims),
            "dimensions_match": self.dimensions_match,
            "orig_format": self.orig_format,
            "mod_format": self.mod_format,
            "formats_match": self.formats_match,
            "total_pixels": self.total_pixels,
            "modified_pixel_count": self.modified_pixel_count,
            "modified_pixel_pct": self.modified_pixel_pct,
            "max_delta": self.max_delta,
            "alpha_preserved": self.alpha_preserved,
            "bounding_box": list(self.bounding_box) if self.bounding_box else None,
            "warnings": self.warnings,
        }


class TextureInspector:
    """
    Forensic texture inspector and comparator.
    Supports TPL, BTI, and standard image formats.
    """

    @classmethod
    def _read_data(cls, target: Union[str, bytes]) -> bytes:
        if isinstance(target, bytes):
            return target
        if isinstance(target, str):
            with open(target, "rb") as f:
                return f.read()
        raise TypeError(f"Expected file path or bytes, got {type(target)}")

    @classmethod
    def _get_tile_dims(cls, format_id: int) -> Tuple[int, int]:
        if format_id in (0, 8, 14):  # I4, CI4, CMPR
            return (8, 8)
        elif format_id in (1, 2, 9):  # I8, IA4, CI8
            return (8, 4)
        elif format_id in (3, 4, 5, 6, 10):  # IA8, RGB565, RGB5A3, RGBA8
            return (4, 4)
        return (8, 8)

    @classmethod
    def _load_rgba_and_meta(
        cls,
        target: Union[str, bytes],
    ) -> Tuple[bytes, int, int, str, int, bool, Optional[str], int, int, Tuple[int, int], List[str], int]:
        data = cls._read_data(target)
        warnings: List[str] = []

        # 1. Check Nintendo TPL
        if data.startswith(b"\x00\x20\xaf\x30"):
            tpl = TPLFile.from_bytes(data)
            if not tpl.images:
                raise ParseError("TPL file contains 0 images.")
            img = tpl.images[0]
            rgba = tpl.decode_rgba(0)
            tile_dims = cls._get_tile_dims(img.format_id)
            expected_sz = calc_gx_texture_size(img.width, img.height, img.format_id)

            if len(img.raw_data) < expected_sz:
                warnings.append(f"Payload size ({len(img.raw_data)} bytes) is truncated; expected at least {expected_sz} bytes.")
            if img.width % tile_dims[0] != 0 or img.height % tile_dims[1] != 0:
                warnings.append(f"Texture dimensions ({img.width}x{img.height}) are not aligned to tile boundary {tile_dims[0]}x{tile_dims[1]}.")

            pal_fmt = img.palette_format_name if img.is_paletted else None
            pal_count = img.color_count if img.is_paletted else 0
            container = "TPL"
            fmt_name = img.format_name
            fmt_id = img.format_id
            is_pal = img.is_paletted
            w, h = img.width, img.height
            img_count = len(tpl.images)

        # 2. Check PNG
        elif data.startswith(b"\x89PNG\r\n\x1a\n"):
            if not HAS_PIL:
                raise ImportError("Pillow is required to inspect PNG textures.")
            pil_img = Image.open(io.BytesIO(data))
            w, h = pil_img.size
            rgba = pil_img.convert("RGBA").tobytes()
            container = "PNG"
            fmt_name = f"PNG ({pil_img.mode})"
            fmt_id = 0xFF
            is_pal = (pil_img.mode == "P")
            pal_fmt = "RGB" if is_pal else None
            pal_count = 256 if is_pal else 0
            tile_dims = (1, 1)
            img_count = 1

        else:
            # Fallback raw / unknown
            container = "Raw"
            fmt_name = "Unknown"
            fmt_id = 0
            is_pal = False
            pal_fmt = None
            pal_count = 0
            w, h = 0, 0
            rgba = b""
            tile_dims = (1, 1)
            img_count = 1
            warnings.append("Unknown texture container header.")

        # Analyze RGBA colors
        unique_colors = set()
        if rgba:
            for i in range(0, len(rgba), 4):
                unique_colors.add((rgba[i], rgba[i + 1], rgba[i + 2], rgba[i + 3]))

        if is_pal and pal_count > 0 and len(unique_colors) > pal_count:
            warnings.append(
                f"Unique color count ({len(unique_colors)}) exceeds palette hardware capacity ({pal_count})."
            )

        return (
            rgba,
            w,
            h,
            container,
            fmt_name,
            fmt_id,
            is_pal,
            pal_fmt,
            pal_count,
            len(unique_colors),
            tile_dims,
            warnings,
            img_count,
        )

    @classmethod
    def inspect(cls, file_or_data: Union[str, bytes]) -> TextureInspectReport:
        """
        Forensically inspects a texture file or byte buffer.
        """
        data = cls._read_data(file_or_data)
        (
            rgba,
            w,
            h,
            container,
            fmt_name,
            fmt_id,
            is_pal,
            pal_fmt,
            pal_count,
            unique_count,
            tile_dims,
            warnings,
            img_count,
        ) = cls._load_rgba_and_meta(data)

        return TextureInspectReport(
            container_type=container,
            width=w,
            height=h,
            format_name=fmt_name,
            format_id=fmt_id,
            is_paletted=is_pal,
            palette_format=pal_fmt,
            palette_color_count=pal_count,
            unique_colors_count=unique_count,
            data_size=len(data),
            tile_dimensions=tile_dims,
            warnings=warnings,
            images_count=img_count,
        )

    @classmethod
    def diff(
        cls,
        orig: Union[str, bytes],
        mod: Union[str, bytes],
    ) -> TextureDiffReport:
        """
        Compares an original texture against a modified texture.
        Computes pixel deltas, bounding box of modifications, format parity, and alpha integrity.
        """
        meta1 = cls._load_rgba_and_meta(orig)
        meta2 = cls._load_rgba_and_meta(mod)

        rgba1, w1, h1, cont1, fmt1, fid1, is_pal1, p_fmt1, p_cnt1, uq1, td1, warn1, ic1 = meta1
        rgba2, w2, h2, cont2, fmt2, fid2, is_pal2, p_fmt2, p_cnt2, uq2, td2, warn2, ic2 = meta2

        warnings: List[str] = []
        dims_match = (w1 == w2 and h1 == h2)
        if not dims_match:
            warnings.append(f"Dimension mismatch: Original ({w1}x{h1}) vs Modified ({w2}x{h2}).")

        fmts_match = (fmt1 == fmt2)
        if not fmts_match:
            warnings.append(f"Format mismatch: Original is {fmt1}, but Modified is {fmt2}.")

        cmp_w = min(w1, w2)
        cmp_h = min(h1, h2)
        total_pixels = cmp_w * cmp_h

        modified_pixels = 0
        max_delta = 0
        min_x, min_y = cmp_w, cmp_h
        max_x, max_y = -1, -1

        orig_alphas = set()
        mod_alphas = set()

        for y in range(cmp_h):
            for x in range(cmp_w):
                idx1 = (y * w1 + x) * 4
                idx2 = (y * w2 + x) * 4

                p1 = (rgba1[idx1], rgba1[idx1 + 1], rgba1[idx1 + 2], rgba1[idx1 + 3])
                p2 = (rgba2[idx2], rgba2[idx2 + 1], rgba2[idx2 + 2], rgba2[idx2 + 3])

                orig_alphas.add(p1[3])
                mod_alphas.add(p2[3])

                deltas = [abs(p1[c] - p2[c]) for c in range(4)]
                cur_max = max(deltas)
                if cur_max > 0:
                    modified_pixels += 1
                    if cur_max > max_delta:
                        max_delta = cur_max
                    if x < min_x:
                        min_x = x
                    if x > max_x:
                        max_x = x
                    if y < min_y:
                        min_y = y
                    if y > max_y:
                        max_y = y

        bbox = (min_x, min_y, max_x, max_y) if modified_pixels > 0 else None
        mod_pct = (modified_pixels / total_pixels * 100.0) if total_pixels > 0 else 0.0

        # Alpha integrity check: did original have smooth alpha that got crushed into binary?
        orig_translucent = any(0 < a < 255 for a in orig_alphas)
        mod_translucent = any(0 < a < 255 for a in mod_alphas)
        alpha_preserved = True
        if orig_translucent and not mod_translucent and modified_pixels > 0:
            alpha_preserved = False
            warnings.append("Multi-level alpha gradients in original were crushed into binary transparency.")

        return TextureDiffReport(
            orig_dims=(w1, h1),
            mod_dims=(w2, h2),
            dimensions_match=dims_match,
            orig_format=fmt1,
            mod_format=fmt2,
            formats_match=fmts_match,
            total_pixels=total_pixels,
            modified_pixel_count=modified_pixels,
            modified_pixel_pct=mod_pct,
            max_delta=max_delta,
            alpha_preserved=alpha_preserved,
            bounding_box=bbox,
            warnings=warnings,
        )

    @classmethod
    def render_ascii(cls, file_or_data: Union[str, bytes], max_width: int = 40) -> str:
        """
        Generates an ASCII visualization of the texture for terminal inspections.
        """
        data = cls._read_data(file_or_data)
        meta = cls._load_rgba_and_meta(data)
        rgba, w, h = meta[0], meta[1], meta[2]

        if not rgba or w <= 0 or h <= 0:
            return "[Empty or unreadable texture]"

        tw = min(w, max_width)
        th = max(1, int(h * (tw / w) * 0.5))

        ascii_chars = " .:-=+*#%@"
        lines = []
        for ty in range(th):
            line = []
            for tx in range(tw):
                src_x = int(tx * w / tw)
                src_y = int(ty * h / th)
                idx = (src_y * w + src_x) * 4
                r = rgba[idx]
                g = rgba[idx + 1]
                b = rgba[idx + 2]
                a = rgba[idx + 3]
                if a < 32:
                    line.append(" ")
                else:
                    lum = (r * 299 + g * 587 + b * 114) // 1000
                    lum = lum * a // 255
                    char_idx = lum * (len(ascii_chars) - 1) // 255
                    line.append(ascii_chars[char_idx])
            lines.append("".join(line))
        return "\n".join(lines)
