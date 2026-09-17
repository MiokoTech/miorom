"""
miorom.rom.handlers.gba
~~~~~~~~~~~~~~~~~~~~~~~
Nintendo Game Boy Advance (.gba) Cartridge ROM Handler.
Supports header parsing, complement checksum calculation and repair,
save-type detection and patching, unpacking to ROM and metadata manifests,
and repacking with hardware padding.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from miorom.platforms.gba.rom import GBARom, fix_gba_checksum
from miorom.rom.base import BaseRomHandler


class GBARomHandler(BaseRomHandler):
    """
    ROM handler for Nintendo Game Boy Advance (.gba) cartridge images.
    """

    name = "gba"
    description = "Game Boy Advance Cartridge ROM"
    extensions = [".gba"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        """Determines if the payload or file is a Game Boy Advance ROM."""
        if len(data) >= 0xC0:
            if data[0x04:0x14] == GBARom.NINTENDO_LOGO[:16]:
                return True

        if filepath and os.path.isfile(filepath):
            ext = os.path.splitext(filepath)[1].lower()
            if ext == ".gba":
                try:
                    with open(filepath, "rb") as f:
                        hdr = f.read(0xC0)
                        if len(hdr) >= 0xC0 and hdr[0x04:0x14] == GBARom.NINTENDO_LOGO[:16]:
                            return True
                except Exception:
                    pass
                return True

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        """Unpacks GBA ROM binary, headers, and save metadata."""
        os.makedirs(output_dir, exist_ok=True)
        rom = GBARom(data)

        # 1. Save main ROM binary
        rom_path = os.path.join(output_dir, "rom.bin")
        with open(rom_path, "wb") as f:
            f.write(rom.data)

        # 2. Save header info
        header_info = {
            "title": rom.title,
            "game_code": rom.game_code,
            "maker_code": rom.maker_code,
            "version": rom.version,
            "region": rom.region,
            "header_checksum": hex(rom.header_checksum),
            "header_checksum_valid": rom.is_header_checksum_valid(),
            "logo_valid": rom.is_logo_valid(),
            "entry_point": hex(rom.entry_point),
            "save_type": rom.detect_save_type(),
            "has_rtc": rom.has_rtc,
            "rom_size": len(rom.data),
        }
        header_path = os.path.join(output_dir, "header.json")
        with open(header_path, "w", encoding="utf-8") as f:
            json.dump(header_info, f, indent=2)

        # Sync timestamps so header.json is not considered newer than rom.bin initially
        bin_mtime = os.path.getmtime(rom_path)
        os.utime(header_path, (bin_mtime, bin_mtime))

        return {
            "platform": "gba",
            "title": rom.title,
            "game_code": rom.game_code,
            "maker_code": rom.maker_code,
            "version": rom.version,
            "region": rom.region,
            "save_type": rom.detect_save_type(),
            "has_rtc": rom.has_rtc,
            "rom_size": len(rom.data),
        }

    def repack(self, input_dir: str, output_path: Optional[str] = None, **kwargs) -> bytes:
        """Repacks an unpacked directory back into a valid GBA ROM."""
        rom_path = os.path.join(input_dir, "rom.bin")
        if not os.path.isfile(rom_path):
            raise FileNotFoundError(f"Cannot repack GBA ROM: 'rom.bin' not found in '{input_dir}'.")

        with open(rom_path, "rb") as f:
            rom_data = bytearray(f.read())

        header_file = os.path.join(input_dir, "header.json")
        if os.path.isfile(header_file):
            try:
                # If header.json was modified after rom.bin, apply header changes
                if os.path.getmtime(header_file) > os.path.getmtime(rom_path):
                    with open(header_file, "r", encoding="utf-8") as f:
                        hdr = json.load(f)
                    if "title" in hdr:
                        title_bytes = hdr["title"].encode("ascii", "replace")[:12].ljust(12, b"\x00")
                        rom_data[0xA0:0xAC] = title_bytes
                    if "game_code" in hdr:
                        rom_data[0xAC:0xB0] = hdr["game_code"].encode("ascii", "replace")[:4].ljust(4, b"\x00")
                    if "maker_code" in hdr:
                        rom_data[0xB0:0xB2] = hdr["maker_code"].encode("ascii", "replace")[:2].ljust(2, b"\x00")
            except Exception:
                pass

        # Fix complement checksum automatically
        repacked = fix_gba_checksum(bytes(rom_data))

        if output_path:
            out_dir = os.path.dirname(output_path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(repacked)

        return repacked

    def get_metadata(self, data: bytes) -> Dict[str, Any]:
        """Extracts GBA cartridge metadata without unpacking."""
        rom = GBARom(data)
        return {
            "platform": "gba",
            "title": rom.title,
            "game_code": rom.game_code,
            "maker_code": rom.maker_code,
            "version": rom.version,
            "region": rom.region,
            "entry_point": hex(rom.entry_point),
            "save_type": rom.detect_save_type(),
            "has_rtc": rom.has_rtc,
            "header_checksum_valid": rom.is_header_checksum_valid(),
            "logo_valid": rom.is_logo_valid(),
            "rom_size": len(rom.data),
        }
