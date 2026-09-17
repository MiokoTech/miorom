"""
miorom.rom.handlers.psx
~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation 1 (PS1 / PS-X) Disc ROM Handler.
Supports 2048-byte Mode 1 ISO disc images and 2352-byte Mode 2 Form 1 CD-ROM BIN images.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from miorom.platforms.cdrom.disc import SYNC_PATTERN
from miorom.platforms.iso.builder import ISOBuilder
from miorom.platforms.psx.rom import PSXRom, _iso_to_bin_bytes
from miorom.rom.base import BaseRomHandler


class PSXRomHandler(BaseRomHandler):
    """
    ROM handler for Sony PlayStation 1 (PS1 / PS-X) CD-ROM disc images.
    """

    name = "psx"
    description = "Sony PlayStation 1 (PS1 / PS-X) CD-ROM Disc"
    extensions = [".iso", ".bin", ".img"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        """Determines if the payload or file is a recognized PS1 disc image."""
        buffer = data
        if (not buffer or len(buffer) < 17 * 2048) and filepath and os.path.isfile(filepath):
            try:
                with open(filepath, "rb") as f:
                    buffer = f.read(64 * 2352)
            except Exception:
                pass

        if len(buffer) < 17 * 2048:
            return False

        # Exclude PSP images (which have PSP_GAME in initial extents)
        if b"PSP_GAME" in buffer[: 64 * 2048]:
            return False

        # 1. Check 2352-byte Mode 2 Form 1 CD-ROM BIN image
        if len(buffer) >= 17 * 2352:
            sec16_off = 16 * 2352
            if buffer[sec16_off : sec16_off + 12] == SYNC_PATTERN:
                pvd_off = sec16_off + 24
                if buffer[pvd_off : pvd_off + 6] == b"\x01CD001":
                    scan_area = buffer[: min(len(buffer), 128 * 2352)]
                    if (
                        b"SYSTEM.CNF" in scan_area
                        or b"PS-X EXE" in scan_area
                        or any(
                            code in scan_area
                            for code in (
                                b"SLUS",
                                b"SCUS",
                                b"SLES",
                                b"SCES",
                                b"SLPS",
                                b"SLPM",
                                b"SCPS",
                                b"SLAJ",
                            )
                        )
                    ):
                        return True

        # 2. Check 2048-byte Mode 1 ISO image
        pvd_offset = 16 * 2048
        if len(buffer) >= pvd_offset + 6 and buffer[pvd_offset : pvd_offset + 6] == b"\x01CD001":
            scan_area = buffer[: min(len(buffer), 128 * 2048)]
            if (
                b"SYSTEM.CNF" in scan_area
                or b"PS-X EXE" in scan_area
                or any(
                    code in scan_area
                    for code in (
                        b"SLUS",
                        b"SCUS",
                        b"SLES",
                        b"SCES",
                        b"SLPS",
                        b"SLPM",
                        b"SCPS",
                        b"SLAJ",
                    )
                )
            ):
                return True

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        """Unpacks all files and metadata from the PS1 ROM."""
        os.makedirs(output_dir, exist_ok=True)
        filepath = kwargs.get("filepath")
        if (not data or len(data) == 0) and filepath and os.path.isfile(filepath):
            rom = PSXRom.from_file(filepath)
        else:
            rom = PSXRom.from_bytes(data)
        rom.extract_all(output_dir)

        metadata = {
            "format": rom.format.value,
            "title": rom.title,
            "game_id": rom.game_id,
            "region": rom.region,
            "boot_path": rom.boot_path,
            "system_cnf": rom.system_cnf,
            "file_count": len(rom.list_files()),
        }
        return metadata

    def repack(self, input_dir: str, output_path: Optional[str] = None, **kwargs) -> bytes:
        """Repacks a directory of files back into a PS1 disc image (ISO or Mode 2 BIN)."""
        source_dir = input_dir
        target_path = output_path or kwargs.get("output_path")
        target_fmt = kwargs.get("fmt")
        if target_fmt:
            target_bin = str(target_fmt).lower() in ("bin", "img")
        elif target_path:
            ext = os.path.splitext(str(target_path))[1].lower()
            target_bin = ext in (".bin", ".img")
        else:
            target_bin = False

        volume_id = "PSX_GAME"
        for root, _, files in os.walk(source_dir):
            for file in files:
                if file.upper() == "SYSTEM.CNF":
                    try:
                        with open(os.path.join(root, file), "r", errors="ignore") as cnf:
                            for line in cnf:
                                if "BOOT" in line.upper() and "=" in line:
                                    vol = line.split("=")[-1].strip().split("\\")[-1].split(";")[0]
                                    if vol:
                                        volume_id = vol[:32].upper()
                                        break
                    except Exception:
                        pass
                    break

        builder = ISOBuilder(volume_id=volume_id)
        for root, _, files in os.walk(source_dir):
            for file in files:
                if file == "miorom.meta.json":
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, source_dir).replace(os.sep, "/")
                with open(full_path, "rb") as f:
                    builder.add_file(rel_path, f.read())

        iso_bytes = builder.build()
        if target_bin:
            final_bytes = _iso_to_bin_bytes(iso_bytes)
        else:
            final_bytes = iso_bytes

        if target_path:
            out_dir = os.path.dirname(target_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(target_path, "wb") as f:
                f.write(final_bytes)

        return final_bytes

    def get_metadata(self, data: bytes) -> Dict[str, Any]:
        """Extracts game metadata without unpacking files."""
        rom = PSXRom.from_bytes(data)
        return {
            "platform": "psx",
            "format": rom.format.value,
            "title": rom.title,
            "game_id": rom.game_id,
            "region": rom.region,
            "boot_path": rom.boot_path,
            "system_cnf": rom.system_cnf,
            "file_count": len(rom.list_files()),
        }
