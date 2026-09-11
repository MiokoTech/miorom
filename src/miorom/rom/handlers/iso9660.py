import os
from typing import Dict, Any, Optional

from miorom.rom.base import BaseRomHandler
from miorom.platforms.iso.iso9660 import ISO9660
from miorom.security import sanitize_extract_path


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

        if filepath and os.path.isfile(filepath):
            try:
                with open(filepath, "rb") as f:
                    f.seek(16 * 2048)
                    pvd = f.read(6)
                    return pvd == b"\x01CD001"
            except OSError:
                return False

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        filepath = kwargs.pop("filepath", None)
        if filepath and os.path.isfile(filepath):
            return self.unpack_file(filepath, output_dir, **kwargs)

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
            dest = sanitize_extract_path(root_dir, f_path)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as f:
                f.write(content)

        return {
            "format": self.name,
            "platform": "ISO9660 Disc Image",
            "volume_id": iso.volume_id,
            "file_count": len(files),
        }

    def unpack_file(self, filepath: str, output_dir: str, **kwargs) -> Dict[str, Any]:
        """Memory-efficient streaming unpack directly from ISO file without loading full disc to RAM."""
        sys_dir = os.path.join(output_dir, "sys")
        root_dir = os.path.join(output_dir, "root")
        os.makedirs(sys_dir, exist_ok=True)
        os.makedirs(root_dir, exist_ok=True)

        # Stream copy to iso_base.bin in 64KB chunks
        with open(filepath, "rb") as f_in, open(os.path.join(sys_dir, "iso_base.bin"), "wb") as f_out:
            while True:
                chunk = f_in.read(65536)
                if not chunk:
                    break
                f_out.write(chunk)

        # Read directory metadata header
        file_size = os.path.getsize(filepath)
        with open(filepath, "rb") as f_in:
            hdr_bytes = f_in.read(min(file_size, 4 * 1024 * 1024))
            iso = ISO9660(hdr_bytes)

            files = iso.list_files()
            for f_path in files:
                entry = iso.get_entry(f_path)
                if not entry:
                    continue
                dest = sanitize_extract_path(root_dir, f_path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                f_in.seek(entry.lba * 2048)
                with open(dest, "wb") as f_out:
                    rem = entry.size
                    while rem > 0:
                        chunk = f_in.read(min(rem, 65536))
                        if not chunk:
                            break
                        f_out.write(chunk)
                        rem -= len(chunk)

        return {
            "format": self.name,
            "platform": "ISO9660 Disc Image",
            "volume_id": iso.volume_id,
            "file_count": len(files),
            "streaming": True,
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

                # Replace file in ISO if found
                entry = iso.get_entry(rel)
                if entry is not None:
                    iso.replace_file(rel, new_data)

        return iso.to_bytes()
