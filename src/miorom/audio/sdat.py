"""
sdat.py - Nintendo DS Sound Data Archive (SDAT) parser, extractor, and rebuilder.

Provides full parsing of SDAT containers including SYMB (symbol tables),
INFO (playback parameters & file mapping), FAT (file allocation table),
and FILE (audio payloads: SSEQ, SBNK, SWAR, SSAR, STRM).
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from miorom.errors import ParseError


@dataclass
class SDATFileEntry:
    """Individual audio file entry tracked by the FAT table."""

    index: int
    offset: int
    size: int
    data: bytearray
    category: str = "UNKNOWN"  # SSEQ, SBNK, SWAR, SSAR, STRM, RAW
    name: Optional[str] = None


class SDATContainer:
    """
    Nintendo DS SDAT (Sound Data) container parser and file extractor/injector.
    Stores SSEQ (music sequence), SWAR (wave archive), SBNK (sound bank),
    SSAR (sound sequence archive), and STRM (direct stream).
    """

    MAGIC = b"SDAT"

    def __init__(self, data: bytes) -> None:
        if len(data) < 64:
            raise ParseError("Data too small for SDAT header (minimum 64 bytes).")

        if data[:4] != self.MAGIC:
            raise ParseError(f"Invalid SDAT magic: {data[:4]!r}")

        self.data = bytearray(data)
        self.file_size = struct.unpack_from("<I", self.data, 8)[0]

        # Block locations from header
        self.symb_offset, self.symb_size = struct.unpack_from("<II", self.data, 0x10)
        self.info_offset, self.info_size = struct.unpack_from("<II", self.data, 0x18)
        self.fat_offset, self.fat_size = struct.unpack_from("<II", self.data, 0x20)
        self.file_block_offset, self.file_block_size = struct.unpack_from("<II", self.data, 0x28)

        self.entries: List[SDATFileEntry] = []
        self.sequences: Dict[str, SDATFileEntry] = {}
        self.sound_banks: Dict[str, SDATFileEntry] = {}
        self.wave_archives: Dict[str, SDATFileEntry] = {}
        self.sequence_archives: Dict[str, SDATFileEntry] = {}
        self.streams: Dict[str, SDATFileEntry] = {}

        self._parse_fat()
        self._parse_and_link_symbols()

    @classmethod
    def from_file(cls, path: str) -> "SDATContainer":
        """Loads an SDAT container from a file path."""
        with open(path, "rb") as f:
            return cls(f.read())

    def _parse_fat(self) -> None:
        """Parses the File Allocation Table (FAT) block with absolute offset resolution."""
        self.entries = []
        if self.fat_offset == 0 or self.fat_offset >= len(self.data):
            return

        fat_block_size = struct.unpack_from("<I", self.data, self.fat_offset + 4)[0]
        header_count = struct.unpack_from("<I", self.data, self.fat_offset + 8)[0]
        records_len = fat_block_size - 12
        # Resolve record count for interleaved tables
        if records_len > 0 and records_len % 8 == 0 and (records_len // 8) > header_count:
            fat_count = records_len // 8
        else:
            fat_count = header_count
        rec_pos = self.fat_offset + 12

        for i in range(fat_count):
            if rec_pos + 8 > len(self.data):
                break
            raw_off, f_size = struct.unpack_from("<II", self.data, rec_pos)

            # In Nitro SDAT, offsets are absolute from the start of the SDAT file.
            # Handle fallback if raw_off is relative to file_block_offset.
            if f_size > 0:
                abs_off = raw_off if raw_off >= self.fat_offset else (self.file_block_offset + raw_off)
                if abs_off + f_size <= len(self.data):
                    f_data = self.data[abs_off : abs_off + f_size]
                else:
                    f_data = self.data[abs_off:]
            else:
                abs_off = 0
                f_data = bytearray()

            # Determine category magic if available
            cat = "RAW"
            if len(f_data) >= 4:
                magic = bytes(f_data[:4])
                if magic in (b"SSEQ", b"SSAR", b"SBNK", b"SWAR", b"STRM"):
                    cat = magic.decode("ascii")

            self.entries.append(
                SDATFileEntry(
                    index=i,
                    offset=abs_off,
                    size=f_size,
                    data=bytearray(f_data),
                    category=cat,
                )
            )
            rec_pos += 8

    def _parse_and_link_symbols(self) -> None:
        """Links human-readable symbol names from SYMB and INFO blocks to FAT entries."""
        if not self.symb_offset or not self.info_offset:
            return

        categories = [
            ("SSEQ", self.sequences),
            ("SSAR", self.sequence_archives),
            ("SBNK", self.sound_banks),
            ("SWAR", self.wave_archives),
            ("PLAYER", None),
            ("GROUP", None),
            ("PLAYER2", None),
            ("STRM", self.streams),
        ]

        for cat_idx, (cat_name, target_dict) in enumerate(categories):
            if target_dict is None:
                continue

            symb_cat_off = struct.unpack_from("<I", self.data, self.symb_offset + 8 + cat_idx * 4)[0]
            info_cat_off = struct.unpack_from("<I", self.data, self.info_offset + 8 + cat_idx * 4)[0]

            if symb_cat_off == 0 or info_cat_off == 0:
                continue

            symb_sub = self.symb_offset + symb_cat_off
            info_sub = self.info_offset + info_cat_off

            symb_count = struct.unpack_from("<I", self.data, symb_sub)[0]
            info_count = struct.unpack_from("<I", self.data, info_sub)[0]
            total_items = min(symb_count, info_count)

            expected_magic = cat_name.encode("ascii")

            for i in range(total_items):
                n_off = struct.unpack_from("<I", self.data, symb_sub + 4 + i * 4)[0]
                r_off = struct.unpack_from("<I", self.data, info_sub + 4 + i * 4)[0]

                if n_off == 0 or r_off == 0:
                    continue

                name_bytes = self.data[self.symb_offset + n_off :].split(b"\x00")[0]
                name = name_bytes.decode("ascii", errors="replace")
                file_id = struct.unpack_from("<H", self.data, self.info_offset + r_off)[0]

                # Interleaved FAT slot mapping
                entry: Optional[SDATFileEntry] = None
                candidates = [file_id * 2, file_id]
                for cand_idx in candidates:
                    if 0 <= cand_idx < len(self.entries):
                        cand_entry = self.entries[cand_idx]
                        if cand_entry.data[:4] == expected_magic:
                            entry = cand_entry
                            break

                if entry is None and 0 <= file_id < len(self.entries):
                    entry = self.entries[file_id]

                if entry is not None:
                    entry.name = name
                    entry.category = cat_name
                    target_dict[name] = entry

    def get_file(self, index: int) -> bytes:
        """Retrieves raw data for a FAT entry index."""
        if 0 <= index < len(self.entries):
            return bytes(self.entries[index].data)
        raise IndexError(f"File index out of range: {index}")

    def replace_file(self, index: int, new_data: bytes) -> None:
        """Replaces sound file data at specified FAT index."""
        if not (0 <= index < len(self.entries)):
            raise IndexError(f"File index out of range: {index}")
        self.entries[index].data = bytearray(new_data)
        self.entries[index].size = len(new_data)

    def replace_by_name(self, name: str, new_data: bytes) -> bool:
        """Replaces an audio sub-file payload using its symbolic name."""
        all_mapped = [
            self.sequences,
            self.sound_banks,
            self.wave_archives,
            self.sequence_archives,
            self.streams,
        ]
        target_name_low = name.lower()
        for d in all_mapped:
            for k, entry in d.items():
                if k.lower() == target_name_low:
                    entry.data = bytearray(new_data)
                    entry.size = len(new_data)
                    return True
        return False

    def extract_all(self, out_dir: str) -> Dict[str, int]:
        """
        Extracts all audio assets into organized subdirectories:
        - out_dir/sseq/ (<name>.sseq)
        - out_dir/sbnk/ (<name>.sbnk)
        - out_dir/swar/ (<name>.swar)
        - out_dir/ssar/ (<name>.ssar)
        - out_dir/strm/ (<name>.strm)
        - out_dir/raw/  (<index:04d>.bin for unmapped entries)
        """
        counts: Dict[str, int] = {
            "sseq": 0,
            "sbnk": 0,
            "swar": 0,
            "ssar": 0,
            "strm": 0,
            "raw": 0,
        }

        cat_folders = {
            "SSEQ": ("sseq", ".sseq"),
            "SBNK": ("sbnk", ".sbnk"),
            "SWAR": ("swar", ".swar"),
            "SSAR": ("ssar", ".ssar"),
            "STRM": ("strm", ".strm"),
        }

        # Track written entries to identify unmapped active entries
        written_indices = set()

        all_dicts = [
            self.sequences,
            self.sound_banks,
            self.wave_archives,
            self.sequence_archives,
            self.streams,
        ]

        for d in all_dicts:
            for name, entry in d.items():
                if not entry.data:
                    continue
                folder_name, ext = cat_folders.get(entry.category, ("raw", ".bin"))
                target_dir = os.path.join(out_dir, folder_name)
                os.makedirs(target_dir, exist_ok=True)
                out_path = os.path.join(target_dir, f"{name}{ext}")
                with open(out_path, "wb") as f:
                    f.write(entry.data)
                counts[folder_name] += 1
                written_indices.add(entry.index)

        # Extract remaining active unmapped entries
        for entry in self.entries:
            if entry.index not in written_indices and len(entry.data) > 0:
                raw_dir = os.path.join(out_dir, "raw")
                os.makedirs(raw_dir, exist_ok=True)
                ext = f".{entry.category.lower()}" if entry.category in cat_folders else ".bin"
                out_path = os.path.join(raw_dir, f"{entry.index:04d}{ext}")
                with open(out_path, "wb") as f:
                    f.write(entry.data)
                counts["raw"] += 1

        return counts

    def repack_from_dir(self, in_dir: str) -> int:
        """
        Scans in_dir for modified audio files and replaces container entries.
        Returns the count of successfully updated files.
        """
        updated = 0
        cat_folders = ["sseq", "sbnk", "swar", "ssar", "strm"]

        for folder in cat_folders:
            sub_path = os.path.join(in_dir, folder)
            if not os.path.isdir(sub_path):
                continue
            for fname in os.listdir(sub_path):
                stem, _ = os.path.splitext(fname)
                fpath = os.path.join(sub_path, fname)
                if os.path.isfile(fpath):
                    with open(fpath, "rb") as f:
                        if self.replace_by_name(stem, f.read()):
                            updated += 1

        # Check raw files if any
        raw_path = os.path.join(in_dir, "raw")
        if os.path.isdir(raw_path):
            for fname in os.listdir(raw_path):
                stem, _ = os.path.splitext(fname)
                if stem.isdigit():
                    idx = int(stem)
                    fpath = os.path.join(raw_path, fname)
                    if 0 <= idx < len(self.entries):
                        with open(fpath, "rb") as f:
                            self.replace_file(idx, f.read())
                            updated += 1

        return updated

    def to_bytes(self) -> bytes:
        """Rebuilds the SDAT binary container with updated FAT and FILE blocks."""
        # Calculate new FILE block starting offset
        symb_block = self.data[self.symb_offset : self.symb_offset + self.symb_size] if self.symb_offset else b""
        info_block = self.data[self.info_offset : self.info_offset + self.info_size] if self.info_offset else b""

        new_symb_off = 64 if symb_block else 0
        new_info_off = new_symb_off + len(symb_block) if info_block else 0
        new_fat_off = (new_info_off + len(info_block)) if (new_info_off or new_symb_off) else 64

        fat_pad = (32 - (new_fat_off % 32)) % 32
        new_fat_off += fat_pad

        fat_records_len = len(self.entries) * 8
        fat_block_len = 12 + fat_records_len
        new_file_off = new_fat_off + fat_block_len
        file_pad = (32 - (new_file_off % 32)) % 32
        new_file_off += file_pad

        # Active file count
        active_count = sum(1 for e in self.entries if len(e.data) > 0)

        # Construct new FILE block and FAT records
        new_file_block = bytearray(b"FILE")
        # Block size and count placeholder
        new_file_block.extend(struct.pack("<II", 0, active_count))

        fat_records = bytearray()
        cur_file_pos = new_file_off + len(new_file_block)

        for entry in self.entries:
            if len(entry.data) > 0:
                pad = (32 - (cur_file_pos % 32)) % 32
                if pad > 0:
                    new_file_block.extend(b"\x00" * pad)
                    cur_file_pos += pad

                fat_records.extend(struct.pack("<II", cur_file_pos, len(entry.data)))
                new_file_block.extend(entry.data)
                cur_file_pos += len(entry.data)
            else:
                fat_records.extend(struct.pack("<II", 0, 0))

        # Finalize FILE block header
        struct.pack_into("<I", new_file_block, 4, len(new_file_block))

        # Assemble FAT block
        fat_block = bytearray(b"FAT ")
        fat_block.extend(struct.pack("<II", fat_block_len, active_count))
        fat_block.extend(fat_records)

        # Build 64-byte SDAT Header
        total_sdat_len = new_file_off + len(new_file_block)
        header = bytearray(self.MAGIC)
        header.extend(struct.pack("<HH", 0xFEFF, 0x0100))
        header.extend(struct.pack("<I", total_sdat_len))
        header.extend(struct.pack("<HH", 64, 4))
        header.extend(struct.pack("<II", new_symb_off, len(symb_block)))
        header.extend(struct.pack("<II", new_info_off, len(info_block)))
        header.extend(struct.pack("<II", new_fat_off, len(fat_block)))
        header.extend(struct.pack("<II", new_file_off, len(new_file_block)))
        header = header.ljust(64, b"\x00")

        # Combine all sections
        out = bytearray(header)
        if symb_block:
            out.extend(symb_block)
        if info_block:
            out.extend(info_block)
        if fat_pad > 0:
            out.extend(b"\x00" * fat_pad)
        out.extend(fat_block)
        if file_pad > 0:
            out.extend(b"\x00" * file_pad)
        out.extend(new_file_block)

        return bytes(out)
