"""
miorom.platforms.psp.pbp
~~~~~~~~~~~~~~~~~~~~~~~~
Sony PlayStation Portable (PSP) EBOOT.PBP container unpacker and repacker.

PBP files bundle executable binaries (DATA.PSP), game ISO/archives (DATA.PSAR),
metadata (PARAM.SFO), and GUI media assets (ICON0.PNG, PIC1.PNG) for PSP homebrew
and PS1 Classics.
"""

import os
import struct
from typing import Dict, List, Optional, Union

from miorom.errors import ParseError
from miorom.platforms.psp.sfo import SFOFile
from miorom.result import MioRomResult


PBP_MAGIC = b"\x00PBP"
PBP_HEADER_SIZE = 40

PBP_SECTION_NAMES = [
    "PARAM.SFO",
    "ICON0.PNG",
    "ICON1.PMF",
    "PIC0.PNG",
    "PIC1.PNG",
    "SND0.AT3",
    "DATA.PSP",
    "DATA.PSAR",
]


class PBPFile(MioRomResult):
    """
    Parser, extractor, and synthesizer for Sony PSP EBOOT.PBP container archives.
    """

    def __init__(self, sections: Optional[Dict[str, bytes]] = None, version: int = 0x00010000):
        self.version = version
        self.sections: Dict[str, bytes] = {}
        for name in PBP_SECTION_NAMES:
            self.sections[name] = b""
        if sections:
            for k, v in sections.items():
                self.sections[k.upper()] = bytes(v)

    @classmethod
    def from_bytes(cls, data: bytes) -> "PBPFile":
        """Parses a raw binary EBOOT.PBP buffer."""
        if len(data) < PBP_HEADER_SIZE:
            raise ParseError("Data too small for PBP header (minimum 40 bytes).")

        magic = data[:4]
        if magic != PBP_MAGIC:
            raise ParseError(f"Invalid PBP magic: {magic!r}, expected {PBP_MAGIC!r}")

        version = struct.unpack_from("<I", data, 4)[0]
        offsets = list(struct.unpack_from("<8I", data, 8))

        sections: Dict[str, bytes] = {}
        for i in range(8):
            name = PBP_SECTION_NAMES[i]
            start = offsets[i]
            end = offsets[i + 1] if i + 1 < 8 else len(data)

            if start < PBP_HEADER_SIZE or start > len(data):
                sections[name] = b""
            elif end < start:
                sections[name] = b""
            else:
                sections[name] = data[start:end]

        return cls(sections, version=version)

    @classmethod
    def from_file(cls, path: str) -> "PBPFile":
        with open(path, "rb") as f:
            return cls.from_bytes(f.read())

    def get_section(self, name: str) -> bytes:
        """Returns payload bytes of specified PBP section."""
        return self.sections.get(name.upper(), b"")

    def set_section(self, name: str, data: bytes):
        """Sets payload bytes of specified PBP section."""
        self.sections[name.upper()] = bytes(data)

    @property
    def sfo(self) -> Optional[SFOFile]:
        """Convenience property parsing PARAM.SFO section if present."""
        sfo_data = self.get_section("PARAM.SFO")
        if len(sfo_data) >= 20 and sfo_data[:4] == b"\x00PSF":
            try:
                return SFOFile.from_bytes(sfo_data)
            except Exception:
                return None
        return None

    def extract_all(self, output_dir: str):
        """Extracts all non-empty sections to directory on disk."""
        os.makedirs(output_dir, exist_ok=True)
        for name, data in self.sections.items():
            if len(data) > 0:
                out_path = os.path.join(output_dir, name)
                with open(out_path, "wb") as f:
                    f.write(data)

    def to_bytes(self) -> bytes:
        """Synthesizes all sections into a valid EBOOT.PBP binary."""
        offsets: List[int] = []
        curr_offset = PBP_HEADER_SIZE

        # Calculate offsets
        for name in PBP_SECTION_NAMES:
            offsets.append(curr_offset)
            curr_offset += len(self.sections.get(name, b""))

        out = bytearray(PBP_HEADER_SIZE)
        out[0:4] = PBP_MAGIC
        struct.pack_into("<I", out, 4, self.version)
        struct.pack_into("<8I", out, 8, *offsets)

        for name in PBP_SECTION_NAMES:
            out.extend(self.sections.get(name, b""))

        return bytes(out)

    def save(self, path: str):
        with open(path, "wb") as f:
            f.write(self.to_bytes())
