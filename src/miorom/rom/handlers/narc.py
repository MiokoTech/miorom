import os
from miorom.errors import ParseError
from typing import Dict, Any, Optional

from miorom.rom.base import BaseRomHandler
from miorom.platforms.nds.narc import NARCArchive


class NarcRomHandler(BaseRomHandler):
    """
    Nintendo DS Nitro ARChive (NARC) unpacker and repacker.
    Standard resource container in NDS games.
    """

    name = "narc"
    description = "Nintendo DS NARC Archive"
    extensions = [".narc", ".carc"]

    def can_handle(self, data: bytes, filepath: Optional[str] = None) -> bool:
        if NARCArchive.is_narc(data):
            return True

        if filepath:
            ext = os.path.splitext(filepath)[1].lower()
            if ext in self.extensions:
                return True

        return False

    def unpack(self, data: bytes, output_dir: str, **kwargs) -> Dict[str, Any]:
        if not NARCArchive.is_narc(data):
            raise ParseError("Data is not a valid Nintendo NARC archive.")

        root_dir = os.path.join(output_dir, "root")
        os.makedirs(root_dir, exist_ok=True)

        entries = NARCArchive.unpack_entries(data)
        padding = max(4, len(str(len(entries))))

        for e in entries:
            fname = e.name if e.name else f"file_{e.index:0{padding}d}.bin"
            fpath = os.path.join(root_dir, fname)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, "wb") as f_out:
                f_out.write(e.data)

        return {
            "format": self.name,
            "platform": "Nintendo DS",
            "file_count": len(entries),
        }

    def repack(self, input_dir: str, **kwargs) -> bytes:
        root_dir = os.path.join(input_dir, "root")
        if not os.path.isdir(root_dir):
            root_dir = os.path.join(input_dir, "data")
        if not os.path.isdir(root_dir):
            root_dir = input_dir

        file_names = sorted(os.listdir(root_dir))
        file_payloads = []
        for fn in file_names:
            fp = os.path.join(root_dir, fn)
            if os.path.isfile(fp):
                with open(fp, "rb") as f_in:
                    file_payloads.append(f_in.read())

        return NARCArchive.pack_files(file_payloads)
