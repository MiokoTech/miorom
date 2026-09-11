"""
miorom.graphics.tilemap_dissector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Menu Tilemap and Nametable Dissector for Fan Translation Reverse Engineering.

Provides structured scanning, visual text-grid extraction, dynamic label splicing,
and layout relocation for tilemap-based game menus (SNES, Genesis, GBA, NDS, NES, GB).
"""

from dataclasses import dataclass, field
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.errors import ParseError
from miorom.graphics.tilemap import Tilemap, TilemapEntry
from miorom.result import MioRomResult
from miorom.text.charmap import CharMap


@dataclass
class TilemapTextRun(MioRomResult):
    """
    Represents a contiguous run of text tiles discovered inside a tilemap.
    """
    row: int
    col: int
    direction: str  # "horizontal" or "vertical"
    tile_indices: List[int]
    decoded_text: str
    palette_bank: int = 0
    flip_x: bool = False
    flip_y: bool = False
    max_available_tiles: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serializes text run to dictionary for JSON export."""
        return {
            "row": self.row,
            "col": self.col,
            "direction": self.direction,
            "tile_indices": list(self.tile_indices),
            "decoded_text": self.decoded_text,
            "palette_bank": self.palette_bank,
            "flip_x": self.flip_x,
            "flip_y": self.flip_y,
            "max_available_tiles": self.max_available_tiles,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TilemapTextRun":
        """Deserializes text run from dictionary."""
        return cls(
            row=data["row"],
            col=data["col"],
            direction=data.get("direction", "horizontal"),
            tile_indices=list(data["tile_indices"]),
            decoded_text=data["decoded_text"],
            palette_bank=data.get("palette_bank", 0),
            flip_x=data.get("flip_x", False),
            flip_y=data.get("flip_y", False),
            max_available_tiles=data.get("max_available_tiles", len(data["tile_indices"])),
        )


@dataclass
class TilemapMenuBox(MioRomResult):
    """
    Represents a rectangular menu window or dialog box in a tilemap containing text runs.
    """
    top: int
    left: int
    width: int
    height: int
    items: List[TilemapTextRun] = field(default_factory=list)


class TilemapDissector:
    """
    Reverse engineering tool for analyzing and modifying tilemap-based menu layouts.
    """

    @classmethod
    def _decode_tile(
        cls,
        tile_index: int,
        charmap: CharMap,
        base_tile_index: int = 0,
    ) -> Optional[str]:
        """
        Attempts to decode a single tile index using the provided CharMap.
        """
        code = tile_index - base_tile_index
        if code < 0:
            return None

        # Check 1-byte mapping
        if code <= 0xFF:
            b1 = bytes([code])
            if b1 in charmap.byte_to_char:
                return charmap.byte_to_char[b1]

        # Check 2-byte big-endian mapping
        if code <= 0xFFFF:
            b2_be = code.to_bytes(2, "big")
            if b2_be in charmap.byte_to_char:
                return charmap.byte_to_char[b2_be]
            b2_le = code.to_bytes(2, "little")
            if b2_le in charmap.byte_to_char:
                return charmap.byte_to_char[b2_le]

        return None

    @classmethod
    def scan_text_runs(
        cls,
        tilemap: Tilemap,
        charmap: CharMap,
        min_length: int = 2,
        direction: str = "horizontal",
        base_tile_index: int = 0,
        blank_tile_indices: Optional[Sequence[int]] = None,
    ) -> List[TilemapTextRun]:
        """
        Scans a tilemap for contiguous runs of text characters.

        Args:
            tilemap: Target Tilemap instance.
            charmap: Character encoding table.
            min_length: Minimum number of continuous text tiles to form a valid run.
            direction: 'horizontal' (row-by-row) or 'vertical' (col-by-col).
            base_tile_index: Offset subtracted from tile_index before charmap lookup.
            blank_tile_indices: Tile indices considered empty space / padding. Defaults to [0].
        """
        blanks = set(blank_tile_indices if blank_tile_indices is not None else [0])
        runs: List[TilemapTextRun] = []

        if direction == "horizontal":
            for r in range(tilemap.height):
                c = 0
                while c < tilemap.width:
                    entry = tilemap.get_entry(c, r)
                    char = cls._decode_tile(entry.tile_index, charmap, base_tile_index)

                    if char is not None and entry.tile_index not in blanks:
                        start_c = c
                        run_tiles = [entry.tile_index]
                        run_chars = [char]
                        first_pal = entry.palette_bank
                        first_fx = entry.flip_x
                        first_fy = entry.flip_y
                        c += 1

                        while c < tilemap.width:
                            next_entry = tilemap.get_entry(c, r)
                            next_char = cls._decode_tile(next_entry.tile_index, charmap, base_tile_index)
                            if next_char is not None and next_entry.tile_index not in blanks:
                                run_tiles.append(next_entry.tile_index)
                                run_chars.append(next_char)
                                c += 1
                            else:
                                break

                        # Count trailing blank / available tiles
                        available_c = c
                        extra_padding = 0
                        while available_c < tilemap.width:
                            check_entry = tilemap.get_entry(available_c, r)
                            if check_entry.tile_index in blanks:
                                extra_padding += 1
                                available_c += 1
                            else:
                                break

                        if len(run_tiles) >= min_length:
                            runs.append(
                                TilemapTextRun(
                                    row=r,
                                    col=start_c,
                                    direction="horizontal",
                                    tile_indices=run_tiles,
                                    decoded_text="".join(run_chars),
                                    palette_bank=first_pal,
                                    flip_x=first_fx,
                                    flip_y=first_fy,
                                    max_available_tiles=len(run_tiles) + extra_padding,
                                )
                            )
                    else:
                        c += 1

        elif direction == "vertical":
            for c in range(tilemap.width):
                r = 0
                while r < tilemap.height:
                    entry = tilemap.get_entry(c, r)
                    char = cls._decode_tile(entry.tile_index, charmap, base_tile_index)

                    if char is not None and entry.tile_index not in blanks:
                        start_r = r
                        run_tiles = [entry.tile_index]
                        run_chars = [char]
                        first_pal = entry.palette_bank
                        first_fx = entry.flip_x
                        first_fy = entry.flip_y
                        r += 1

                        while r < tilemap.height:
                            next_entry = tilemap.get_entry(c, r)
                            next_char = cls._decode_tile(next_entry.tile_index, charmap, base_tile_index)
                            if next_char is not None and next_entry.tile_index not in blanks:
                                run_tiles.append(next_entry.tile_index)
                                run_chars.append(next_char)
                                r += 1
                            else:
                                break

                        # Count trailing blank tiles down the column
                        available_r = r
                        extra_padding = 0
                        while available_r < tilemap.height:
                            check_entry = tilemap.get_entry(c, available_r)
                            if check_entry.tile_index in blanks:
                                extra_padding += 1
                                available_r += 1
                            else:
                                break

                        if len(run_tiles) >= min_length:
                            runs.append(
                                TilemapTextRun(
                                    row=start_r,
                                    col=c,
                                    direction="vertical",
                                    tile_indices=run_tiles,
                                    decoded_text="".join(run_chars),
                                    palette_bank=first_pal,
                                    flip_x=first_fx,
                                    flip_y=first_fy,
                                    max_available_tiles=len(run_tiles) + extra_padding,
                                )
                            )
                    else:
                        r += 1
        else:
            raise ValueError(f"Unknown direction '{direction}'. Must be 'horizontal' or 'vertical'.")

        return runs

    @classmethod
    def export_text_grid(
        cls,
        tilemap: Tilemap,
        charmap: CharMap,
        base_tile_index: int = 0,
        blank_char: str = ".",
    ) -> str:
        """
        Renders a 2D ASCII/Unicode visualization of the tilemap text contents.
        Unmapped or blank tiles are represented by blank_char.
        """
        lines = []
        for r in range(tilemap.height):
            row_chars = []
            for c in range(tilemap.width):
                entry = tilemap.get_entry(c, r)
                char = cls._decode_tile(entry.tile_index, charmap, base_tile_index)
                if char is not None and char.strip():
                    row_chars.append(char[0])  # First glyph character
                else:
                    row_chars.append(blank_char)
            lines.append("".join(row_chars))
        return "\n".join(lines)

    @classmethod
    def splice_label(
        cls,
        tilemap: Tilemap,
        row: int,
        col: int,
        new_text: str,
        charmap: CharMap,
        base_tile_index: int = 0,
        palette_bank: Optional[int] = None,
        pad_tile: int = 0,
        max_width: Optional[int] = None,
        align: str = "left",
    ) -> Tilemap:
        """
        Replaces text tiles starting at (row, col) with encoded new_text.

        Args:
            tilemap: Tilemap to modify (modified in-place and returned).
            row: Starting row index.
            col: Starting column index.
            new_text: String to inject.
            charmap: Character map table.
            base_tile_index: Added to encoded byte value to determine tile index.
            palette_bank: Palette bank to set (preserves existing if None).
            pad_tile: Tile index used to clear residual old tiles or for alignment padding.
            max_width: Maximum allowed width in tiles.
            align: 'left', 'center', or 'right'.
        """
        # Encode characters to tile indices
        new_tiles: List[int] = []
        for ch in new_text:
            if ch in charmap.char_to_byte:
                raw_b = charmap.char_to_byte[ch]
                code = int.from_bytes(raw_b, "big")
                new_tiles.append(base_tile_index + code)
            else:
                new_tiles.append(pad_tile)

        text_len = len(new_tiles)

        if max_width is not None and text_len > max_width:
            raise ValueError(
                f"New text '{new_text}' length ({text_len} tiles) exceeds max_width ({max_width} tiles)."
            )

        target_span = max_width if max_width is not None else text_len

        # Check boundary bounds
        if col + target_span > tilemap.width or row >= tilemap.height:
            raise IndexError(
                f"Splice span ({col} + {target_span}) exceeds tilemap dimensions ({tilemap.width}x{tilemap.height})."
            )

        # Determine alignment offsets
        if align == "center":
            left_pad = (target_span - text_len) // 2
            right_pad = target_span - text_len - left_pad
        elif align == "right":
            left_pad = target_span - text_len
            right_pad = 0
        else:  # left
            left_pad = 0
            right_pad = target_span - text_len

        # Write left padding
        current_col = col
        for _ in range(left_pad):
            orig_entry = tilemap.get_entry(current_col, row)
            pal = palette_bank if palette_bank is not None else orig_entry.palette_bank
            tilemap.set_entry(
                current_col,
                row,
                TilemapEntry(tile_index=pad_tile, palette_bank=pal, priority=orig_entry.priority),
            )
            current_col += 1

        # Write text tiles
        for t_idx in new_tiles:
            orig_entry = tilemap.get_entry(current_col, row)
            pal = palette_bank if palette_bank is not None else orig_entry.palette_bank
            tilemap.set_entry(
                current_col,
                row,
                TilemapEntry(tile_index=t_idx, palette_bank=pal, priority=orig_entry.priority),
            )
            current_col += 1

        # Write right padding
        for _ in range(right_pad):
            orig_entry = tilemap.get_entry(current_col, row)
            pal = palette_bank if palette_bank is not None else orig_entry.palette_bank
            tilemap.set_entry(
                current_col,
                row,
                TilemapEntry(tile_index=pad_tile, palette_bank=pal, priority=orig_entry.priority),
            )
            current_col += 1

        return tilemap

    @classmethod
    def extract_menu_box(
        cls,
        tilemap: Tilemap,
        charmap: CharMap,
        top: int,
        left: int,
        width: int,
        height: int,
        base_tile_index: int = 0,
        blank_tile_indices: Optional[Sequence[int]] = None,
    ) -> TilemapMenuBox:
        """
        Extracts a rectangular sub-region and analyzes all horizontal text runs within it.
        """
        sub = tilemap.submap(left, top, width, height)
        sub_runs = cls.scan_text_runs(
            sub,
            charmap=charmap,
            min_length=1,
            direction="horizontal",
            base_tile_index=base_tile_index,
            blank_tile_indices=blank_tile_indices,
        )

        # Relocate coordinates back to parent tilemap
        box_items: List[TilemapTextRun] = []
        for r in sub_runs:
            box_items.append(
                TilemapTextRun(
                    row=top + r.row,
                    col=left + r.col,
                    direction="horizontal",
                    tile_indices=r.tile_indices,
                    decoded_text=r.decoded_text,
                    palette_bank=r.palette_bank,
                    flip_x=r.flip_x,
                    flip_y=r.flip_y,
                    max_available_tiles=r.max_available_tiles,
                )
            )

        return TilemapMenuBox(top=top, left=left, width=width, height=height, items=box_items)

    @classmethod
    def clear_region(
        cls,
        tilemap: Tilemap,
        row: int,
        col: int,
        width: int,
        height: int,
        clear_tile: int = 0,
        palette_bank: int = 0,
    ) -> None:
        """
        Fills a rectangular region with clear_tile.
        """
        for r in range(row, row + height):
            for c in range(col, col + width):
                if 0 <= r < tilemap.height and 0 <= c < tilemap.width:
                    tilemap.set_entry(c, r, TilemapEntry(tile_index=clear_tile, palette_bank=palette_bank))

    @classmethod
    def export_layout_json(cls, runs: Sequence[TilemapTextRun]) -> str:
        """
        Exports a list of TilemapTextRun to formatted JSON string.
        """
        data = [r.to_dict() for r in runs]
        return json.dumps(data, indent=2, ensure_ascii=False)

    @classmethod
    def import_layout_json(cls, json_str: str) -> List[TilemapTextRun]:
        """
        Parses TilemapTextRun list from JSON string.
        """
        data = json.loads(json_str)
        return [TilemapTextRun.from_dict(item) for item in data]

    @classmethod
    def apply_layout_dict(
        cls,
        tilemap: Tilemap,
        translations: List[Dict[str, Any]],
        charmap: CharMap,
        base_tile_index: int = 0,
        pad_tile: int = 0,
    ) -> Tilemap:
        """
        Applies batch translation dictionary items to the tilemap.
        Each item in translations must have: 'row', 'col', 'new_text', and optionally 'max_width', 'align'.
        """
        for item in translations:
            row = item["row"]
            col = item["col"]
            new_text = item.get("new_text", item.get("decoded_text", ""))
            max_width = item.get("max_width", item.get("max_available_tiles"))
            align = item.get("align", "left")
            pal = item.get("palette_bank")
            cls.splice_label(
                tilemap=tilemap,
                row=row,
                col=col,
                new_text=new_text,
                charmap=charmap,
                base_tile_index=base_tile_index,
                palette_bank=pal,
                pad_tile=pad_tile,
                max_width=max_width,
                align=align,
            )
        return tilemap
