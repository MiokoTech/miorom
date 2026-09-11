"""
miorom.graphics.font_dissector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Reverse Engineering Font Bank Scanner, Glyph Extractor, and VWF Width Table Hunter.

Discovers uncompressed 1bpp, 2bpp, and 4bpp font sheets in retro ROM dumps
(NES, SNES, Game Boy, GBA, Genesis, PS1), measures natural glyph metrics,
correlates companion proportional font width arrays, and supports roundtrip
export and injection for ROM hacking and fan translation workflows.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import json
import math
import struct
from typing import Dict, List, Optional, Sequence, Tuple, Union

from miorom.errors import ParseError
from miorom.graphics.planar import PlanarTileCodec
from miorom.result import MioRomResult


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class FontGeometry(MioRomResult):
    """
    Geometry, bit-depth, and tile layout specification for a font bank.
    """
    width: int
    height: int
    bpp: int
    format_name: str
    bytes_per_glyph: int

    @property
    def total_pixels(self) -> int:
        return self.width * self.height


@dataclass
class DissectedGlyph(MioRomResult):
    """
    A single decoded font glyph with measured bounding box and advance metrics.
    """
    index: int
    offset: int
    raw_bytes: bytes
    pixels: List[int]  # Row-major indexed pixel values
    bounding_box: Tuple[int, int, int, int]  # (min_x, min_y, max_x, max_y)
    measured_width: int  # Natural pixel advance width
    measured_height: int  # Natural pixel height

    @property
    def is_blank(self) -> bool:
        """True if the glyph contains no active pixels (e.g. space character)."""
        return all(p == 0 for p in self.pixels)


@dataclass
class WidthTableCandidate(MioRomResult):
    """
    Candidate proportional font width array discovered in binary ROM data.
    """
    offset: int
    entry_count: int
    entry_size: int
    widths: List[int]
    min_width: int
    max_width: int
    average_width: float
    confidence: float

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"


@dataclass
class FontCandidate(MioRomResult):
    """
    A high-confidence font bank discovered in binary ROM data.
    """
    offset: int
    glyph_count: int
    geometry: FontGeometry
    confidence: float
    glyphs: List[DissectedGlyph]
    correlated_width_table: Optional[WidthTableCandidate] = None

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"

    @property
    def total_bytes(self) -> int:
        return self.glyph_count * self.geometry.bytes_per_glyph

    def export_sheet_png(self, columns: int = 16) -> bytes:
        """
        Renders all glyphs into a 2D composite spritesheet PNG image (pure Python).

        Args:
            columns: Number of glyphs per row in the composite sheet.
        """
        if not self.glyphs:
            return b""

        w = self.geometry.width
        h = self.geometry.height
        glyph_count = len(self.glyphs)
        rows = (glyph_count + columns - 1) // columns

        sheet_w = columns * w
        sheet_h = rows * h
        sheet_pixels = bytearray(sheet_w * sheet_h)

        max_val = (1 << self.geometry.bpp) - 1
        if max_val == 0:
            max_val = 1

        for i, glyph in enumerate(self.glyphs):
            col = i % columns
            row = i // columns
            gx = col * w
            gy = row * h

            for py in range(h):
                for px in range(w):
                    val = glyph.pixels[py * w + px]
                    if val > 0:
                        gray = int((val / max_val) * 255)
                    else:
                        gray = 0
                    sheet_pixels[(gy + py) * sheet_w + (gx + px)] = gray

        from miorom.text.bmfont import PNGCodec
        return PNGCodec.encode_grayscale(sheet_w, sheet_h, bytes(sheet_pixels))

    def export_metrics_json(self) -> str:
        """
        Exports font geometry, glyph bounding boxes, and measured metrics to JSON.
        """
        data = {
            "font_offset": self.offset_hex,
            "glyph_count": self.glyph_count,
            "geometry": {
                "width": self.geometry.width,
                "height": self.geometry.height,
                "bpp": self.geometry.bpp,
                "format_name": self.geometry.format_name,
                "bytes_per_glyph": self.geometry.bytes_per_glyph,
            },
            "confidence": self.confidence,
            "width_table": self.correlated_width_table.widths if self.correlated_width_table else None,
            "glyphs": [
                {
                    "index": g.index,
                    "offset": f"0x{g.offset:08X}",
                    "is_blank": g.is_blank,
                    "bounding_box": list(g.bounding_box),
                    "measured_width": g.measured_width,
                    "measured_height": g.measured_height,
                }
                for g in self.glyphs
            ],
        }
        return json.dumps(data, indent=2)


# ============================================================================
# Font Dissector Engine
# ============================================================================

class FontDissector:
    """
    Reverse Engineering Font Bank Scanner, Glyph Extractor, and VWF Width Table Hunter.
    Automates discovering, extracting, and injecting retro game fonts.
    """

    # Supported (width, height, bpp, format_name) definitions
    SUPPORTED_GEOMETRIES: Tuple[Tuple[int, int, int, str], ...] = (
        (8, 8, 1, "1bpp_linear"),
        (8, 8, 2, "gb_2bpp"),
        (8, 8, 2, "snes_2bpp"),
        (8, 8, 4, "genesis_4bpp"),
        (8, 8, 4, "gba_4bpp"),
        (8, 16, 1, "1bpp_linear"),
        (16, 16, 1, "1bpp_linear"),
    )

    @classmethod
    def get_bytes_per_glyph(cls, width: int, height: int, bpp: int, format_name: str) -> int:
        """Calculates the byte storage size of a single glyph."""
        if format_name == "1bpp_linear":
            return (width * height) // 8
        if width == 8 and height == 8:
            return PlanarTileCodec.get_tile_size(format_name)
        # Multi-tile calculation
        tiles_x = width // 8
        tiles_y = height // 8
        single_tile_size = PlanarTileCodec.get_tile_size(format_name)
        return tiles_x * tiles_y * single_tile_size

    @classmethod
    def decode_glyph_pixels(
        cls,
        data: bytes,
        geometry: FontGeometry,
    ) -> List[int]:
        """
        Decodes raw bytes of a single glyph into row-major indexed pixels.
        """
        w, h, bpp, fmt = geometry.width, geometry.height, geometry.bpp, geometry.format_name

        if fmt == "1bpp_linear":
            pixels = [0] * (w * h)
            if w == 8:
                # 8 pixels wide: 1 byte per row
                for y in range(h):
                    b = data[y]
                    for x in range(8):
                        pixels[y * 8 + x] = (b >> (7 - x)) & 1
            elif w == 16:
                # 16 pixels wide: 2 bytes per row (MSB first)
                for y in range(h):
                    b0 = data[y * 2]
                    b1 = data[y * 2 + 1]
                    for x in range(8):
                        pixels[y * 16 + x] = (b0 >> (7 - x)) & 1
                    for x in range(8):
                        pixels[y * 16 + 8 + x] = (b1 >> (7 - x)) & 1
            return pixels

        # Planar / Chunky 8x8 tiles
        if w == 8 and h == 8:
            return PlanarTileCodec.decode_tile(data, fmt)

        # Multi-tile 16x16
        if w == 16 and h == 16:
            tile_sz = PlanarTileCodec.get_tile_size(fmt)
            t_tl = PlanarTileCodec.decode_tile(data[0 : tile_sz], fmt)
            t_tr = PlanarTileCodec.decode_tile(data[tile_sz : tile_sz * 2], fmt)
            t_bl = PlanarTileCodec.decode_tile(data[tile_sz * 2 : tile_sz * 3], fmt)
            t_br = PlanarTileCodec.decode_tile(data[tile_sz * 3 : tile_sz * 4], fmt)
            pixels = [0] * 256
            for y in range(8):
                for x in range(8):
                    pixels[y * 16 + x] = t_tl[y * 8 + x]
                    pixels[y * 16 + 8 + x] = t_tr[y * 8 + x]
                    pixels[(y + 8) * 16 + x] = t_bl[y * 8 + x]
                    pixels[(y + 8) * 16 + 8 + x] = t_br[y * 8 + x]
            return pixels

        raise ParseError(f"Unsupported geometry for decode: {w}x{h} ({fmt})")

    @classmethod
    def encode_glyph_pixels(
        cls,
        pixels: Sequence[int],
        geometry: FontGeometry,
    ) -> bytes:
        """
        Encodes row-major indexed pixels into raw binary bytes for this geometry.
        """
        w, h, bpp, fmt = geometry.width, geometry.height, geometry.bpp, geometry.format_name

        if fmt == "1bpp_linear":
            out = bytearray()
            if w == 8:
                for y in range(h):
                    row_val = 0
                    for x in range(8):
                        if pixels[y * 8 + x] & 1:
                            row_val |= (1 << (7 - x))
                    out.append(row_val)
            elif w == 16:
                for y in range(h):
                    b0, b1 = 0, 0
                    for x in range(8):
                        if pixels[y * 16 + x] & 1:
                            b0 |= (1 << (7 - x))
                    for x in range(8):
                        if pixels[y * 16 + 8 + x] & 1:
                            b1 |= (1 << (7 - x))
                    out.extend([b0, b1])
            return bytes(out)

        if w == 8 and h == 8:
            return PlanarTileCodec.encode_tile(pixels, fmt)

        if w == 16 and h == 16:
            # 2x2 tiles
            tl = [pixels[y * 16 + x] for y in range(8) for x in range(8)]
            tr = [pixels[y * 16 + 8 + x] for y in range(8) for x in range(8)]
            bl = [pixels[(y + 8) * 16 + x] for y in range(8) for x in range(8)]
            br = [pixels[(y + 8) * 16 + 8 + x] for y in range(8) for x in range(8)]
            out = bytearray()
            out.extend(PlanarTileCodec.encode_tile(tl, fmt))
            out.extend(PlanarTileCodec.encode_tile(tr, fmt))
            out.extend(PlanarTileCodec.encode_tile(bl, fmt))
            out.extend(PlanarTileCodec.encode_tile(br, fmt))
            return bytes(out)

        raise ParseError(f"Unsupported geometry for encode: {w}x{h} ({fmt})")

    @classmethod
    def _measure_glyph(
        cls,
        pixels: Sequence[int],
        width: int,
        height: int,
    ) -> Tuple[Tuple[int, int, int, int], int, int]:
        """
        Computes bounding box (min_x, min_y, max_x, max_y) and natural advance dimensions.
        """
        active = [(x, y) for y in range(height) for x in range(width) if pixels[y * width + x] > 0]
        if not active:
            # Empty / Space glyph
            space_width = max(2, width // 2)
            return (0, 0, 0, 0), space_width, height

        xs = [pt[0] for pt in active]
        ys = [pt[1] for pt in active]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)

        bbox = (min_x, min_y, max_x, max_y)
        # Advance width: max_x + 1 or + 2 for natural tracking, bounded by width
        adv_w = min(width, max_x + 2)
        adv_h = max_y - min_y + 1
        return bbox, adv_w, adv_h

    @classmethod
    def _score_glyph_block(
        cls,
        glyphs: Sequence[DissectedGlyph],
        geometry: FontGeometry,
        raw_slice: bytes,
    ) -> float:
        """
        Evaluates heuristic font consistency score (0.0 to 1.0) for a candidate block.
        """
        total = len(glyphs)
        if total < 16:
            return 0.0

        # 1. Entropy calculation: font sheets typically have entropy in [1.0, 4.8]
        entropy = cls._calculate_entropy(raw_slice)
        if entropy < 0.8 or entropy > 5.8:
            return 0.0

        w = geometry.width
        h = geometry.height
        total_pixels = w * h

        valid_glyphs = 0
        blank_glyphs = 0
        margin_consistent_glyphs = 0

        for g in glyphs:
            active_count = sum(1 for p in g.pixels if p > 0)
            if active_count == 0:
                blank_glyphs += 1
                valid_glyphs += 1
                continue

            fill_ratio = active_count / total_pixels
            # Natural font glyphs have stroke fill ratio between 6% and 48%
            if 0.06 <= fill_ratio <= 0.48:
                valid_glyphs += 1

            # Check if top row or bottom row has blank margin
            top_empty = all(g.pixels[x] == 0 for x in range(w))
            bottom_empty = all(g.pixels[(h - 1) * w + x] == 0 for x in range(w))
            if top_empty or bottom_empty:
                margin_consistent_glyphs += 1

        valid_ratio = valid_glyphs / total
        margin_ratio = margin_consistent_glyphs / total

        # If too many blank glyphs (>25%), this is mostly padding
        if blank_glyphs / total > 0.25:
            return 0.0

        # Ensure glyph diversity (a font bank contains many distinct characters)
        unique_glyphs = len(set(tuple(g.pixels) for g in glyphs))
        if unique_glyphs < max(10, int(total * 0.40)):
            return 0.0

        # Cannot start with multiple consecutive blank tiles
        if len(glyphs) >= 2 and glyphs[0].is_blank and glyphs[1].is_blank:
            return 0.0

        # Base confidence calculation
        if valid_ratio < 0.70:
            return 0.0

        confidence = (valid_ratio * 0.5) + (margin_ratio * 0.3) + 0.2
        # Normalize between 0.0 and 1.0
        return min(0.99, max(0.0, confidence))

    @classmethod
    def _calculate_entropy(cls, data: bytes) -> float:
        """Calculates Shannon entropy in bits per byte."""
        if not data:
            return 0.0
        counts = Counter(data)
        total = len(data)
        ent = 0.0
        for count in counts.values():
            p = count / total
            ent -= p * math.log2(p)
        return ent

    @classmethod
    def scan_fonts(
        cls,
        data: bytes,
        min_glyphs: int = 32,
        max_bpp: int = 4,
        confidence_threshold: float = 0.70,
        step: int = 16,
    ) -> List[FontCandidate]:
        """
        Scans binary ROM buffer for candidate font banks across supported geometries.

        Args:
            data: Binary ROM buffer.
            min_glyphs: Minimum contiguous glyph count required for a font bank.
            max_bpp: Maximum bits per pixel to consider (1, 2, or 4).
            confidence_threshold: Minimum heuristic confidence score (0.0 to 1.0).
            step: Offset stepping increment in bytes.
        """
        candidates: List[FontCandidate] = []
        data_len = len(data)

        for w, h, bpp, fmt in cls.SUPPORTED_GEOMETRIES:
            if bpp > max_bpp:
                continue

            geom = FontGeometry(
                width=w,
                height=h,
                bpp=bpp,
                format_name=fmt,
                bytes_per_glyph=cls.get_bytes_per_glyph(w, h, bpp, fmt),
            )
            bpg = geom.bytes_per_glyph
            min_block_bytes = min_glyphs * bpg

            if data_len < min_block_bytes:
                continue

            pos = 0
            while pos <= data_len - min_block_bytes:
                # Fast reject leading padding or repetitive noise
                g0 = data[pos : pos + bpg]
                g1 = data[pos + bpg : pos + 2 * bpg]
                if g0 == g1:
                    # Consecutive identical tiles (either blank padding or noise fill)
                    pos += step
                    continue

                # Test a candidate block of min_glyphs
                block_slice = data[pos : pos + min_block_bytes]
                glyphs: List[DissectedGlyph] = []

                for g_idx in range(min_glyphs):
                    g_data = block_slice[g_idx * bpg : (g_idx + 1) * bpg]
                    pixels = cls.decode_glyph_pixels(g_data, geom)
                    bbox, adv_w, adv_h = cls._measure_glyph(pixels, w, h)
                    glyphs.append(
                        DissectedGlyph(
                            index=g_idx,
                            offset=pos + g_idx * bpg,
                            raw_bytes=g_data,
                            pixels=pixels,
                            bounding_box=bbox,
                            measured_width=adv_w,
                            measured_height=adv_h,
                        )
                    )

                # Validate initial glyph
                g0_pixels = glyphs[0].pixels
                g0_active = sum(1 for p in g0_pixels if p > 0)
                if g0_active > 0:
                    g0_fill = g0_active / (w * h)
                    g0_top_empty = all(g0_pixels[x] == 0 for x in range(w))
                    g0_bottom_empty = all(g0_pixels[(h - 1) * w + x] == 0 for x in range(w))
                    if not ((0.05 <= g0_fill <= 0.48) and (g0_top_empty or g0_bottom_empty)):
                        pos += bpg
                        continue

                score = cls._score_glyph_block(glyphs, geom, block_slice)
                if score >= confidence_threshold:
                    # Extend forward to discover the full font bank extent
                    ext_glyphs = list(glyphs)
                    cur_idx = min_glyphs
                    while pos + (cur_idx + 1) * bpg <= data_len:
                        next_g_data = data[pos + cur_idx * bpg : pos + (cur_idx + 1) * bpg]
                        next_pixels = cls.decode_glyph_pixels(next_g_data, geom)
                        bbox, adv_w, adv_h = cls._measure_glyph(next_pixels, w, h)
                        active_cnt = sum(1 for p in next_pixels if p > 0)
                        fill_ratio = active_cnt / (w * h)

                        is_blank = active_cnt == 0
                        top_empty = all(next_pixels[x] == 0 for x in range(w))
                        bottom_empty = all(next_pixels[(h - 1) * w + x] == 0 for x in range(w))
                        is_valid_glyph = (0.05 <= fill_ratio <= 0.48) and (top_empty or bottom_empty)

                        # Stop if not a valid font glyph
                        if not is_blank and not is_valid_glyph:
                            break
                        # Stop on repeating identical non-blank tiles (noise pattern)
                        if not is_blank and next_pixels == ext_glyphs[-1].pixels:
                            break
                        # Stop on multiple consecutive blank tiles (end of font bank)
                        if is_blank and ext_glyphs[-1].is_blank:
                            break

                        ext_glyphs.append(
                            DissectedGlyph(
                                index=cur_idx,
                                offset=pos + cur_idx * bpg,
                                raw_bytes=next_g_data,
                                pixels=next_pixels,
                                bounding_box=bbox,
                                measured_width=adv_w,
                                measured_height=adv_h,
                            )
                        )
                        cur_idx += 1

                    final_glyph_count = len(ext_glyphs)
                    final_slice = data[pos : pos + final_glyph_count * bpg]
                    final_score = cls._score_glyph_block(ext_glyphs, geom, final_slice)

                    # Correlate with companion width table
                    width_tables = cls.hunt_width_table(
                        data,
                        glyph_count=final_glyph_count,
                        max_glyph_width=w,
                        proximity_offset=pos,
                    )
                    top_wt = width_tables[0] if width_tables else None

                    candidate = FontCandidate(
                        offset=pos,
                        glyph_count=final_glyph_count,
                        geometry=geom,
                        confidence=round(final_score, 4),
                        glyphs=ext_glyphs,
                        correlated_width_table=top_wt,
                    )
                    candidates.append(candidate)

                    # Jump past the discovered bank
                    pos += final_glyph_count * bpg
                    continue

                pos += step

        # Sort candidates by confidence, then total glyphs
        candidates.sort(key=lambda c: (c.confidence, c.glyph_count), reverse=True)
        return candidates

    @classmethod
    def hunt_width_table(
        cls,
        data: bytes,
        glyph_count: int,
        max_glyph_width: int = 8,
        proximity_offset: Optional[int] = None,
        search_window: int = 65536,
    ) -> List[WidthTableCandidate]:
        """
        Scans for an array of 1-byte or 2-byte pixel widths matching glyph_count.

        Args:
            data: Binary ROM buffer.
            glyph_count: Expected number of entries in the width table.
            max_glyph_width: Maximum pixel width of a single character.
            proximity_offset: Anchor offset (e.g. font bank position) to prioritize nearby tables.
            search_window: Proximity search radius around proximity_offset.
        """
        if glyph_count < 16:
            return []

        candidates: List[WidthTableCandidate] = []
        data_len = len(data)

        # Determine search range
        if proximity_offset is not None:
            start_pos = max(0, proximity_offset - search_window)
            end_pos = min(data_len - glyph_count, proximity_offset + search_window)
        else:
            start_pos = 0
            end_pos = data_len - glyph_count

        # 1-byte width table scan
        for pos in range(start_pos, end_pos + 1):
            slice_bytes = data[pos : pos + glyph_count]

            # Width values must predominantly fall within [2, max_glyph_width]
            valid_count = 0
            total_w = 0
            for b in slice_bytes:
                if 2 <= b <= max_glyph_width:
                    valid_count += 1
                total_w += b

            valid_ratio = valid_count / glyph_count
            if valid_ratio >= 0.88:
                avg_w = total_w / glyph_count
                # Realistic VWF average width for retro games: 0.45*W to 0.85*W
                if 0.45 * max_glyph_width <= avg_w <= 0.85 * max_glyph_width:
                    # Calculate variance to ensure table has real character variation
                    variance = sum((b - avg_w) ** 2 for b in slice_bytes) / glyph_count
                    if variance >= 0.35:  # Not just a flat constant array
                        conf = min(0.99, 0.75 + (valid_ratio - 0.88) * 2.0)
                        candidates.append(
                            WidthTableCandidate(
                                offset=pos,
                                entry_count=glyph_count,
                                entry_size=1,
                                widths=list(slice_bytes),
                                min_width=min(slice_bytes),
                                max_width=max(slice_bytes),
                                average_width=round(avg_w, 2),
                                confidence=round(conf, 4),
                            )
                        )

        # Sort by proximity to anchor (if provided), then confidence
        if proximity_offset is not None:
            candidates.sort(key=lambda c: (abs(c.offset - proximity_offset), -c.confidence))
        else:
            candidates.sort(key=lambda c: c.confidence, reverse=True)

        return candidates

    @classmethod
    def auto_dissect(
        cls,
        data: bytes,
        min_glyphs: int = 32,
    ) -> Optional[FontCandidate]:
        """
        One-shot discovery entry point.
        Discovers the primary font bank and correlates its companion width table.
        """
        candidates = cls.scan_fonts(data=data, min_glyphs=min_glyphs)
        if not candidates:
            return None
        return candidates[0]

    @classmethod
    def inject_glyphs(
        cls,
        rom_data: Union[bytes, bytearray],
        candidate: FontCandidate,
        glyph_pixels: Dict[int, Sequence[int]],
    ) -> bytearray:
        """
        Re-encodes modified glyph pixel arrays and writes them into the ROM buffer.

        Args:
            rom_data: Target ROM buffer.
            candidate: FontCandidate containing destination offset and geometry.
            glyph_pixels: Mapping of glyph index to pixel array (length width*height).
        """
        buf = bytearray(rom_data)
        bpg = candidate.geometry.bytes_per_glyph
        base_offset = candidate.offset

        for idx, pixels in glyph_pixels.items():
            if idx < 0 or idx >= candidate.glyph_count:
                raise ValueError(f"Glyph index {idx} out of bounds (0..{candidate.glyph_count - 1})")

            encoded = cls.encode_glyph_pixels(pixels, candidate.geometry)
            write_pos = base_offset + idx * bpg
            buf[write_pos : write_pos + bpg] = encoded

        return buf

    @classmethod
    def inject_width_table(
        cls,
        rom_data: Union[bytes, bytearray],
        table_offset: int,
        widths: Sequence[int],
        entry_size: int = 1,
    ) -> bytearray:
        """
        Injects updated proportional font widths into the ROM buffer.

        Args:
            rom_data: Target ROM buffer.
            table_offset: Byte offset of the width table in ROM.
            widths: List of pixel widths to write.
            entry_size: Entry size in bytes (1 or 2).
        """
        buf = bytearray(rom_data)
        for i, w in enumerate(widths):
            pos = table_offset + (i * entry_size)
            if entry_size == 1:
                buf[pos] = min(255, max(0, w))
            elif entry_size == 2:
                buf[pos : pos + 2] = struct.pack("<H", min(65535, max(0, w)))
            else:
                raise ParseError("entry_size must be 1 or 2 bytes")

        return buf
