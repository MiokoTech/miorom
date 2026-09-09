from miorom.result import MioRomResult
from miorom.errors import ParseError
from dataclasses import dataclass
from miorom.core.schema import BinaryStruct, FixedString, RawBytes, U16, U32, U8
from typing import List, Optional, Tuple, Dict


class ISOBothU32Struct(BinaryStruct):
    _endian = "<"
    little = U32()
    big = U32(endian=">")


class ISOPvdStruct(BinaryStruct):
    _endian = "<"
    magic = RawBytes(6)
    _reserved_0x06 = RawBytes(34)
    volume_id = FixedString(32)
    _reserved_0x48 = RawBytes(8)
    volume_space_size = ISOBothU32Struct()
    _reserved_0x58 = RawBytes(40)
    logical_block_size = U16()
    logical_block_size_big = U16(endian=">")
    _reserved_0x84 = RawBytes(24)
    root_directory = RawBytes(34)
    _reserved_0xEA = RawBytes(658)


class ISODirectoryRecordStruct(BinaryStruct):
    _endian = "<"
    length = U8()
    extended_attribute_length = U8()
    lba = ISOBothU32Struct()
    size = ISOBothU32Struct()
    recording_datetime = RawBytes(7)
    file_flags = U8()
    file_unit_size = U8()
    interleave_gap = U8()
    volume_sequence_number = U16()
    volume_sequence_number_big = U16(endian=">")
    name_length = U8()


@dataclass
class ISOFileEntry(MioRomResult):
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
            raise ParseError("Data too small to be a valid ISO9660 image.")

        # Check Primary Volume Descriptor at sector 16
        pvd_offset = 16 * self.SECTOR_SIZE
        if self.data[pvd_offset : pvd_offset + 6] != b"\x01CD001":
            raise ParseError("Invalid ISO9660 Primary Volume Descriptor magic.")

        self.pvd_offset = pvd_offset
        self.entries: List[ISOFileEntry] = []
        self._parse_tree()

    @classmethod
    def from_file(cls, path: str) -> "ISO9660":
        with open(path, "rb") as f:
            return cls(f.read())

    @property
    def volume_id(self) -> str:
        return ISOPvdStruct.from_bytes(self.data, offset=self.pvd_offset).volume_id.strip()

    def _parse_tree(self):
        self.entries = []
        # Root directory record is at PVD offset 156
        root_rec = self.pvd_offset + 156
        root_record = ISODirectoryRecordStruct.from_bytes(self.data, offset=root_rec)
        root_lba = root_record.lba.little
        root_size = root_record.size.little

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

            record = ISODirectoryRecordStruct.from_bytes(self.data, offset=rec_offset)
            entry_lba = record.lba.little
            entry_size = record.size.little
            is_dir = bool(record.file_flags & 0x02)
            name_len = record.name_length
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
            self.data[self.pvd_offset + 80 : self.pvd_offset + 88] = ISOBothU32Struct(
                little=new_total_sectors,
                big=new_total_sectors,
            ).to_bytes()
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
        self.data[entry.record_offset + 2 : entry.record_offset + 10] = ISOBothU32Struct(
            little=target_lba,
            big=target_lba,
        ).to_bytes()
        self.data[entry.record_offset + 10 : entry.record_offset + 18] = ISOBothU32Struct(
            little=new_len,
            big=new_len,
        ).to_bytes()

        # Update cached entry
        entry.lba = target_lba
        entry.size = new_len

    def to_bytes(self) -> bytes:
        return bytes(self.data)
