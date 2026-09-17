"""
miorom.rom.handlers.psp
~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation Portable (PSP) ROM & Disc Handler.
Supports UMD ISO 9660 (.iso), Compressed ISO (.cso), and EBOOT.PBP packages.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from miorom.platforms.psp.rom import PSPFormat, PSPRom
from miorom.rom.base import BaseRomHandler


class PSPRomHandler(BaseRomHandler):
    """
    ROM handler for Sony PlayStation Portable (PSP) games.
    """

    name = "psp"
    description = "Sony PlayStation Portable (PSP) Disc / Package"
    extensions = [".iso", ".cso", ".pbp"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        """Determines if the payload or file is a recognized PSP game."""
        # 1. PBP check
        if len(data) >= 4 and data[:4] == b"\x00PBP":
            return True

        # 2. CSO check
        if len(data) >= 4 and data[:4] == b"CISO":
            return True

        # 3. ISO 9660 check
        pvd_offset = 16 * 2048
        if len(data) >= pvd_offset + 6 and data[pvd_offset : pvd_offset + 6] == b"\x01CD001":
            # Must be a PSP disc (search for PSP_GAME in initial disc extent / volume)
            root_extent = data[: min(len(data), 64 * 2048)]
            if b"PSP_GAME" in root_extent:
                return True

        if filepath and os.path.isfile(filepath):
            try:
                with open(filepath, "rb") as f:
                    hdr = f.read(32768 + 2048)
                    if len(hdr) >= 4 and hdr[:4] in (b"\x00PBP", b"CISO"):
                        return True
                    if len(hdr) >= pvd_offset + 6 and hdr[pvd_offset : pvd_offset + 6] == b"\x01CD001":
                        if b"PSP_GAME" in hdr:
                            return True
            except Exception:
                pass

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        """Unpacks all files and metadata from the PSP ROM."""
        os.makedirs(output_dir, exist_ok=True)
        filepath = kwargs.get("filepath")
        if (not data or len(data) == 0) and filepath and os.path.isfile(filepath):
            rom = PSPRom.from_file(filepath)
        else:
            rom = PSPRom.from_bytes(data)
        rom.extract_all(output_dir)

        metadata = {
            "format": rom.format.value,
            "game_id": rom.game_id,
            "title": rom.title,
            "version": rom.version,
            "category": rom.category,
            "region": rom.region,
            "file_count": len(rom.list_files()),
        }
        return metadata

    def repack(self, input_dir: str, output_path: Optional[str] = None, **kwargs) -> bytes:
        """Repacks a directory of files back into a PSP ROM image."""
        source_dir = input_dir
        target_path = output_path or kwargs.get("output_path")
        target_fmt = kwargs.get("fmt")
        if target_fmt:
            fmt = PSPFormat(str(target_fmt).lower())
        elif target_path:
            ext = os.path.splitext(str(target_path))[1].lower()
            fmt = PSPFormat.PBP if ext == ".pbp" else (PSPFormat.CSO if ext == ".cso" else PSPFormat.ISO)
        else:
            fmt = PSPFormat.ISO

        # Build ISO from directory
        from miorom.platforms.iso.builder import ISOBuilder

        builder = ISOBuilder(volume_id="PSP_GAME")
        for root, _, files in os.walk(source_dir):
            for file in files:
                if file == "miorom.meta.json":
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, source_dir).replace(os.sep, "/")
                with open(full_path, "rb") as f:
                    builder.add_file(rel_path, f.read())

        iso_bytes = builder.build()
        rom = PSPRom(iso_bytes, fmt=PSPFormat.ISO)
        if target_path:
            rom.save(target_path, fmt=fmt)
        return rom.to_bytes(fmt=fmt)

    def get_metadata(self, data: bytes) -> Dict[str, Any]:
        """Extracts game metadata without unpacking files."""
        rom = PSPRom.from_bytes(data)
        return {
            "platform": "psp",
            "format": rom.format.value,
            "game_id": rom.game_id,
            "title": rom.title,
            "version": rom.version,
            "category": rom.category,
            "region": rom.region,
            "file_count": len(rom.list_files()),
        }
