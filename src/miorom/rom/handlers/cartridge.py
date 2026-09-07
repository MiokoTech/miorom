import os
import struct
import json
from typing import Dict, Any, Optional

from miorom.rom.base import BaseRomHandler
from miorom.platforms.gba import GBARom, fix_gba_checksum
from miorom.platforms.gb import GBRom, fix_gb_checksum
from miorom.platforms.n64 import N64Rom, fix_n64_checksum
from miorom.platforms.snes import SNESRom
from miorom.platforms.md import MDRom, fix_md_checksum


class CartridgeRomHandler(BaseRomHandler):
    """
    Cartridge ROM handler for flat memory-mapped ROM images:
    Game Boy Advance (.gba), Nintendo 64 (.z64/.n64), Game Boy/GBC (.gb/.gbc),
    SNES (.sfc/.smc), and Sega Mega Drive/Genesis (.md/.gen).
    Unpacks ROM binary and system headers, repacks with automatic platform hardware checksum recalibration.
    """

    name = "cartridge"
    description = "Cartridge ROM Image"
    extensions = [".gba", ".gb", ".gbc", ".z64", ".n64", ".v64", ".sfc", ".smc", ".md", ".gen"]

    def _detect_subplatform(self, data: bytes, filepath: Optional[str] = None) -> Optional[str]:
        ext = os.path.splitext(filepath)[1].lower() if filepath else ""

        # 1. GBA
        if ext == ".gba" or (len(data) >= 0xC0 and data[4:20] == GBARom.NINTENDO_LOGO[:16]):
            return "gba"

        # 2. N64
        if ext in (".z64", ".n64", ".v64") or (len(data) >= 4 and struct.unpack(">I", data[:4])[0] in (0x80371240, 0x37804012, 0x40123780, 0x12408037)):
            return "n64"

        # 3. Game Boy / Color
        if ext in (".gb", ".gbc") or (len(data) >= 0x150 and data[0x104:0x114] == GBRom.NINTENDO_LOGO[:16]):
            return "gb"

        # 4. Mega Drive / Genesis
        if ext in (".md", ".gen") or (len(data) >= 0x104 and data[0x100:0x104] == b"SEGA"):
            return "md"

        # 5. SNES
        if ext in (".sfc", ".smc"):
            return "snes"

        if len(data) >= 0x8000:
            for hdr_off in (0x7FC0, 0xFFC0):
                if hdr_off + 32 <= len(data):
                    comp, chk = struct.unpack_from("<HH", data, hdr_off + 0x1C)
                    if (comp ^ chk) == 0xFFFF:
                        return "snes"

        return None

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        return self._detect_subplatform(data, filepath) is not None

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        sub = self._detect_subplatform(data, kwargs.get("filepath"))
        if not sub:
            sub = "generic_cartridge"

        sys_dir = os.path.join(output_dir, "sys")
        os.makedirs(sys_dir, exist_ok=True)

        # Save rom.bin
        with open(os.path.join(output_dir, "rom.bin"), "wb") as f:
            f.write(data)

        # Extract header
        header_len = min(len(data), 0x400)
        with open(os.path.join(sys_dir, "header.bin"), "wb") as f:
            f.write(data[:header_len])

        title = "Unknown"
        meta_info: Dict[str, Any] = {
            "format": self.name,
            "subplatform": sub,
            "rom_size": len(data),
        }

        try:
            if sub == "gba" and len(data) >= 0xC0:
                rom = GBARom(data)
                title = rom.title
                meta_info["title"] = rom.title
                meta_info["game_code"] = rom.game_code
                meta_info["maker_code"] = rom.maker_code
            elif sub == "gb" and len(data) >= 0x150:
                rom_gb = GBRom(data)
                title = rom_gb.title
                meta_info["title"] = rom_gb.title
                meta_info["cartridge_type"] = rom_gb.cartridge_type_name
            elif sub == "n64" and len(data) >= 0x40:
                rom_n64 = N64Rom(data)
                title = rom_n64.header.title
                meta_info["title"] = rom_n64.header.title
                meta_info["game_code"] = rom_n64.header.game_code
            elif sub == "snes" and len(data) >= 0x8000:
                rom_snes = SNESRom(data)
                title = rom_snes.title
                meta_info["title"] = rom_snes.title
            elif sub == "md" and len(data) >= 0x200:
                rom_md = MDRom(data)
                title = rom_md.header.domestic_title
                meta_info["title"] = rom_md.header.domestic_title
        except Exception:
            pass

        meta_info["title"] = title
        return meta_info

    def repack(self, input_dir: str, **kwargs) -> bytes:
        rom_path = os.path.join(input_dir, "rom.bin")
        if not os.path.isfile(rom_path):
            raise FileNotFoundError(f"Cannot repack cartridge: '{rom_path}' not found.")

        with open(rom_path, "rb") as f:
            rom_data = bytearray(f.read())

        sub = kwargs.get("subplatform")
        if not sub:
            meta_path = os.path.join(input_dir, "miorom.meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    sub = meta.get("subplatform")
                except Exception:
                    pass

        if not sub:
            sub = self._detect_subplatform(bytes(rom_data))

        # Recalibrate hardware checksums
        if sub == "gba":
            rom_data = bytearray(fix_gba_checksum(bytes(rom_data)))
        elif sub == "gb":
            rom_data = bytearray(fix_gb_checksum(bytes(rom_data)))
        elif sub == "n64":
            rom_data = bytearray(fix_n64_checksum(bytes(rom_data)))
        elif sub == "snes":
            snes = SNESRom(bytes(rom_data))
            snes.fix_checksum()
            rom_data = bytearray(snes.data)
        elif sub == "md":
            rom_data = bytearray(fix_md_checksum(bytes(rom_data)))

        return bytes(rom_data)
