"""
miorom.graphics.tile_dedup
~~~~~~~~~~~~~~~~~~~~~~~~~~
Tile deduplication and VRAM optimizer for retro 2D consoles.
Analyzes 8x8 tile buffers, identifies identical tiles and mirror-flipped variants
(Horizontal, Vertical, and HV flip), and generates an optimized tile library with
remapped nametable coordinates to conserve limited VRAM and ROM bank space.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.result import MioRomResult


@dataclass
class DeduplicatedTileEntry(MioRomResult):
    """Mapping entry relating an original tile position to its deduplicated target."""
    orig_index: int
    unique_index: int
    flip_h: bool = False
    flip_v: bool = False

    def to_nametable_word_snes(self, palette: int = 0, priority: int = 0) -> int:
        """Encodes entry into a standard 16-bit SNES nametable word."""
        word = self.unique_index & 0x03FF
        word |= (palette & 0x07) << 10
        word |= (priority & 0x01) << 13
        if self.flip_h:
            word |= 1 << 14
        if self.flip_v:
            word |= 1 << 15
        return word

    def to_nametable_word_genesis(self, palette: int = 0, priority: int = 0) -> int:
        """Encodes entry into a standard 16-bit Sega Genesis nametable word."""
        word = self.unique_index & 0x07FF
        if self.flip_h:
            word |= 1 << 11
        if self.flip_v:
            word |= 1 << 12
        word |= (palette & 0x03) << 13
        word |= (priority & 0x01) << 15
        return word

    def to_gbc_map_entry(self, palette: int = 0, vram_bank: int = 0, priority: int = 0) -> Tuple[int, int]:
        """Encodes entry into Game Boy Color (tile_index, attr_byte) tuple."""
        attr = palette & 0x07
        attr |= (vram_bank & 0x01) << 3
        if self.flip_h:
            attr |= 1 << 5
        if self.flip_v:
            attr |= 1 << 6
        attr |= (priority & 0x01) << 7
        return self.unique_index & 0xFF, attr

    def to_gba_map_entry(self, palette: int = 0) -> int:
        """Encodes entry into a standard 16-bit GBA text background entry."""
        word = self.unique_index & 0x03FF
        if self.flip_h:
            word |= 1 << 10
        if self.flip_v:
            word |= 1 << 11
        word |= (palette & 0x0F) << 12
        return word


@dataclass
class TileDedupResult(MioRomResult):
    """Contains optimized tile arrays, mapping descriptors, and compression statistics."""
    unique_tiles: List[bytes]
    entries: List[DeduplicatedTileEntry]
    original_count: int
    unique_count: int
    saved_count: int
    compression_ratio: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class TileDeduplicator:
    """
    Optimizes 8x8 tile arrays by identifying exact duplicates and symmetrical flipped copies.
    """

    @staticmethod
    def flip_horizontal_8x8(tile_pixels: bytes) -> bytes:
        """Flips an 8x8 64-byte pixel array horizontally."""
        out = bytearray(64)
        for y in range(8):
            row_start = y * 8
            for x in range(8):
                out[row_start + x] = tile_pixels[row_start + (7 - x)]
        return bytes(out)

    @staticmethod
    def flip_vertical_8x8(tile_pixels: bytes) -> bytes:
        """Flips an 8x8 64-byte pixel array vertically."""
        out = bytearray(64)
        for y in range(8):
            src_row_start = (7 - y) * 8
            dst_row_start = y * 8
            out[dst_row_start : dst_row_start + 8] = tile_pixels[src_row_start : src_row_start + 8]
        return bytes(out)

    @classmethod
    def flip_hv_8x8(cls, tile_pixels: bytes) -> bytes:
        """Flips an 8x8 64-byte pixel array both horizontally and vertically."""
        return cls.flip_vertical_8x8(cls.flip_horizontal_8x8(tile_pixels))

    @classmethod
    def deduplicate(
        cls,
        tiles: Sequence[bytes],
        allow_flip_h: bool = True,
        allow_flip_v: bool = True,
        preserve_blank_at_zero: bool = True,
    ) -> TileDedupResult:
        """
        Deduplicates a sequence of 64-byte 8x8 tile pixel buffers.
        Supports horizontal and vertical flip matching.
        """
        if not tiles:
            return TileDedupResult(
                unique_tiles=[],
                entries=[],
                original_count=0,
                unique_count=0,
                saved_count=0,
                compression_ratio=1.0,
            )

        unique_tiles: List[bytes] = []
        entries: List[DeduplicatedTileEntry] = []

        tile_lookup: Dict[bytes, Tuple[int, bool, bool]] = {}

        blank_tile = bytes(64)
        if preserve_blank_at_zero:
            unique_tiles.append(blank_tile)
            tile_lookup[blank_tile] = (0, False, False)

        for idx, tile in enumerate(tiles):
            if len(tile) != 64:
                raise ValueError(f"Tile at index {idx} must be exactly 64 bytes (8x8 pixels), got {len(tile)}")

            if tile in tile_lookup:
                uidx, fh, fv = tile_lookup[tile]
                entries.append(DeduplicatedTileEntry(orig_index=idx, unique_index=uidx, flip_h=fh, flip_v=fv))
                continue

            found = False

            if allow_flip_h:
                th = cls.flip_horizontal_8x8(tile)
                if th in tile_lookup and not tile_lookup[th][1] and not tile_lookup[th][2]:
                    base_uidx = tile_lookup[th][0]
                    entries.append(DeduplicatedTileEntry(orig_index=idx, unique_index=base_uidx, flip_h=True, flip_v=False))
                    found = True

            if not found and allow_flip_v:
                tv = cls.flip_vertical_8x8(tile)
                if tv in tile_lookup and not tile_lookup[tv][1] and not tile_lookup[tv][2]:
                    base_uidx = tile_lookup[tv][0]
                    entries.append(DeduplicatedTileEntry(orig_index=idx, unique_index=base_uidx, flip_h=False, flip_v=True))
                    found = True

            if not found and allow_flip_h and allow_flip_v:
                thv = cls.flip_hv_8x8(tile)
                if thv in tile_lookup and not tile_lookup[thv][1] and not tile_lookup[thv][2]:
                    base_uidx = tile_lookup[thv][0]
                    entries.append(DeduplicatedTileEntry(orig_index=idx, unique_index=base_uidx, flip_h=True, flip_v=True))
                    found = True

            if not found:
                new_idx = len(unique_tiles)
                unique_tiles.append(tile)
                tile_lookup[tile] = (new_idx, False, False)
                entries.append(DeduplicatedTileEntry(orig_index=idx, unique_index=new_idx, flip_h=False, flip_v=False))

        orig_cnt = len(tiles)
        uniq_cnt = len(unique_tiles)
        saved_cnt = orig_cnt - uniq_cnt
        ratio = uniq_cnt / orig_cnt if orig_cnt > 0 else 1.0

        return TileDedupResult(
            unique_tiles=unique_tiles,
            entries=entries,
            original_count=orig_cnt,
            unique_count=uniq_cnt,
            saved_count=saved_cnt,
            compression_ratio=ratio,
        )

    @classmethod
    def deduplicate_raw_bpp(
        cls,
        raw_tile_data: bytes,
        bpp: int = 4,
        format: Optional[str] = None,
        allow_flip_h: bool = True,
        allow_flip_v: bool = True,
    ) -> Tuple[bytes, List[DeduplicatedTileEntry]]:
        """
        Deduplicates raw planar or packed tile binary data directly.
        Converts to pixel arrays, optimizes, and encodes back into raw bytes.
        """
        from miorom.graphics.planar import PlanarTileCodec

        fmt = format or (f"{bpp}bpp" if bpp != 4 else "4bpp_planar")
        tile_size = PlanarTileCodec.get_tile_size(fmt)
        if len(raw_tile_data) % tile_size != 0:
            raise ValueError(f"Tile buffer length {len(raw_tile_data)} is not a multiple of tile size {tile_size}")

        num_tiles = len(raw_tile_data) // tile_size
        decoded_tiles: List[bytes] = []

        for i in range(num_tiles):
            chunk = raw_tile_data[i * tile_size : (i + 1) * tile_size]
            pixels = bytes(PlanarTileCodec.decode_tile(chunk, format=fmt))
            decoded_tiles.append(pixels)

        res = cls.deduplicate(decoded_tiles, allow_flip_h=allow_flip_h, allow_flip_v=allow_flip_v, preserve_blank_at_zero=False)

        encoded_out = bytearray()
        for tile in res.unique_tiles:
            encoded_out.extend(PlanarTileCodec.encode_tile(tile, format=fmt))

        return bytes(encoded_out), res.entries
