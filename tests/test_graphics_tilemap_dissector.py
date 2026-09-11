"""
Tests for miorom.graphics.tilemap_dissector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Verifies scanning, 2D text grid visualization, dynamic splicing with alignment/padding,
and JSON layout export/import for tilemap menu reverse engineering.
"""

import pytest
from miorom.graphics.tilemap import Tilemap, TilemapEntry
from miorom.graphics.tilemap_dissector import (
    TilemapDissector,
    TilemapTextRun,
    TilemapMenuBox,
)
from miorom.text.charmap import CharMap


@pytest.fixture
def sample_charmap() -> CharMap:
    """Creates a sample CharMap matching ASCII characters to single-byte values."""
    cm = CharMap()
    for i in range(ord("A"), ord("Z") + 1):
        cm.add_mapping(bytes([i]), chr(i))
    for i in range(ord("0"), ord("9") + 1):
        cm.add_mapping(bytes([i]), chr(i))
    cm.add_mapping(b"\x20", " ")
    return cm


def test_scan_horizontal_text_runs(sample_charmap):
    """Test horizontal text run scanning and padding detection."""
    # Create an 8x8 tilemap with empty tiles (index 0)
    tm = Tilemap(width=8, height=8)

    # Place "ITEM" at row 2, col 1 (indices: 0x49, 0x54, 0x45, 0x4D)
    # Remaining cols 5, 6, 7 are blank (index 0) -> max_available_tiles = 4 + 3 = 7
    for idx, char in enumerate("ITEM"):
        tm.set_entry(1 + idx, 2, TilemapEntry(tile_index=ord(char), palette_bank=1))

    # Place "MAGIC" at row 4, col 0 (indices: 0x4D, 0x41, 0x47, 0x49, 0x43)
    # Col 5 is non-blank (e.g. border tile 0x99), so padding is 0 -> max_available_tiles = 5
    for idx, char in enumerate("MAGIC"):
        tm.set_entry(idx, 4, TilemapEntry(tile_index=ord(char), palette_bank=2))
    tm.set_entry(5, 4, TilemapEntry(tile_index=0x99, palette_bank=0))

    runs = TilemapDissector.scan_text_runs(
        tilemap=tm,
        charmap=sample_charmap,
        min_length=2,
        direction="horizontal",
    )

    assert len(runs) == 2

    # Verify first run ("ITEM")
    r0 = runs[0]
    assert r0.row == 2
    assert r0.col == 1
    assert r0.decoded_text == "ITEM"
    assert r0.palette_bank == 1
    assert r0.max_available_tiles == 7  # 4 text + 3 empty tiles

    # Verify second run ("MAGIC")
    r1 = runs[1]
    assert r1.row == 4
    assert r1.col == 0
    assert r1.decoded_text == "MAGIC"
    assert r1.palette_bank == 2
    assert r1.max_available_tiles == 5  # blocked by tile 0x99


def test_scan_vertical_text_runs(sample_charmap):
    """Test vertical text run scanning down columns."""
    tm = Tilemap(width=4, height=6)

    # Place "TOP" down column 1, rows 1..3
    for row_offset, char in enumerate("TOP"):
        tm.set_entry(1, 1 + row_offset, TilemapEntry(tile_index=ord(char), palette_bank=3))

    runs = TilemapDissector.scan_text_runs(
        tilemap=tm,
        charmap=sample_charmap,
        min_length=2,
        direction="vertical",
    )

    assert len(runs) == 1
    vrun = runs[0]
    assert vrun.col == 1
    assert vrun.row == 1
    assert vrun.direction == "vertical"
    assert vrun.decoded_text == "TOP"
    assert vrun.palette_bank == 3
    assert vrun.max_available_tiles == 3 + 2  # 3 text + rows 4, 5


def test_export_text_grid(sample_charmap):
    """Test 2D visual ASCII grid rendering of tilemap contents."""
    tm = Tilemap(width=6, height=3)
    for idx, char in enumerate("HI"):
        tm.set_entry(idx, 0, TilemapEntry(tile_index=ord(char)))
    for idx, char in enumerate("OK"):
        tm.set_entry(3 + idx, 2, TilemapEntry(tile_index=ord(char)))

    grid = TilemapDissector.export_text_grid(tm, sample_charmap, blank_char=".")
    expected_lines = [
        "HI....",
        "......",
        "...OK.",
    ]
    assert grid.splitlines() == expected_lines


def test_splice_label_left_center_right(sample_charmap):
    """Test splicing new text labels with left, center, and right alignments."""
    tm = Tilemap(width=10, height=3)

    # 1. Left alignment with padding in a span of 6 tiles
    TilemapDissector.splice_label(
        tilemap=tm,
        row=0,
        col=0,
        new_text="GO",
        charmap=sample_charmap,
        pad_tile=0,
        max_width=6,
        align="left",
    )
    # Positions 0..1: 'G', 'O'; Positions 2..5: pad 0
    assert tm.get_entry(0, 0).tile_index == ord("G")
    assert tm.get_entry(1, 0).tile_index == ord("O")
    assert tm.get_entry(2, 0).tile_index == 0
    assert tm.get_entry(5, 0).tile_index == 0

    # 2. Center alignment in a span of 6 tiles: "GO" (len 2) -> 2 left pad, 2 text, 2 right pad
    TilemapDissector.splice_label(
        tilemap=tm,
        row=1,
        col=2,
        new_text="GO",
        charmap=sample_charmap,
        pad_tile=0,
        max_width=6,
        align="center",
    )
    # Span is col 2..7. Left pad (6-2)//2 = 2. Col 2, 3: pad; Col 4, 5: 'G', 'O'; Col 6, 7: pad
    assert tm.get_entry(2, 1).tile_index == 0
    assert tm.get_entry(3, 1).tile_index == 0
    assert tm.get_entry(4, 1).tile_index == ord("G")
    assert tm.get_entry(5, 1).tile_index == ord("O")
    assert tm.get_entry(6, 1).tile_index == 0
    assert tm.get_entry(7, 1).tile_index == 0

    # 3. Right alignment in a span of 4 tiles: "WIN" (len 3) -> 1 left pad, 3 text
    TilemapDissector.splice_label(
        tilemap=tm,
        row=2,
        col=0,
        new_text="WIN",
        charmap=sample_charmap,
        pad_tile=0,
        max_width=4,
        align="right",
    )
    assert tm.get_entry(0, 2).tile_index == 0
    assert tm.get_entry(1, 2).tile_index == ord("W")
    assert tm.get_entry(2, 2).tile_index == ord("I")
    assert tm.get_entry(3, 2).tile_index == ord("N")


def test_splice_label_boundary_overflow(sample_charmap):
    """Test boundary checks when splicing exceeds max_width or tilemap dimensions."""
    tm = Tilemap(width=5, height=2)

    # Exceeds max_width
    with pytest.raises(ValueError, match="exceeds max_width"):
        TilemapDissector.splice_label(
            tilemap=tm,
            row=0,
            col=0,
            new_text="TOOLONG",
            charmap=sample_charmap,
            max_width=4,
        )

    # Exceeds tilemap width
    with pytest.raises(IndexError, match="exceeds tilemap dimensions"):
        TilemapDissector.splice_label(
            tilemap=tm,
            row=0,
            col=4,
            new_text="ABC",
            charmap=sample_charmap,
        )


def test_extract_menu_box(sample_charmap):
    """Test extracting structured text runs from a designated menu box region."""
    tm = Tilemap(width=16, height=16)

    # Put a window box at top=4, left=3, width=8, height=6
    # Inside window, row 5 (rel 1), col 4 (rel 1) has "SAVE"
    for idx, char in enumerate("SAVE"):
        tm.set_entry(4 + idx, 5, TilemapEntry(tile_index=ord(char), palette_bank=3))

    box = TilemapDissector.extract_menu_box(
        tilemap=tm,
        charmap=sample_charmap,
        top=4,
        left=3,
        width=8,
        height=6,
    )

    assert box.top == 4
    assert box.left == 3
    assert len(box.items) == 1

    item = box.items[0]
    assert item.row == 5
    assert item.col == 4
    assert item.decoded_text == "SAVE"
    assert item.palette_bank == 3


def test_export_import_and_apply_layout_json(sample_charmap):
    """Test full roundtrip: scan runs -> export JSON -> translate -> apply layout."""
    tm = Tilemap(width=12, height=4)
    for idx, char in enumerate("POTION"):
        tm.set_entry(1 + idx, 1, TilemapEntry(tile_index=ord(char), palette_bank=2))

    runs = TilemapDissector.scan_text_runs(tm, sample_charmap)
    json_str = TilemapDissector.export_layout_json(runs)

    imported_runs = TilemapDissector.import_layout_json(json_str)
    assert len(imported_runs) == 1
    assert imported_runs[0].decoded_text == "POTION"

    # Simulate translation edit: "POTION" -> "OBAT" (4 letters) with left alignment in 6 tiles
    translations = [
        {
            "row": imported_runs[0].row,
            "col": imported_runs[0].col,
            "new_text": "OBAT",
            "max_width": imported_runs[0].max_available_tiles,
            "align": "left",
            "palette_bank": 2,
        }
    ]

    TilemapDissector.apply_layout_dict(tm, translations, sample_charmap, pad_tile=0)

    # Verify "OBAT" at (1..4, 1) and cleared padding at (5..6, 1)
    assert "".join(chr(tm.get_entry(1 + i, 1).tile_index) for i in range(4)) == "OBAT"
    assert tm.get_entry(5, 1).tile_index == 0
    assert tm.get_entry(6, 1).tile_index == 0
