"""
test_nds_asset_graph.py - Comprehensive unit tests for NitroAssetGraph.
Tests asset cataloging, screen linking, structural constraints, sprite assembly,
and domain isolation between screens and sprites.
"""

import os
import tempfile
import pytest

from miorom.platforms.nds.asset_graph import (
    NitroAssetCatalog,
    NitroScreen,
    NitroSprite,
    NitroAssetGraph,
)
from miorom.platforms.nds.ncgr import NCGRFile
from miorom.platforms.nds.nclr import NCLRFile
from miorom.platforms.nds.nscr import NSCRFile, ScreenEntry
from miorom.platforms.nds.ncer import NCERFile, NCERBank, NCERCell
from miorom.graphics.palette import Palette, Color
from miorom.graphics.tiles import Tile


def _make_dummy_palette(colors: int = 16) -> Palette:
    pal = Palette()
    for i in range(colors):
        pal.append(Color(i * 15, i * 15, i * 15, 255 if i > 0 else 0))
    return pal


def _make_dummy_tiles(count: int = 16) -> list:
    tiles = []
    for t in range(count):
        tiles.append(Tile(pixels=[t % 16] * 64))
    return tiles


def test_catalog_scan_case_insensitive():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create mixed-case files
        open(os.path.join(tmpdir, "Title_Bg.NCGR"), "wb").write(b"ncgr")
        open(os.path.join(tmpdir, "title_bg.NCLR"), "wb").write(b"nclr")
        open(os.path.join(tmpdir, "TITLE_BG.NSCR"), "wb").write(b"nscr")
        open(os.path.join(tmpdir, "hero_spr.ncer"), "wb").write(b"ncer")

        catalog = NitroAssetCatalog(root_dir=tmpdir)
        catalog.scan()

        assert "title_bg" in catalog.ncgr_files
        assert "title_bg" in catalog.nclr_files
        assert "title_bg" in catalog.nscr_files
        assert "hero_spr" in catalog.ncer_files

        # Test resolution
        assert catalog.resolve("TITLE_BG", ".ncgr") is not None
        assert catalog.resolve("title_bg_1", ".ncgr") is not None
        assert catalog.resolve("unknown", ".ncgr") is None


def test_screen_resolution_and_render():
    with tempfile.TemporaryDirectory() as tmpdir:
        pal = _make_dummy_palette(16)
        nclr = NCLRFile.from_palette(pal, bpp=4)
        tiles = _make_dummy_tiles(16)
        ncgr = NCGRFile(tiles=tiles, bpp=4, width_tiles=4, height_tiles=4)

        # 32x24 grid = 768 entries
        entries = [ScreenEntry(tile_index=i % 16, palette_index=0) for i in range(768)]
        nscr = NSCRFile(entries=entries, width_pixels=256, height_pixels=192)

        ncgr_path = os.path.join(tmpdir, "screen01.NCGR")
        nclr_path = os.path.join(tmpdir, "screen01.NCLR")
        nscr_path = os.path.join(tmpdir, "screen01_1.NSCR")

        with open(ncgr_path, "wb") as f:
            f.write(ncgr.to_bytes())
        with open(nclr_path, "wb") as f:
            f.write(nclr.to_bytes())
        with open(nscr_path, "wb") as f:
            f.write(nscr.to_bytes())

        graph = NitroAssetGraph(root_dir=tmpdir)
        graph.resolve()

        assert "screen01_1" in graph.screens
        screen = graph.screens["screen01_1"]
        assert screen.ncgr_path == ncgr_path
        assert screen.nclr_path == nclr_path

        # Test render
        img = screen.render()
        assert img.size == (256, 192)

        # Test export
        out_png = os.path.join(tmpdir, "out", "screen01_1.png")
        screen.export(out_png)
        assert os.path.isfile(out_png)


def test_structural_tile_bounds_constraint():
    """Verify that an NCGR with insufficient tiles triggers fallback selection."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pal = _make_dummy_palette(16)
        nclr = NCLRFile.from_palette(pal, bpp=4)

        # Small NCGR (only 4 tiles)
        small_ncgr = NCGRFile(tiles=_make_dummy_tiles(4), bpp=4)
        # Large NCGR (32 tiles)
        large_ncgr = NCGRFile(tiles=_make_dummy_tiles(32), bpp=4)

        # NSCR referencing tile index 20 (requires at least 21 tiles)
        entries = [ScreenEntry(tile_index=20, palette_index=0) for _ in range(768)]
        nscr = NSCRFile(entries=entries, width_pixels=256, height_pixels=192)

        open(os.path.join(tmpdir, "panel01.NCLR"), "wb").write(nclr.to_bytes())
        open(os.path.join(tmpdir, "panel01.NCGR"), "wb").write(small_ncgr.to_bytes())
        open(os.path.join(tmpdir, "panel_master.NCGR"), "wb").write(large_ncgr.to_bytes())
        open(os.path.join(tmpdir, "panel01_1.NSCR"), "wb").write(nscr.to_bytes())

        graph = NitroAssetGraph(root_dir=tmpdir)
        # Register fallback to panel_master
        graph.register_screen_family(
            prefix="panel01",
            ncgr_fallbacks=["panel_master"],
            nclr_fallbacks=["panel01"],
        )
        graph.resolve()

        screen = graph.screens.get("panel01_1")
        assert screen is not None
        # Resolver must have selected panel_master because panel01 had insufficient tiles
        assert os.path.basename(screen.ncgr_path).lower() == "panel_master.ncgr"


def test_sprite_resolution_and_domain_isolation():
    """Verify that screen NCGRs never leak into the sprite list and sprites assemble correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pal = _make_dummy_palette(16)
        nclr = NCLRFile.from_palette(pal, bpp=4)
        tiles = _make_dummy_tiles(16)
        ncgr = NCGRFile(tiles=tiles, bpp=4)

        # 1. Screen asset: win_calendar01
        entries = [ScreenEntry(tile_index=0, palette_index=0) for _ in range(768)]
        nscr = NSCRFile(entries=entries, width_pixels=256, height_pixels=192)

        open(os.path.join(tmpdir, "win_calendar01.NCGR"), "wb").write(ncgr.to_bytes())
        open(os.path.join(tmpdir, "win_calendar01.NCLR"), "wb").write(nclr.to_bytes())
        open(os.path.join(tmpdir, "win_calendar01_1.NSCR"), "wb").write(nscr.to_bytes())

        # 2. Sprite asset: hero_walk with valid NCER binary data
        ncer_bytes = (
            b"RECN\xff\xfe\x00\x01k\x00\x00\x00\x10\x00\x03\x00KBEC8\x00\x00\x00"
            b"\x01\x00\x01\x00\x18\x00\x00\x00\x02\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x01\x00\x05\x08\x00\x00\x00\x00"
            b"\x12\x00\x12\x00\xf3\xff\xf3\xff\xf3\x00\xf3\x81\x00\x00\x00\x00"
            b"LBAL\x17\x00\x00\x00\x00\x00\x00\x00CellAnime0\x00TXEU\x0c\x00\x00\x00\x00\x00\x00\x00"
        )
        open(os.path.join(tmpdir, "hero_walk.NCGR"), "wb").write(ncgr.to_bytes())
        open(os.path.join(tmpdir, "hero_walk.NCLR"), "wb").write(nclr.to_bytes())
        open(os.path.join(tmpdir, "hero_walk.NCER"), "wb").write(ncer_bytes)

        graph = NitroAssetGraph(root_dir=tmpdir)
        graph.resolve()

        # Check domain isolation
        assert "win_calendar01_1" in graph.screens
        assert "win_calendar01" not in graph.sprites
        assert "hero_walk" in graph.sprites

        # Check sprite frames render
        sprite = graph.sprites["hero_walk"]
        img = sprite.render_frames(stacked=True)
        assert img is not None
        assert img.size == (32, 32)


def test_custom_fallback_registry_and_orphans():
    with tempfile.TemporaryDirectory() as tmpdir:
        pal = _make_dummy_palette(16)
        nclr = NCLRFile.from_palette(pal, bpp=4)
        tiles = _make_dummy_tiles(16)
        ncgr = NCGRFile(tiles=tiles, bpp=4)

        open(os.path.join(tmpdir, "pal_shared.NCLR"), "wb").write(nclr.to_bytes())
        open(os.path.join(tmpdir, "talk_cursor.NCGR"), "wb").write(ncgr.to_bytes())

        # Orphan screen with missing NCGR
        entries = [ScreenEntry(tile_index=0, palette_index=0) for _ in range(10)]
        nscr = NSCRFile(entries=entries, width_pixels=256, height_pixels=192)
        open(os.path.join(tmpdir, "orphan_screen.NSCR"), "wb").write(nscr.to_bytes())

        graph = NitroAssetGraph(root_dir=tmpdir)
        graph.register_palette_family(prefix="talk_", fallbacks=["pal_shared"])
        graph.resolve()

        assert "talk_cursor" in graph.sprites
        assert graph.sprites["talk_cursor"].nclr_path.endswith("pal_shared.NCLR")

        # Verify orphan reporting
        assert any("orphan_screen" in o for o in graph.orphan_assets)
