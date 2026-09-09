from miorom.result import MioRomResult
import os
from dataclasses import dataclass
from typing import List, Optional, Dict, BinaryIO

from miorom.security import sanitize_extract_path


@dataclass
class ArchiveEntry(MioRomResult):
    index: int
    name: str
    offset: int
    size: int
    data: Optional[bytes] = None


class ArchiveContainer:
    """
    Generic ROM archive / Table-of-Contents (TOC) container unpacker and packer.
    """

    def __init__(self, entries: Optional[List[ArchiveEntry]] = None):
        self.entries: List[ArchiveEntry] = entries or []

    def extract_to_dir(self, data_stream: BinaryIO, output_dir: str):
        """Extract all entries from data_stream to output directory."""
        os.makedirs(output_dir, exist_ok=True)
        for entry in self.entries:
            data_stream.seek(entry.offset)
            raw = data_stream.read(entry.size)
            filepath = sanitize_extract_path(output_dir, entry.name)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(raw)

    def load_from_dir(self, input_dir: str) -> List[ArchiveEntry]:
        """Load entries from files inside a directory."""
        entries = []
        files = sorted(os.listdir(input_dir))
        for idx, filename in enumerate(files):
            filepath = os.path.join(input_dir, filename)
            if os.path.isfile(filepath):
                with open(filepath, "rb") as f:
                    content = f.read()
                entries.append(ArchiveEntry(
                    index=idx,
                    name=filename,
                    offset=0,
                    size=len(content),
                    data=content
                ))
        self.entries = entries
        return entries

    def pack(self, alignment: int = 32) -> bytes:
        """Pack all entry datas sequentially, aligning each entry to alignment boundary."""
        out = bytearray()
        for entry in self.entries:
            if entry.data is None:
                continue
            # Alignment
            rem = len(out) % alignment
            if rem != 0:
                out.extend(b"\x00" * (alignment - rem))
            entry.offset = len(out)
            entry.size = len(entry.data)
            out.extend(entry.data)
        return bytes(out)
