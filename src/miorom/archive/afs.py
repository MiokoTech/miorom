"""
miorom.archive.afs
~~~~~~~~~~~~~~~~~~
CRI Middleware AFS (Archive File System) container parser and builder.
Standard archive container used across Dreamcast, PlayStation 2, GameCube, and Xbox
games (e.g. Sonic Adventure 2, Shenmue, Virtua Fighter, Resident Evil: Code Veronica).
Pure Python, using MioROM declarative binary primitives.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Dict, List, Optional, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import BinaryStruct, RawBytes, U16, U32
from miorom.errors import ParseError
from miorom.result import MioRomResult
from miorom.security import sanitize_extract_path


class AFSHeaderStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(4)  # b"AFS\x00" or b"AFS "
    entry_count = U32()


class AFSEntryRecordStruct(BinaryStruct):
    _endian = "<"
    offset = U32()
    size = U32()


class AFSTocPointerStruct(BinaryStruct):
    _endian = "<"
    toc_offset = U32()
    toc_size = U32()


class AFSTocMetadataStruct(BinaryStruct):
    _endian = "<"
    year = U16()
    month = U16()
    day = U16()
    hour = U16()
    minute = U16()
    second = U16()
    file_size = U32()


@dataclass
class AFSEntry(MioRomResult):
    """An individual file entry inside a CRI AFS archive."""

    name: str
    data: bytes
    year: int = 2000
    month: int = 1
    day: int = 1
    hour: int = 0
    minute: int = 0
    second: int = 0


class AFSArchive:
    """
    CRI Middleware AFS (Archive File System) container parser and builder.
    """

    MAGIC = b"AFS\x00"
    ALT_MAGIC = b"AFS "
    SECTOR_SIZE = 2048  # 0x800 CD/DVD sector alignment

    def __init__(self, entries: Optional[List[AFSEntry]] = None, has_toc: bool = True):
        self.entries: List[AFSEntry] = entries or []
        self.has_toc = has_toc

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    @property
    def filenames(self) -> List[str]:
        return [e.name for e in self.entries]

    def get_file(self, name_or_idx: Union[str, int]) -> Optional[bytes]:
        """Retrieves file data by name or index."""
        if isinstance(name_or_idx, int):
            if 0 <= name_or_idx < len(self.entries):
                return self.entries[name_or_idx].data
            return None

        target = name_or_idx.lower()
        for e in self.entries:
            if e.name.lower() == target:
                return e.data
        return None

    def add_file(self, name: str, data: bytes, **metadata) -> None:
        """Adds or replaces a file in the archive."""
        for e in self.entries:
            if e.name.lower() == name.lower():
                e.name = name
                e.data = data
                for k, v in metadata.items():
                    if hasattr(e, k):
                        setattr(e, k, v)
                return

        entry = AFSEntry(name=name, data=data, **metadata)
        self.entries.append(entry)

    @classmethod
    def from_bytes(cls, data: bytes) -> "AFSArchive":
        """Parses an AFS container from raw bytes."""
        if len(data) < AFSHeaderStruct.sizeof():
            raise ParseError("Data too small for AFS header.")

        header = AFSHeaderStruct.from_bytes(data, offset=0)
        if header.magic not in (cls.MAGIC, cls.ALT_MAGIC):
            raise ParseError(f"Invalid AFS magic: {header.magic!r}")

        entry_count = header.entry_count
        if entry_count < 0 or AFSHeaderStruct.sizeof() + entry_count * AFSEntryRecordStruct.sizeof() > len(data):
            raise ParseError(f"Invalid AFS entry count: {entry_count}")

        reader = BinaryReader(data, endian="<")
        reader.seek(AFSHeaderStruct.sizeof())

        # Read entry table
        raw_entries: List[Tuple[int, int]] = []
        for _ in range(entry_count):
            rec = AFSEntryRecordStruct.from_bytes(reader.read_bytes(AFSEntryRecordStruct.sizeof()))
            raw_entries.append((rec.offset, rec.size))

        # Read TOC Pointer immediately following the entry table
        toc_offset = 0
        toc_size = 0
        if reader.remaining >= AFSTocPointerStruct.sizeof():
            toc_ptr = AFSTocPointerStruct.from_bytes(reader.read_bytes(AFSTocPointerStruct.sizeof()))
            toc_offset = toc_ptr.toc_offset
            toc_size = toc_ptr.toc_size

        # Read TOC names if present
        filenames: Dict[int, str] = {}
        metadata_map: Dict[int, dict] = {}
        has_toc = False

        if toc_offset > 0 and toc_offset + toc_size <= len(data):
            has_toc = True
            toc_reader = BinaryReader(data, endian="<")
            toc_reader.seek(toc_offset)
            toc_entries = toc_size // 48
            for i in range(min(entry_count, toc_entries)):
                rec_bytes = toc_reader.read_bytes(48)
                name_raw = rec_bytes[:32].rstrip(b"\x00")
                name = name_raw.decode("ascii", errors="replace")
                if not name:
                    name = f"file_{i:04d}.bin"
                filenames[i] = name

                meta = AFSTocMetadataStruct.from_bytes(rec_bytes[32:48])
                metadata_map[i] = {
                    "year": meta.year,
                    "month": meta.month,
                    "day": meta.day,
                    "hour": meta.hour,
                    "minute": meta.minute,
                    "second": meta.second,
                }

        # Assemble file entries
        entries: List[AFSEntry] = []
        for i, (off, sz) in enumerate(raw_entries):
            if off + sz > len(data):
                raise ParseError(f"AFS entry {i} out of bounds ({off}+{sz} > {len(data)})")

            file_data = data[off : off + sz]
            name = filenames.get(i, f"file_{i:04d}.bin")
            meta = metadata_map.get(
                i,
                {"year": 2000, "month": 1, "day": 1, "hour": 0, "minute": 0, "second": 0},
            )

            entries.append(
                AFSEntry(
                    name=name,
                    data=file_data,
                    year=meta["year"],
                    month=meta["month"],
                    day=meta["day"],
                    hour=meta["hour"],
                    minute=meta["minute"],
                    second=meta["second"],
                )
            )

        return cls(entries=entries, has_toc=has_toc)

    def to_bytes(self, sector_align: bool = True) -> bytes:
        """
        Serializes the archive back to CRI AFS binary format.

        Args:
            sector_align: When True, aligns each file and the trailing TOC
                          to SECTOR_SIZE (2048 / 0x800 bytes).
        """
        entry_count = len(self.entries)
        writer = BinaryWriter(endian="<")

        # 1. Header
        writer.write_bytes(AFSHeaderStruct(magic=self.MAGIC, entry_count=entry_count).to_bytes())

        # 2. Calculate offsets
        toc_ptr_offset = AFSHeaderStruct.sizeof() + entry_count * AFSEntryRecordStruct.sizeof()
        header_table_len = toc_ptr_offset + AFSTocPointerStruct.sizeof()

        align = self.SECTOR_SIZE if sector_align else 4
        first_file_offset = (header_table_len + (align - 1)) & ~(align - 1)
        current_offset = first_file_offset

        offsets_and_sizes: List[Tuple[int, int]] = []
        for e in self.entries:
            sz = len(e.data)
            offsets_and_sizes.append((current_offset, sz))
            current_offset += sz
            if sector_align:
                current_offset = (current_offset + (align - 1)) & ~(align - 1)

        # Write entry table
        for off, sz in offsets_and_sizes:
            writer.write_bytes(AFSEntryRecordStruct(offset=off, size=sz).to_bytes())

        # Write TOC Pointer
        toc_offset = 0
        toc_size = 0
        if self.has_toc and entry_count > 0:
            toc_offset = current_offset
            toc_size = entry_count * 48
            writer.write_bytes(AFSTocPointerStruct(toc_offset=toc_offset, toc_size=toc_size).to_bytes())
        else:
            writer.write_bytes(AFSTocPointerStruct(toc_offset=0, toc_size=0).to_bytes())

        # Pad up to first file offset
        if writer.tell() < first_file_offset:
            writer.pad(first_file_offset - writer.tell())

        # Write files
        for i, e in enumerate(self.entries):
            off, _ = offsets_and_sizes[i]
            if writer.tell() < off:
                writer.pad(off - writer.tell())
            writer.write_bytes(e.data)

        # Write Trailing TOC
        if self.has_toc and entry_count > 0:
            if writer.tell() < toc_offset:
                writer.pad(toc_offset - writer.tell())

            for e in self.entries:
                name_bytes = e.name.encode("ascii", errors="replace")[:31]
                rec = bytearray(32)
                rec[: len(name_bytes)] = name_bytes

                meta_bytes = AFSTocMetadataStruct(
                    year=e.year,
                    month=e.month,
                    day=e.day,
                    hour=e.hour,
                    minute=e.minute,
                    second=e.second,
                    file_size=len(e.data),
                ).to_bytes()

                rec.extend(meta_bytes)
                writer.write_bytes(bytes(rec))

            if sector_align:
                writer.align(align)

        return writer.to_bytes()

    def extract_all(self, output_dir: str) -> List[str]:
        """
        Extracts all files from the archive into the specified directory.
        Protected against directory traversal attacks via sanitize_extract_path.
        """
        extracted_paths: List[str] = []
        os.makedirs(output_dir, exist_ok=True)

        for e in self.entries:
            safe_target = sanitize_extract_path(output_dir, e.name)
            parent_dir = os.path.dirname(safe_target)
            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(safe_target, "wb") as f:
                f.write(e.data)
            extracted_paths.append(safe_target)

        return extracted_paths
