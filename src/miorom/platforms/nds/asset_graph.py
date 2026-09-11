"""
asset_graph.py - High-level Nintendo DS 2D graphics scene graph and asset resolver.

Provides automated discovery, structural constraint validation, and linking
across Nitro binary formats (NCGR, NCLR, NSCR, NCER, NANR).
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from miorom.graphics.image_bridge import ImageBridge
from miorom.platforms.nds.ncer import NCERFile
from miorom.platforms.nds.nanr import NANRFile
from miorom.platforms.nds.ncgr import NCGRFile
from miorom.platforms.nds.nclr import NCLRFile
from miorom.platforms.nds.nscr import NSCRFile


@dataclass
class NitroAssetCatalog:
    """Discovers and catalogs Nitro binary assets in a directory tree."""

    root_dir: str
    ncgr_files: Dict[str, str] = field(default_factory=dict)  # lower_stem -> full_path
    nclr_files: Dict[str, str] = field(default_factory=dict)
    nscr_files: Dict[str, str] = field(default_factory=dict)
    ncer_files: Dict[str, str] = field(default_factory=dict)
    nanr_files: Dict[str, str] = field(default_factory=dict)

    def scan(self, recursive: bool = False) -> None:
        """Indexes all supported Nitro binary extensions in root_dir."""
        self.ncgr_files.clear()
        self.nclr_files.clear()
        self.nscr_files.clear()
        self.ncer_files.clear()
        self.nanr_files.clear()

        if not os.path.isdir(self.root_dir):
            return

        def _index_file(fpath: str) -> None:
            base = os.path.basename(fpath)
            stem, ext = os.path.splitext(base)
            low_stem = stem.lower()
            low_ext = ext.lower()

            if low_ext == ".ncgr":
                self.ncgr_files[low_stem] = fpath
            elif low_ext == ".nclr":
                self.nclr_files[low_stem] = fpath
            elif low_ext == ".nscr":
                self.nscr_files[low_stem] = fpath
            elif low_ext == ".ncer":
                self.ncer_files[low_stem] = fpath
            elif low_ext == ".nanr":
                self.nanr_files[low_stem] = fpath

        if recursive:
            for root, _, files in os.walk(self.root_dir):
                for fname in files:
                    _index_file(os.path.join(root, fname))
        else:
            for fname in os.listdir(self.root_dir):
                fpath = os.path.join(self.root_dir, fname)
                if os.path.isfile(fpath):
                    _index_file(fpath)

    def resolve(
        self,
        stem: str,
        ext: str,
        fallbacks: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Resolves an asset path using exact stem matching, prefix reduction, and fallbacks.
        ext must be one of: '.ncgr', '.nclr', '.nscr', '.ncer', '.nanr'.
        """
        table_map = {
            ".ncgr": self.ncgr_files,
            ".nclr": self.nclr_files,
            ".nscr": self.nscr_files,
            ".ncer": self.ncer_files,
            ".nanr": self.nanr_files,
        }
        lookup = table_map.get(ext.lower())
        if lookup is None:
            return None

        clean_stem = os.path.splitext(stem)[0]
        prefix_strip_digits = re.sub(r"\d+$", "", clean_stem)
        prefix_underscore = clean_stem[: clean_stem.rfind("_")] if "_" in clean_stem else clean_stem

        candidates = [
            clean_stem,
            prefix_strip_digits,
            prefix_underscore,
            f"{prefix_underscore}_01",
            f"{prefix_underscore}01",
            f"{prefix_strip_digits}01",
            f"{prefix_strip_digits}00",
        ]
        if fallbacks:
            candidates.extend(fallbacks)

        for cand in candidates:
            cand_low = cand.lower()
            if cand_low in lookup:
                return lookup[cand_low]

        return None


@dataclass
class NitroScreen:
    """Represents a resolved background screen (NSCR tilemap + NCGR tiles + NCLR palette)."""

    name: str
    nscr_path: str
    ncgr_path: str
    nclr_path: str
    width: int = 256
    height: int = 192

    def render(self, transparency: str = "auto") -> Image.Image:
        """Renders the screen tilemap into a PIL Image."""
        if not HAS_PIL:
            raise ImportError("Pillow is required for graphics rendering. Install with 'pip install Pillow'.")

        with open(self.ncgr_path, "rb") as f:
            ncgr = NCGRFile.from_bytes(f.read())
        with open(self.nclr_path, "rb") as f:
            nclr = NCLRFile.from_bytes(f.read())
        with open(self.nscr_path, "rb") as f:
            nscr = NSCRFile.from_bytes(f.read())

        pal = nclr.to_palette(expand_pmcp=True)
        is_trans_zero = (transparency == "transparent")
        if transparency == "auto":
            if len(pal) > 0 and (pal[0].r, pal[0].g, pal[0].b) in [(255, 0, 255), (0, 255, 255), (0, 255, 0)]:
                is_trans_zero = True
            elif any(k in self.name.lower() for k in ["talk_win", "waku", "obj_"]) or self.name.lower().endswith(("_2", "_3", "_4", "02", "03", "04")):
                is_trans_zero = True

        w_tiles = nscr.width_tiles
        h_tiles = nscr.actual_height_tiles
        width_px = nscr.width_pixels
        height_px = nscr.actual_height_pixels

        img = Image.new("RGBA", (width_px, height_px), (0, 0, 0, 0))
        pixels = img.load()

        for ty in range(h_tiles):
            for tx in range(w_tiles):
                entry = nscr.get_entry(tx, ty, paged=True)
                if entry is None or len(ncgr.tiles) == 0:
                    continue

                t_idx = entry.tile_index % len(ncgr.tiles)
                tile = ncgr.tiles[t_idx]
                pal_base = entry.palette_index * 16 if ncgr.bpp == 4 else 0

                for y in range(8):
                    py = 7 - y if entry.flip_y else y
                    for x in range(8):
                        px = 7 - x if entry.flip_x else x
                        color_idx = tile.get_pixel(px, py)
                        if is_trans_zero and color_idx == 0:
                            continue

                        full_pal_idx = pal_base + color_idx
                        if full_pal_idx < len(pal):
                            col = pal[full_pal_idx]
                            if is_trans_zero and (col.r, col.g, col.b) == (255, 0, 255):
                                continue
                            pixels[tx * 8 + x, ty * 8 + y] = (col.r, col.g, col.b, 255)

        return img

    def export(self, out_path: str, transparency: str = "auto") -> str:
        """Renders and saves the screen image to a PNG file."""
        img = self.render(transparency=transparency)
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)
        return out_path


@dataclass
class NitroSprite:
    """Represents a resolved UI/character sprite (NCER cell bank + NCGR tiles + NCLR palette)."""

    name: str
    ncgr_path: str
    nclr_path: str
    ncer_path: Optional[str] = None
    nanr_path: Optional[str] = None

    def render_frames(self, stacked: bool = True, transparency: bool = True) -> Optional[Image.Image]:
        """Renders assembled OAM cell banks into a PIL Image."""
        if not HAS_PIL:
            raise ImportError("Pillow is required for graphics rendering. Install with 'pip install Pillow'.")

        with open(self.ncgr_path, "rb") as f:
            ncgr = NCGRFile.from_bytes(f.read())
        with open(self.nclr_path, "rb") as f:
            nclr = NCLRFile.from_bytes(f.read())

        if self.ncer_path and os.path.isfile(self.ncer_path):
            with open(self.ncer_path, "rb") as f:
                ncer = NCERFile.from_bytes(f.read())
            if stacked:
                return ncer.render_all_banks_stacked(
                    ncgr=ncgr,
                    palette_or_nclr=nclr,
                    transparency=transparency,
                )
            elif ncer.banks:
                return ncer.render_bank(
                    bank_index=0,
                    ncgr=ncgr,
                    palette_or_nclr=nclr,
                    transparency=transparency,
                )

        # Fallback to raw tilesheet
        return ImageBridge.to_image(
            ncgr.tiles,
            nclr.to_palette(expand_pmcp=True),
            width_in_tiles=ncgr.width_tiles if ncgr.width_tiles not in (0xFFFF, 0) else 16,
            transparency_mode="transparent" if transparency else "opaque",
        )

    def export(self, out_path: str, stacked: bool = True, transparency: bool = True) -> Optional[str]:
        """Renders and saves the sprite to a PNG file."""
        img = self.render_frames(stacked=stacked, transparency=transparency)
        if img is None:
            return None
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        img.save(out_path)
        return out_path

    def get_animation(self) -> Optional[NANRFile]:
        """Loads companion Nitro Animation Resource (NANR) if present."""
        if self.nanr_path and os.path.isfile(self.nanr_path):
            with open(self.nanr_path, "rb") as f:
                return NANRFile.from_bytes(f.read())
        return None

    def render_animation_sequence(
        self,
        seq_index: int = 0,
        transparency: bool = True,
    ) -> List["Image.Image"]:
        """Renders all frames in a specific animation sequence as a list of images."""
        if not HAS_PIL:
            raise ImportError("Pillow is required for graphics rendering.")

        nanr = self.get_animation()
        if not nanr or seq_index >= len(nanr.sequences):
            return []

        if not self.ncer_path or not os.path.isfile(self.ncer_path):
            return []

        with open(self.ncgr_path, "rb") as f:
            ncgr = NCGRFile.from_bytes(f.read())
        with open(self.nclr_path, "rb") as f:
            nclr = NCLRFile.from_bytes(f.read())
        with open(self.ncer_path, "rb") as f:
            ncer = NCERFile.from_bytes(f.read())

        seq = nanr.sequences[seq_index]
        frames: List["Image.Image"] = []
        for f in seq.frames:
            img = ncer.render_bank(f.cell_index, ncgr, nclr, transparency=transparency)
            if img:
                frames.append(img)
        return frames


class NitroAssetGraph:
    """High-level Nitro 2D graphics scene graph and automated constraint-solving resolver."""

    def __init__(
        self,
        root_dir: str,
        default_palette_fallbacks: Optional[List[str]] = None,
    ) -> None:
        self.root_dir = root_dir
        self.catalog = NitroAssetCatalog(root_dir=root_dir)
        self.default_palette_fallbacks: List[str] = default_palette_fallbacks or []
        self.screens: Dict[str, NitroScreen] = {}
        self.sprites: Dict[str, NitroSprite] = {}
        self.screen_ncgrs: Set[str] = set()
        self.orphan_assets: List[str] = []

        # Registered custom fallback rules
        self._palette_families: Dict[str, List[str]] = {}
        self._screen_families: Dict[str, Tuple[List[str], List[str]]] = {}

        # Global screen prefix families
        self._screen_prefixes: Tuple[str, ...] = (
            "win_",
            "talk_win",
            "camp_bg",
            "title_bg",
            "s_0",
            "mapguide",
        )

    def register_palette_family(self, prefix: str, fallbacks: List[str]) -> None:
        """Registers fallback palette names for assets starting with prefix."""
        self._palette_families[prefix.lower()] = fallbacks

    def register_screen_family(
        self,
        prefix: str,
        ncgr_fallbacks: Optional[List[str]] = None,
        nclr_fallbacks: Optional[List[str]] = None,
    ) -> None:
        """Registers custom tilebank and palette fallbacks for screen families."""
        self._screen_families[prefix.lower()] = (
            ncgr_fallbacks or [],
            nclr_fallbacks or [],
        )

    def is_screen_asset(self, name: str) -> bool:
        """Determines whether an asset name strictly represents a background screen."""
        low = name.lower()
        if low.startswith(self._screen_prefixes):
            return True
        if low in self.screen_ncgrs:
            return True
        if low in self.catalog.nscr_files:
            return True
        for suffix in ("_1", "_2", "_3", "_4", "_01", "_02", "_03", "_04", "00", "01", "02"):
            if f"{low}{suffix}" in self.catalog.nscr_files:
                return True
        return False

    def _get_palette_fallbacks(self, name: str) -> List[str]:
        low = name.lower()
        for prefix, fallbacks in self._palette_families.items():
            if low.startswith(prefix):
                return fallbacks
        return self.default_palette_fallbacks

    def _get_screen_fallbacks(self, name: str) -> Tuple[List[str], List[str]]:
        low = name.lower()
        for prefix, (ncgr_fb, nclr_fb) in self._screen_families.items():
            if low.startswith(prefix):
                return ncgr_fb, nclr_fb
        return [], []

    def resolve(self) -> NitroAssetGraph:
        """Discovers, validates, and links all screen and sprite assets in the catalog."""
        self.catalog.scan()
        self.screens.clear()
        self.sprites.clear()
        self.screen_ncgrs.clear()
        self.orphan_assets.clear()

        # Step 1: Resolve all background screens from NSCR files
        for low_stem, nscr_path in sorted(self.catalog.nscr_files.items()):
            # Skip dummy binary font maps
            if low_stem in ("font12x12", "ed_font12x12"):
                continue

            ncgr_fb, nclr_fb = self._get_screen_fallbacks(low_stem)
            ncgr_path = self.catalog.resolve(low_stem, ".ncgr", fallbacks=ncgr_fb)
            nclr_path = self.catalog.resolve(low_stem, ".nclr", fallbacks=nclr_fb or self._get_palette_fallbacks(low_stem))

            # Verify NCGR tile count for NSCR
            if ncgr_path and os.path.isfile(ncgr_path):
                try:
                    with open(nscr_path, "rb") as f_nscr:
                        nscr = NSCRFile.from_bytes(f_nscr.read())
                    with open(ncgr_path, "rb") as f_ncgr:
                        ncgr = NCGRFile.from_bytes(f_ncgr.read())

                    max_tile = max((e.tile_index for e in nscr.entries), default=0)
                    if max_tile >= len(ncgr.tiles) and ncgr_fb:
                        # Secondary fallback if candidate too small
                        for alt_stem in ncgr_fb:
                            alt_path = self.catalog.ncgr_files.get(alt_stem.lower())
                            if alt_path and alt_path != ncgr_path:
                                with open(alt_path, "rb") as f_alt:
                                    alt_ncgr = NCGRFile.from_bytes(f_alt.read())
                                if max_tile < len(alt_ncgr.tiles):
                                    ncgr_path = alt_path
                                    break
                except Exception:
                    pass

            if ncgr_path and nclr_path:
                self.screens[low_stem] = NitroScreen(
                    name=low_stem,
                    nscr_path=nscr_path,
                    ncgr_path=ncgr_path,
                    nclr_path=nclr_path,
                )
                self.screen_ncgrs.add(os.path.splitext(os.path.basename(ncgr_path))[0].lower())
            else:
                self.orphan_assets.append(f"NSCR:{low_stem}")

        # Standalone boot warning screen
        caution_ncgr = self.catalog.ncgr_files.get("win_caution01")
        caution_nclr = self.catalog.nclr_files.get("win_caution01")
        if caution_ncgr:
            self.screen_ncgrs.add("win_caution01")

        # Step 2: Resolve all UI/character sprites from NCGR files
        for low_stem, ncgr_path in sorted(self.catalog.ncgr_files.items()):
            # Strictly exclude background screen tilebanks
            if self.is_screen_asset(low_stem):
                continue

            nclr_fb = self._get_palette_fallbacks(low_stem)
            nclr_path = self.catalog.resolve(low_stem, ".nclr", fallbacks=nclr_fb)
            ncer_path = self.catalog.ncer_files.get(low_stem)
            nanr_path = self.catalog.nanr_files.get(low_stem)

            if nclr_path:
                self.sprites[low_stem] = NitroSprite(
                    name=low_stem,
                    ncgr_path=ncgr_path,
                    nclr_path=nclr_path,
                    ncer_path=ncer_path,
                    nanr_path=nanr_path,
                )
            else:
                self.orphan_assets.append(f"NCGR:{low_stem}")

        return self

    def export_all_screens(self, out_dir: str, transparency: str = "auto") -> int:
        """Renders and exports all resolved background screens to PNG."""
        screens_dir = os.path.join(out_dir, "screens")
        os.makedirs(screens_dir, exist_ok=True)
        exported = 0

        screen_groups: Dict[str, List[str]] = defaultdict(list)

        for name, screen in self.screens.items():
            try:
                out_png = os.path.join(screens_dir, f"{name}.png")
                screen.export(out_png, transparency=transparency)
                exported += 1

                prefix_underscore = name[: name.rfind("_")] if "_" in name else name
                prefix_strip_digits = re.sub(r"\d+$", "", name)
                group_key = prefix_underscore if "_" in name else prefix_strip_digits
                if group_key and group_key != name and group_key.lower() not in ("talk", "talk_win", "waku"):
                    screen_groups[group_key].append(out_png)
            except Exception:
                pass

        # Standalone boot warning screen
        caution_ncgr = self.catalog.ncgr_files.get("win_caution01")
        caution_nclr = self.catalog.nclr_files.get("win_caution01")
        if caution_ncgr and caution_nclr and HAS_PIL:
            try:
                caution_png = os.path.join(screens_dir, "win_caution01.png")
                with open(caution_ncgr, "rb") as f_c:
                    nc_c = NCGRFile.from_bytes(f_c.read())
                with open(caution_nclr, "rb") as f_p:
                    nl_c = NCLRFile.from_bytes(f_p.read())
                c_img = ImageBridge.to_image(
                    nc_c.tiles,
                    nl_c.to_palette(expand_pmcp=True),
                    width_in_tiles=32,
                    transparency_mode="opaque",
                )
                c_img.save(caution_png)
                exported += 1
            except Exception:
                pass

        # Generate composite previews for multi-layer sets
        if HAS_PIL:
            for g_key, paths in screen_groups.items():
                if len(paths) > 1:
                    comp_out = os.path.join(screens_dir, f"{g_key}_composite.png")
                    valid = [p for p in sorted(paths) if os.path.isfile(p)]
                    if valid:
                        base = Image.open(valid[0]).convert("RGBA")
                        for p in valid[1:]:
                            layer = Image.open(p).convert("RGBA")
                            if layer.size != base.size:
                                layer = layer.resize(base.size)
                            base = Image.alpha_composite(base, layer)
                        base.save(comp_out)

        return exported

    def export_all_sprites(self, out_dir: str, transparency: bool = True) -> int:
        """Renders and exports all resolved UI/character sprites to PNG."""
        ui_dir = os.path.join(out_dir, "ui")
        os.makedirs(ui_dir, exist_ok=True)
        exported = 0

        for name, sprite in self.sprites.items():
            try:
                out_png = os.path.join(ui_dir, f"{name}.png")
                res = sprite.export(out_png, stacked=True, transparency=transparency)
                if res:
                    exported += 1
            except Exception:
                pass

        return exported

    def export_all(self, out_dir: str, screen_transparency: str = "auto", sprite_transparency: bool = True) -> Tuple[int, int]:
        """Convenience method to export both screens and sprites in one pass."""
        s_count = self.export_all_screens(out_dir, transparency=screen_transparency)
        u_count = self.export_all_sprites(out_dir, transparency=sprite_transparency)
        return s_count, u_count
