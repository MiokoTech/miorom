import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict


@dataclass
class ISOFileEntry:
    path: str
    lba: int
    size: int
    is_directory: bool
    record_offset: int  # File offset where the 34+ byte directory record is stored

    @property
    def sector_offset(self) -> int:
        return self.lba * 2048


class ISO9660:
    """
    Pure-Python ISO9660 (CD/DVD disc image) filesystem reader and injector.
    Supports PS1, PS2, and standard console optical disc images.
    """

    SECTOR_SIZE = 2048

    def __init__(self, data: bytes):
        self.data = bytearray(data)
        if len(self.data) < 17 * self.SECTOR_SIZE:
            raise ValueError("Data too small to be a valid ISO9660 image.")

        # Check Primary Volume Descriptor at sector 16
        pvd_offset = 16 * self.SECTOR_SIZE
        if self.data[pvd_offset : pvd_offset + 6] != b"\x01CD001":
            raise ValueError("Invalid ISO9660 Primary Volume Descriptor magic.")

        self.pvd_offset = pvd_offset
        self.entries: List[ISOFileEntry] = []
        self._parse_tree()

    @classmethod
    def from_file(cls, path: str) -> "ISO9660":
        with open(path, "rb") as f:
            return cls(f.read())

    @property
    def volume_id(self) -> str:
        raw = self.data[self.pvd_offset + 40 : self.pvd_offset + 72]
        return raw.decode("ascii", errors="replace").strip()

    def _parse_tree(self):
        self.entries = []
        # Root directory record is at PVD offset 156
        root_rec = self.pvd_offset + 156
        root_lba = struct.unpack_from("<I", self.data, root_rec + 2)[0]
        root_size = struct.unpack_from("<I", self.data, root_rec + 10)[0]

        self._read_directory(root_lba, root_size, "")

    def _read_directory(self, dir_lba: int, dir_size: int, current_path: str):
        dir_start = dir_lba * self.SECTOR_SIZE
        pos = 0

        while pos < dir_size:
            rec_offset = dir_start + pos
            if rec_offset >= len(self.data):
                break

            rec_len = self.data[rec_offset]
            if rec_len == 0:
                # Padding to next sector boundary
                next_sector_pos = ((pos // self.SECTOR_SIZE) + 1) * self.SECTOR_SIZE
                if next_sector_pos == pos:
                    break
                pos = next_sector_pos
                continue

            entry_lba = struct.unpack_from("<I", self.data, rec_offset + 2)[0]
            entry_size = struct.unpack_from("<I", self.data, rec_offset + 10)[0]
            flags = self.data[rec_offset + 25]
            is_dir = bool(flags & 0x02)
            name_len = self.data[rec_offset + 32]
            raw_name = self.data[rec_offset + 33 : rec_offset + 33 + name_len]

            pos += rec_len

            # Ignore . (\x00) and .. (\x01)
            if raw_name in (b"\x00", b"\x01"):
                continue

            name = raw_name.decode("latin1", errors="replace")
            # Strip version suffix (e.g. ';1') for user friendliness
            clean_name = name.split(";")[0]
            full_path = f"{current_path}/{clean_name}" if current_path else clean_name

            entry = ISOFileEntry(
                path=full_path,
                lba=entry_lba,
                size=entry_size,
                is_directory=is_dir,
                record_offset=rec_offset,
            )
            self.entries.append(entry)

            if is_dir:
                self._read_directory(entry_lba, entry_size, full_path)

    def list_files(self) -> List[str]:
        return [e.path for e in self.entries if not e.is_directory]

    def get_entry(self, path: str) -> Optional[ISOFileEntry]:
        norm = path.strip("/").upper()
        for e in self.entries:
            if e.path.strip("/").upper() == norm:
                return e
        return None

    def read_file(self, path: str) -> bytes:
        entry = self.get_entry(path)
        if not entry:
            raise FileNotFoundError(f"File not found in ISO: {path}")
        if entry.is_directory:
            raise IsADirectoryError(f"Target is a directory: {path}")

        start = entry.lba * self.SECTOR_SIZE
        end = start + entry.size
        return bytes(self.data[start:end])

    def replace_file(self, path: str, new_content: bytes):
        """
        Replaces a file within the ISO.
        If the new data exceeds original sector allocation, relocates extent to the end of the disc
        and updates directory record LBA & size (both LE and BE pairs).
        """
        entry = self.get_entry(path)
        if not entry:
            raise FileNotFoundError(f"File not found in ISO: {path}")
        if entry.is_directory:
            raise IsADirectoryError(f"Cannot replace a directory: {path}")

        new_len = len(new_content)
        sectors_needed = (new_len + self.SECTOR_SIZE - 1) // self.SECTOR_SIZE
        old_sectors = (entry.size + self.SECTOR_SIZE - 1) // self.SECTOR_SIZE

        target_lba = entry.lba

        if sectors_needed > old_sectors:
            # Append new sectors at the end of the ISO
            current_total_sectors = len(self.data) // self.SECTOR_SIZE
            target_lba = current_total_sectors

            # Extend data buffer
            padding = (sectors_needed * self.SECTOR_SIZE) - new_len
            self.data.extend(new_content)
            self.data.extend(b"\x00" * padding)

            # Update volume space size in PVD (offset 80: uint32 LE + uint32 BE)
            new_total_sectors = len(self.data) // self.SECTOR_SIZE
            struct.pack_into("<I", self.data, self.pvd_offset + 80, new_total_sectors)
            struct.pack_into(">I", self.data, self.pvd_offset + 84, new_total_sectors)
        else:
            # In-place overwrite
            start = target_lba * self.SECTOR_SIZE
            self.data[start : start + new_len] = new_content
            # Zero out any remaining bytes in the allocated sectors
            allocated_bytes = old_sectors * self.SECTOR_SIZE
            if new_len < allocated_bytes:
                self.data[start + new_len : start + allocated_bytes] = b"\x00" * (allocated_bytes - new_len)

        # Update Directory Record:
        # Offset +2: LBA LE (uint32)
        # Offset +6: LBA BE (uint32)
        # Offset +10: Size LE (uint32)
        # Offset +14: Size BE (uint32)
        struct.pack_into("<I", self.data, entry.record_offset + 2, target_lba)
        struct.pack_into(">I", self.data, entry.record_offset + 6, target_lba)
        struct.pack_into("<I", self.data, entry.record_offset + 10, new_len)
        struct.pack_into(">I", self.data, entry.record_offset + 14, new_len)

        # Update cached entry
        entry.lba = target_lba
        entry.size = new_len

    def to_bytes(self) -> bytes:
        return bytes(self.data)
