"""
miorom.archive.dma
~~~~~~~~~~~~~~~~~~
Generic DMA (Direct Memory Access) Filesystem Table abstraction.
Commonly used across Nintendo 64 and MIPS games (Zelda, Animal Crossing,
Pokemon Stadium) where virtual address spaces map to physical ROM offsets
with optional compression (e.g. Yaz0).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import BinaryIO, Dict, Iterator, List, Optional, Tuple, Union

from miorom.archive.container import ArchiveContainer, ArchiveEntry
from miorom.compression.yaz0 import Yaz0
from miorom.core.schema import BinaryStruct, U32
from miorom.result import MioRomResult
from miorom.security import sanitize_extract_path


class DmaTableEntryStruct(BinaryStruct):
    """Declarative 16-byte DMA filesystem table entry."""
    _endian = ">"
    v_start = U32()
    v_end = U32()
    p_start = U32()
    p_end = U32()


@dataclass
class DmaFileEntry(MioRomResult):
    """Resolved metadata describing an individual file in a DMA filesystem."""
    index: int
    name: str
    v_start: int
    v_end: int
    p_start: int
    p_end: int
    is_compressed: bool
    size_decompressed: int
    size_rom: int


class DmaTableArchive:
    """
    Generic DMA Table Filesystem Archive parser, extractor, and VFS mapper.
    """

    def __init__(self, entries: Optional[List[DmaFileEntry]] = None):
        self.entries: List[DmaFileEntry] = entries or []

    @classmethod
    def from_bytes(
        cls,
        data: bytes,
        table_offset: int,
        endian: str = ">",
        entry_names: Optional[Dict[int, str]] = None,
        max_entries: Optional[int] = None,
    ) -> "DmaTableArchive":
        """
        Parses a DMA table directly from ROM binary data.
        """
        names = entry_names or {}
        entries: List[DmaFileEntry] = []
        sz = DmaTableEntryStruct.sizeof()
        curr = table_offset
        idx = 0

        while curr + sz <= len(data):
            if max_entries is not None and idx >= max_entries:
                break

            rec = DmaTableEntryStruct.from_bytes(data, offset=curr, endian=endian)
            if rec.v_start == 0 and rec.v_end == 0 and rec.p_start == 0 and rec.p_end == 0:
                break

            # Skip dummy or deleted entries
            if rec.p_start == 0xFFFFFFFF and rec.p_end == 0xFFFFFFFF:
                curr += sz
                idx += 1
                continue

            is_comp = (rec.p_end != 0)
            rom_sz = (rec.p_end - rec.p_start) if is_comp else (rec.v_end - rec.v_start)
            dec_sz = rec.v_end - rec.v_start

            name = names.get(idx, f"file_{idx:04d}.bin")

            entries.append(DmaFileEntry(
                index=idx,
                name=name,
                v_start=rec.v_start,
                v_end=rec.v_end,
                p_start=rec.p_start,
                p_end=rec.p_end,
                is_compressed=is_comp,
                size_decompressed=dec_sz,
                size_rom=rom_sz,
            ))
            curr += sz
            idx += 1

        return cls(entries)

    def extract_file(self, rom_data: bytes, index: int, decompress_yaz0: bool = True) -> bytes:
        """Extract a single file by DMA entry index, with optional Yaz0 decompression."""
        entry = next((e for e in self.entries if e.index == index), None)
        if entry is None:
            raise KeyError(f"DMA file entry index {index} not found.")

        end = entry.p_end if entry.is_compressed else entry.p_start + entry.size_rom
        raw = rom_data[entry.p_start : end]

        if decompress_yaz0 and entry.is_compressed and raw.startswith(b"Yaz0"):
            try:
                return Yaz0.decompress(raw)
            except Exception:
                return raw
        return raw

    def extract_to_dir(
        self,
        rom_data: bytes,
        output_dir: str,
        decompress_yaz0: bool = True,
    ) -> List[str]:
        """Extract all files from ROM to output_dir."""
        os.makedirs(output_dir, exist_ok=True)
        extracted_paths: List[str] = []

        for e in self.entries:
            content = self.extract_file(rom_data, e.index, decompress_yaz0=decompress_yaz0)
            target = sanitize_extract_path(output_dir, e.name)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(content)
            extracted_paths.append(target)

        return extracted_paths

    def find_by_vaddr(self, vaddr: int) -> Optional[DmaFileEntry]:
        """Binary search / lookup for file containing the specified virtual address."""
        for e in self.entries:
            if e.v_start <= vaddr < e.v_end:
                return e
        return None
