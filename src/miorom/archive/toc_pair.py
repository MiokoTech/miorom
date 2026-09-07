"""
miorom.archive.toc_pair
~~~~~~~~~~~~~~~~~~~~~~~
Handler for TOC-paired binary archives: a small .bin index file referencing
offsets/sizes within a large .dat payload file.

Supports:
1. Neverland NLCM format (Rune Factory series, Harvest Moon, etc.):
   - Header magic: b"NLCM" (0x38 bytes header)
   - num_entries at 0x0C (big-endian uint32)
   - Entry stride: 0x10 bytes (size at +0x00, offset at +0x08)
2. Raw TOC format:
   - Array of (offset, size) pairs, big-endian uint32
"""

import os
import shutil
import struct
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class TocEntry:
    index: int
    offset: int
    size: int

    @property
    def end(self) -> int:
        return self.offset + self.size

    def __repr__(self) -> str:
        return f"<TocEntry [{self.index}] offset=0x{self.offset:08X} size={self.size}>"


class TocPair:
    """
    Reads and manipulates TOC .bin + payload .dat file pairs with streaming I/O
    to avoid reading hundreds of megabytes into RAM.
    """

    def __init__(self, bin_path: str, dat_path: str, format_type: str, entries: List[TocEntry], bin_data: bytearray):
        self.bin_path = bin_path
        self.dat_path = dat_path
        self.format_type = format_type
        self.entries = entries
        self.bin_data = bin_data

    @classmethod
    def load(cls, bin_path: str, dat_path: str) -> "TocPair":
        with open(bin_path, "rb") as f:
            bin_data = bytearray(f.read())

        if bin_data.startswith(b"NLCM"):
            fmt = "nlcm"
            entries = cls._parse_nlcm(bin_data)
        else:
            fmt = "raw_pair"
            entries = cls._parse_raw(bin_data)

        return cls(bin_path, dat_path, fmt, entries, bin_data)

    @classmethod
    def _parse_nlcm(cls, bin_data: bytes) -> List[TocEntry]:
        num_entries = struct.unpack_from(">I", bin_data, 0x0C)[0]
        entries: List[TocEntry] = []
        for i in range(num_entries):
            e_off = 0x38 + (i * 0x10)
            if e_off + 0x10 > len(bin_data):
                break
            size = struct.unpack_from(">I", bin_data, e_off)[0]
            offset = struct.unpack_from(">I", bin_data, e_off + 0x08)[0]
            entries.append(TocEntry(index=i, offset=offset, size=size))
        return entries

    @classmethod
    def _parse_raw(cls, bin_data: bytes) -> List[TocEntry]:
        entries: List[TocEntry] = []
        n = len(bin_data) // 8
        for i in range(n):
            off = i * 8
            raw_offset, raw_size = struct.unpack_from(">II", bin_data, off)
            if raw_offset == 0 and raw_size == 0 and i > 0:
                break
            entries.append(TocEntry(index=i, offset=raw_offset, size=raw_size))
        return entries

    def __len__(self) -> int:
        return len(self.entries)

    def get_entry(self, index: int) -> TocEntry:
        if index < 0 or index >= len(self.entries):
            raise IndexError(f"TOC index {index} out of range (0-{len(self.entries)-1})")
        return self.entries[index]

    def extract(self, index: int) -> bytes:
        entry = self.get_entry(index)
        if entry.size == 0:
            return b""
        with open(self.dat_path, "rb") as f_dat:
            f_dat.seek(entry.offset)
            return f_dat.read(entry.size)

    def extract_all(
        self,
        dest_dir: str,
        prefix: str = "file_",
        extension: str = ".bin",
        overwrite: bool = True,
        skip_empty: bool = True,
    ) -> List[str]:
        """
        Extract all payload subfiles into dest_dir.

        Keyword Args:
            dest_dir: Destination folder where subfiles will be saved.
            prefix: Filename prefix (default: 'file_').
            extension: Filename extension (default: '.bin').
            overwrite: Whether to overwrite existing files (default: True).
            skip_empty: Skip generating files for 0-byte entries (default: True).
        """
        os.makedirs(dest_dir, exist_ok=True)
        extracted_paths: List[str] = []

        for entry in self.entries:
            if skip_empty and entry.size == 0:
                continue
            out_name = f"{prefix}{entry.index:04d}{extension}"
            out_path = os.path.join(dest_dir, out_name)
            if os.path.exists(out_path) and not overwrite:
                extracted_paths.append(out_path)
                continue
            data = self.extract(entry.index)
            with open(out_path, "wb") as f:
                f.write(data)
            extracted_paths.append(out_path)

        return extracted_paths

    def inject(
        self,
        index: int,
        new_data: bytes,
        out_bin: Optional[str] = None,
        out_dat: Optional[str] = None,
        alignment: int = 32,
        pad_byte: bytes = b"\x00",
        dry_run: bool = False,
    ) -> int:
        """
        Inject new_data into the TOC payload at index.
        If size <= orig_size, performs in-place overwrite.
        If size > orig_size, appends new_data aligned to alignment bytes at EOF and updates offset.
        Returns the final offset of the injected entry.

        Keyword Args:
            out_bin: Output path for .bin index (defaults to overwriting self.bin_path).
            out_dat: Output path for .dat payload (defaults to overwriting self.dat_path).
            alignment: Boundary to align appended payload chunks to (default: 32).
            pad_byte: Byte used for alignment padding (default: b'\\x00').
            dry_run: If True, computes final offset without modifying files on disk.
        """
        entry = self.get_entry(index)
        orig_size = entry.size
        new_size = len(new_data)

        target_dat = out_dat if out_dat else self.dat_path
        target_bin = out_bin if out_bin else self.bin_path

        if dry_run:
            if new_size <= orig_size:
                return entry.offset
            else:
                dat_len = os.path.getsize(self.dat_path) if os.path.exists(self.dat_path) else 0
                rem = dat_len % alignment
                pad_len = (alignment - rem) % alignment if alignment > 1 else 0
                return dat_len + pad_len

        # If saving to separate target dat, copy first if not existing or different
        if out_dat and os.path.abspath(out_dat) != os.path.abspath(self.dat_path):
            if not os.path.exists(out_dat):
                shutil.copyfile(self.dat_path, out_dat)

        with open(target_dat, "r+b") as f_dat:
            if new_size <= orig_size:
                f_dat.seek(entry.offset)
                f_dat.write(new_data)
                # Zero-pad remaining space if smaller
                if new_size < orig_size:
                    f_dat.write(pad_byte * (orig_size - new_size))
                final_offset = entry.offset
            else:
                f_dat.seek(0, 2)  # Seek to EOF
                cur_pos = f_dat.tell()
                pad_len = (alignment - (cur_pos % alignment)) % alignment if alignment > 1 else 0
                if pad_len > 0:
                    f_dat.write(pad_byte * pad_len)
                final_offset = f_dat.tell()
                f_dat.write(new_data)

        # Update entry in memory
        entry.offset = final_offset
        entry.size = new_size

        # Update bin_data
        if self.format_type == "nlcm":
            e_off = 0x38 + (index * 0x10)
            struct.pack_into(">I", self.bin_data, e_off, new_size)
            struct.pack_into(">I", self.bin_data, e_off + 0x08, final_offset)
        else:
            e_off = index * 8
            struct.pack_into(">II", self.bin_data, e_off, final_offset, new_size)

        with open(target_bin, "wb") as f_bin:
            f_bin.write(self.bin_data)

        return final_offset

    def summary(self, max_entries: int = 20) -> str:
        dat_size = os.path.getsize(self.dat_path) if os.path.exists(self.dat_path) else 0
        lines = [
            f"TocPair ({self.format_type.upper()}): {len(self.entries)} entries, payload: {dat_size:,} bytes",
            f"{'Index':<8} {'Offset':<12} {'Size':<12} {'End':<12}",
            "-" * 48,
        ]
        for e in self.entries[:max_entries]:
            lines.append(f"{e.index:<8} 0x{e.offset:08X}   {e.size:<12} 0x{e.end:08X}")
        if len(self.entries) > max_entries:
            lines.append(f"... and {len(self.entries) - max_entries} more entries")
        return "\n".join(lines)
