import pytest
from miorom.graphics.palette import Color, Palette
from miorom.graphics.tiles import Tile
from miorom.graphics.tilesheet import TileSheet, TileSheetRenderer


def test_tilesheet_basic_and_pixels():
    # Create 4 tiles in a 2x2 grid
    t0 = Tile([1] * 64)
    t1 = Tile([2] * 64)
    t2 = Tile([3] * 64)
    t3 = Tile([4] * 64)
    
    pal = Palette([
        Color(0, 0, 0),
        Color(255, 0, 0),
        Color(0, 255, 0),
        Color(0, 0, 255),
        Color(255, 255, 0),
    ])

    sheet = TileSheet(tiles=[t0, t1, t2, t3], columns=2, palette=pal)
    assert sheet.rows == 2
    assert sheet.pixel_width == 16
    assert sheet.pixel_height == 16

    # Test coordinate access
    assert sheet.get_pixel(0, 0) == 1
    assert sheet.get_pixel(8, 0) == 2
    assert sheet.get_pixel(0, 8) == 3
    assert sheet.get_pixel(8, 8) == 4

    # Modify pixel
    sheet.set_pixel(3, 3, 4)
    assert sheet.get_pixel(3, 3) == 4
    assert t0.get_pixel(3, 3) == 4


def test_tilesheet_bmp_roundtrip(tmp_path):
    t0 = Tile()
    for y in range(8):
        for x in range(8):
            t0.set_pixel(x, y, (x + y) % 4)

    pal = Palette([
        Color(0, 0, 0),
        Color(255, 0, 0),
        Color(0, 255, 0),
        Color(0, 0, 255),
    ])

    sheet = TileSheet(tiles=[t0], columns=1, palette=pal)
    bmp_file = tmp_path / "sheet.bmp"
    raw_bmp = sheet.to_bmp(output_path=str(bmp_file))

    # Verify BMP magic and header
    assert raw_bmp.startswith(b"BM")
    assert bmp_file.exists()

    # Load back from file
    imported_sheet = TileSheet.from_bmp(str(bmp_file), bpp=4, palette=pal)
    assert imported_sheet.pixel_width == 8
    assert imported_sheet.pixel_height == 8
    assert len(imported_sheet.tiles) == 1

    # Verify pixels match exactly
    for y in range(8):
        for x in range(8):
            assert imported_sheet.get_pixel(x, y) == sheet.get_pixel(x, y)


def test_tilesheet_tileset_bytes_roundtrip():
    # 4 tiles with 4bpp encoding
    tiles = [Tile([i % 16] * 64) for i in range(4)]
    sheet = TileSheet(tiles=tiles, columns=2)

    raw_tiles = sheet.to_tileset_bytes(bpp=4)
    assert len(raw_tiles) == 4 * 32  # 32 bytes per 4bpp tile

    sheet2 = TileSheet.from_tileset_bytes(raw_tiles, bpp=4, columns=2)
    assert len(sheet2.tiles) == 4
    for i in range(4):
        assert sheet2.tiles[i].pixels == sheet.tiles[i].pixels


def test_tilesheet_renderer(tmp_path):
    t0 = Tile([1] * 64)
    pal = Palette([Color(0, 0, 0), Color(255, 255, 255)])
    sheet = TileSheet(tiles=[t0], columns=1, palette=pal)

    scaled_bmp = TileSheetRenderer.render_to_bmp(sheet, scale=2, show_grid=True)
    assert scaled_bmp.startswith(b"BM")
    # Width and height should be 16x16
    assert len(scaled_bmp) > len(sheet.to_bmp())
