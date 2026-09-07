import os
import tempfile
from typing import Dict, Any, Optional
import json

from miorom.rom.base import BaseRomHandler
from miorom.platforms.wii.u8 import U8Archive
from miorom.compression import decompress, compress


class U8RomHandler(BaseRomHandler):
    """
    Nintendo U8 Archive (.arc / .szs) unpacker and repacker.
    Standard container used across GameCube and Wii games.
    Transparently handles Yaz0 and LZ11 compression during unpack and repack.
    """

    name = "u8"
    description = "Nintendo U8 Archive"
    extensions = [".arc", ".szs"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        if U8Archive.is_u8(data):
            return True

        if len(data) >= 4 and data[:4] == b"Yaz0":
            return True

        if len(data) >= 5 and data[0] == 0x11:
            try:
                dec = decompress(data)
                return U8Archive.is_u8(dec)
            except Exception:
                pass

        if filepath:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.extensions:
                return True

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        comp_type: Optional[str] = None
        raw_u8 = data

        if data[:4] == b"Yaz0":
            comp_type = "yaz0"
            raw_u8 = U8Archive._decompress_yaz0(data)
        elif len(data) > 0 and data[0] == 0x11:
            comp_type = "lz11"
            raw_u8 = decompress(data)

        if not U8Archive.is_u8(raw_u8):
            raise ValueError("Data is not a valid Nintendo U8 archive.")

        root_dir = os.path.join(output_dir, "root")
        os.makedirs(root_dir, exist_ok=True)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".arc") as tmp:
            tmp.write(raw_u8)
            tmp_path = tmp.name

        try:
            extracted_files = U8Archive.extract_all(tmp_path, root_dir)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        return {
            "format": self.name,
            "platform": "Nintendo Wii / GameCube",
            "compression": comp_type,
            "file_count": len(extracted_files),
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        root_dir = os.path.join(input_dir, "root")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "data")
        if not os.path.isdir(root_dir):
            root_dir = input_dir

        comp_type = kwargs.get("compression")
        if comp_type is None:
            # Check meta.json
            meta_path = os.path.join(input_dir, "miorom.meta.json")
            if os.path.isfile(meta_path):
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    comp_type = meta.get("compression")
                except Exception:
                    pass

        with tempfile.NamedTemporaryFile(delete=False, suffix=".arc") as tmp:
            tmp_path = tmp.name

        try:
            U8Archive.pack(root_dir, tmp_path)
            with open(tmp_path, "rb") as f:
                arc_data = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        if comp_type in ("yaz0", "lz11"):
            return compress(arc_data, fmt=comp_type)

        return arc_data
