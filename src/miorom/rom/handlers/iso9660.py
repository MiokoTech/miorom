import os
from typing import Dict, Any, Optional

from miorom.rom.base import BaseRomHandler
from miorom.platforms.iso.iso9660 import ISO9660


class Iso9660RomHandler(BaseRomHandler):
    """
    ISO9660 optical disc image (.iso) unpacker and repacker.
    Extracts all directory records, system sectors, and files.
    Repacks modified files into ISO9660 images, automatically updating sector extents and LBA pointers.
    """

    name = "iso9660"
    description = "ISO9660 Disc Image"
    extensions = [".iso"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        if len(data) >= 17 * 2048:
            pvd_off = 16 * 2048
            if data[pvd_off : pvd_off + 6] == b"\x01CD001":
                return True

        if filepath:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.extensions and len(data) >= 17 * 2048:
                pvd_off = 16 * 2048
                return data[pvd_off : pvd_off + 6] == b"\x01CD001"

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        iso = ISO9660(data)
        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        # Save disc base for repacking
        with open(os.path.join(sys_dir, "iso_base.bin"), "wb") as f:
            f.write(data)

        files = iso.list_files()
        for f_path in files:
            content = iso.read_file(f_path)
            dest = os.path.join(root_dir, f_path.lstrip("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(content)

        return {
            "format": self.name,
            "platform": "ISO9660 Disc Image",
            "volume_id": iso.volume_id,
            "file_count": len(files),
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        sys_dir = os.path.join(input_dir, "sys")
        root_dir = os.path.join(input_dir, "root")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "data")
        if not os.path.isdir(root_dir):
            root_dir = input_dir

        base_path = os.path.join(sys_dir, "iso_base.bin")
        if not os.path.isfile(base_path):
            raise FileNotFoundError(f"Cannot repack ISO9660: base disc image '{base_path}' not found.")

        with open(base_path, "rb") as f:
            base_data = f.read()

        iso = ISO9660(base_data)

        for root, _, files in os.walk(root_dir):
            for fname in files:
                full_path = os.path.join(root, fname)
                rel = os.path.relpath(full_path, root_dir).replace("\\", "/").strip("/")
                with open(full_path, "rb") as f:
                    new_data = f.read()

                # If file exists in ISO, replace it; if not and method exists, inject
                entry = iso.get_entry(rel)
                if entry is not None:
                    iso.replace_file(rel, new_data)

        return iso.to_bytes()
