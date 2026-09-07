"""
miorom.archive.dissector
~~~~~~~~~~~~~~~~~~~~~~~~
Heuristic Archive Dissector & Automated Container Reverse Engineer.
Analyzes proprietary/unknown game pack files (.bin, .dat, .pak, .arc), detects
implicit or explicit Table-of-Contents (TOC) arrays, determines endianness and
sub-stream types, and provides 1-click unpacking and format-preserving repacking.
"""

import os
import struct
from dataclasses import dataclass, field
from typing import BinaryIO, Dict, List, Optional, Tuple, Union

from miorom.archive.container import ArchiveContainer, ArchiveEntry
from miorom.archive.vfs import VirtualFileSystem


# Known magic signatures for sub-file type identification
MAGIC_EXT_MAP: List[Tuple[bytes, str]] = [
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"BM", ".bmp"),
    (b"\x10\x00\x00\x00", ".tim"),       # PSX TIM
    (b"RIFF", ".wav"),
    (b"OggS", ".ogg"),
    (b"NFTR", ".nftr"),                 # Nintendo Font Resource
    (b"NFTB", ".nftb"),
    (b"SSEQ", ".sseq"),                 # Nintendo Sound Sequence
    (b"SDAT", ".sdat"),                 # Nintendo Sound Data
    (b"BMD0", ".bmd"),                  # NDS 3D Model
    (b"BTX0", ".btx"),                  # NDS Texture
    (b"\x78\x9c", ".zlib"),             # zlib default
    (b"\x78\x01", ".zlib"),             # zlib low compression
    (b"\x78\xda", ".zlib"),             # zlib best compression
    (b"NANR", ".nanr"),                 # Nintendo Animation
    (b"NCER", ".ncer"),                 # Nintendo Cell
    (b"NCGR", ".ncgr"),                 # Nintendo Character Graphic
    (b"NCLR", ".nclr"),                 # Nintendo Color (Palette)
]


def detect_file_extension(data: bytes) -> str:
    """Guesses file extension based on magic header or text content."""
    if not data:
        return ".bin"

    # Check known magics
    for magic, ext in MAGIC_EXT_MAP:
        if data.startswith(magic):
            return ext

    # Nintendo LZ10/LZ11 header check (0x10 or 0x11 followed by 24-bit uncompressed size)
    if len(data) >= 4 and data[0] in (0x10, 0x11):
        unpacked_sz = data[1] | (data[2] << 8) | (data[3] << 16)
        if 0 < unpacked_sz <= 16 * 1024 * 1024:
            return ".lz"

    # Check if printable text / script
    printable = sum(1 for b in data[:min(len(data), 128)] if 32 <= b <= 126 or b in (9, 10, 13))
    if len(data) > 0 and (printable / min(len(data), 128)) > 0.85:
        return ".txt"

    return ".bin"


@dataclass
class DissectedArchive:
    """
    Result of a successful heuristic archive analysis.
    """
    format_type: str        # 'implicit_offsets', 'explicit_offset_size', 'explicit_size_offset', 'magic_carved'
    endianness: str         # '<' or '>'
    pointer_size: int       # 2 or 4
    header_size: int        # bytes occupied by header/TOC
    entries: List[ArchiveEntry] = field(default_factory=list)
    confidence: float = 0.0
    raw_data: bytes = field(default=b"", repr=False)
    has_count_prefix: bool = True

    def extract_to_dir(self, output_dir: str):
        """Extracts all dissected sub-files to directory."""
        os.makedirs(output_dir, exist_ok=True)
        for entry in self.entries:
            file_data = entry.data
            if file_data is None:
                file_data = self.raw_data[entry.offset : entry.offset + entry.size]
            filepath = os.path.join(output_dir, entry.name)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "wb") as f:
                f.write(file_data)

    def to_vfs(self) -> VirtualFileSystem:
        """Converts dissected archive entries into a VirtualFileSystem."""
        vfs = VirtualFileSystem()
        for entry in self.entries:
            file_data = entry.data
            if file_data is None:
                file_data = self.raw_data[entry.offset : entry.offset + entry.size]
            vfs.write(f"/{entry.name}", file_data)
        return vfs

    def repack(self, new_entries: Optional[List[ArchiveEntry]] = None, alignment: int = 4) -> bytes:
        """
        Reconstructs the archive using the exact detected TOC format and endianness.
        """
        active_entries = new_entries if new_entries is not None else self.entries
        num_entries = len(active_entries)
        end = self.endianness
        ptr_sz = self.pointer_size
        fmt_ptr = f"{end}I" if ptr_sz == 4 else f"{end}H"

        if self.format_type == "implicit_offsets":
            # Header has count (if has_count_prefix) + (num_entries + 1) offsets
            toc_entries_count = num_entries + 1
            toc_header_size = (ptr_sz if self.has_count_prefix else 0) + (toc_entries_count * ptr_sz)

            # Align base offset
            rem = toc_header_size % alignment
            base_data_offset = toc_header_size if rem == 0 else toc_header_size + (alignment - rem)

            # Calculate offsets
            offsets = []
            cur_off = base_data_offset
            data_blocks = bytearray()

            for entry in active_entries:
                offsets.append(cur_off)
                content = entry.data if entry.data is not None else self.raw_data[entry.offset : entry.offset + entry.size]
                data_blocks.extend(content)
                # Align next entry
                rem_align = len(data_blocks) % alignment
                if rem_align != 0:
                    data_blocks.extend(b"\x00" * (alignment - rem_align))
                cur_off = base_data_offset + len(data_blocks)

            offsets.append(cur_off)  # Sentinel end offset

            # Build header
            header = bytearray()
            if self.has_count_prefix:
                header.extend(struct.pack(fmt_ptr, num_entries))
            for off in offsets:
                header.extend(struct.pack(fmt_ptr, off))

            # Pad header to base_data_offset
            pad_len = base_data_offset - len(header)
            if pad_len > 0:
                header.extend(b"\x00" * pad_len)

            return bytes(header + data_blocks)

        elif self.format_type in ("explicit_offset_size", "explicit_size_offset"):
            toc_header_size = (ptr_sz if self.has_count_prefix else 0) + (num_entries * ptr_sz * 2)
            rem = toc_header_size % alignment
            base_data_offset = toc_header_size if rem == 0 else toc_header_size + (alignment - rem)

            toc_records = []
            data_blocks = bytearray()
            cur_off = base_data_offset

            for entry in active_entries:
                content = entry.data if entry.data is not None else self.raw_data[entry.offset : entry.offset + entry.size]
                sz = len(content)
                toc_records.append((cur_off, sz))
                data_blocks.extend(content)
                rem_align = len(data_blocks) % alignment
                if rem_align != 0:
                    data_blocks.extend(b"\x00" * (alignment - rem_align))
                cur_off = base_data_offset + len(data_blocks)

            header = bytearray()
            if self.has_count_prefix:
                header.extend(struct.pack(fmt_ptr, num_entries))
            for off, sz in toc_records:
                if self.format_type == "explicit_offset_size":
                    header.extend(struct.pack(f"{end}{'I' if ptr_sz==4 else 'H'}{'I' if ptr_sz==4 else 'H'}", off, sz))
                else:
                    header.extend(struct.pack(f"{end}{'I' if ptr_sz==4 else 'H'}{'I' if ptr_sz==4 else 'H'}", sz, off))

            pad_len = base_data_offset - len(header)
            if pad_len > 0:
                header.extend(b"\x00" * pad_len)

            return bytes(header + data_blocks)

        else:
            # Fallback: simple sequential pack
            container = ArchiveContainer(self.entries)
            return container.pack(alignment=alignment)


class HeuristicArchiveDissector:
    """
    Automated binary reverse engineering engine for game archives and resource packs.
    Heuristically discovers internal file layouts and builds reconstructed archives.
    """

    @classmethod
    def dissect(
        cls,
        data: bytes,
        min_entries: int = 2,
        max_entries: int = 10000,
    ) -> Optional[DissectedArchive]:
        """
        Examines binary data and reconstructs the most probable archive container structure.
        """
        if len(data) < 16:
            return None

        # 1. Try Explicit (Offset, Size) or (Size, Offset) pairs with Count prefix
        for endian in ("<", ">"):
            for ptr_sz in (4, 2):
                res = cls._try_explicit_pairs(data, endian, ptr_sz, min_entries, max_entries)
                if res and res.confidence >= 0.8:
                    return res

        # 2. Try Implicit Offset Table with Count prefix
        for endian in ("<", ">"):
            for ptr_sz in (4, 2):
                res = cls._try_implicit_offsets_with_count(data, endian, ptr_sz, min_entries, max_entries)
                if res and res.confidence >= 0.8:
                    return res

        # 3. Try Implicit Offset Table without Count prefix (pure offset table starting at 0)
        for endian in ("<", ">"):
            for ptr_sz in (4, 2):
                res = cls._try_implicit_offsets_no_count(data, endian, ptr_sz, min_entries, max_entries)
                if res and res.confidence >= 0.8:
                    return res

        # 4. Fallback: Magic / Signature Carving
        res_carved = cls._try_magic_carving(data, min_entries)
        if res_carved:
            return res_carved

        return None

    @classmethod
    def _try_implicit_offsets_with_count(
        cls,
        data: bytes,
        endian: str,
        ptr_sz: int,
        min_entries: int,
        max_entries: int,
    ) -> Optional[DissectedArchive]:
        fmt_val = f"{endian}I" if ptr_sz == 4 else f"{endian}H"
        count = struct.unpack_from(fmt_val, data, 0)[0]

        if not (min_entries <= count <= max_entries):
            return None

        # Table could have count + 1 offsets (with sentinel end) or count offsets
        table_bytes_needed = ptr_sz + (count * ptr_sz)
        if table_bytes_needed > len(data):
            return None

        # Read offsets
        offsets: List[int] = []
        has_sentinel = False

        for i in range(count):
            off = struct.unpack_from(fmt_val, data, ptr_sz + (i * ptr_sz))[0]
            offsets.append(off)

        # Check sentinel if exists
        sentinel_pos = ptr_sz + (count * ptr_sz)
        if sentinel_pos + ptr_sz <= len(data):
            sentinel_val = struct.unpack_from(fmt_val, data, sentinel_pos)[0]
            if sentinel_val > offsets[-1] and sentinel_val <= len(data):
                offsets.append(sentinel_val)
                has_sentinel = True

        # Validation: offsets must be strictly non-decreasing
        first_off = offsets[0]
        # First offset must be >= table header
        min_header_size = ptr_sz + ((count + (1 if has_sentinel else 0)) * ptr_sz)
        if first_off < min_header_size or first_off >= len(data):
            return None

        for j in range(len(offsets) - 1):
            if offsets[j] >= offsets[j + 1]:
                return None
            if offsets[j + 1] > len(data):
                return None

        # Construct entries
        entries: List[ArchiveEntry] = []
        num_items = count
        for i in range(num_items):
            start = offsets[i]
            if i + 1 < len(offsets):
                sz = offsets[i + 1] - start
            else:
                sz = len(data) - start

            chunk = data[start : start + sz]
            ext = detect_file_extension(chunk)
            name = f"file_{i:04d}{ext}"
            entries.append(ArchiveEntry(index=i, name=name, offset=start, size=sz, data=chunk))

        # Confidence calculation
        confidence = 0.90 if has_sentinel else 0.82

        return DissectedArchive(
            format_type="implicit_offsets",
            endianness=endian,
            pointer_size=ptr_sz,
            header_size=first_off,
            entries=entries,
            confidence=confidence,
            raw_data=data,
            has_count_prefix=True,
        )

    @classmethod
    def _try_explicit_pairs(
        cls,
        data: bytes,
        endian: str,
        ptr_sz: int,
        min_entries: int,
        max_entries: int,
    ) -> Optional[DissectedArchive]:
        fmt_val = f"{endian}I" if ptr_sz == 4 else f"{endian}H"
        count = struct.unpack_from(fmt_val, data, 0)[0]

        if not (min_entries <= count <= max_entries):
            return None

        table_bytes_needed = ptr_sz + (count * ptr_sz * 2)
        if table_bytes_needed > len(data):
            return None

        # Test both (offset, size) and (size, offset)
        for pair_mode in ("explicit_offset_size", "explicit_size_offset"):
            valid = True
            entries: List[ArchiveEntry] = []
            min_header = table_bytes_needed

            for i in range(count):
                rec_off = ptr_sz + (i * ptr_sz * 2)
                v1 = struct.unpack_from(fmt_val, data, rec_off)[0]
                v2 = struct.unpack_from(fmt_val, data, rec_off + ptr_sz)[0]

                off = v1 if pair_mode == "explicit_offset_size" else v2
                sz = v2 if pair_mode == "explicit_offset_size" else v1

                if off < min_header or off + sz > len(data) or sz <= 0:
                    valid = False
                    break

                chunk = data[off : off + sz]
                ext = detect_file_extension(chunk)
                name = f"file_{i:04d}{ext}"
                entries.append(ArchiveEntry(index=i, name=name, offset=off, size=sz, data=chunk))

            if valid and len(entries) == count:
                return DissectedArchive(
                    format_type=pair_mode,
                    endianness=endian,
                    pointer_size=ptr_sz,
                    header_size=entries[0].offset if entries else min_header,
                    entries=entries,
                    confidence=0.88,
                    raw_data=data,
                    has_count_prefix=True,
                )

        return None

    @classmethod
    def _try_implicit_offsets_no_count(
        cls,
        data: bytes,
        endian: str,
        ptr_sz: int,
        min_entries: int,
        max_entries: int,
    ) -> Optional[DissectedArchive]:
        fmt_val = f"{endian}I" if ptr_sz == 4 else f"{endian}H"
        # First entry offset tells us where the TOC ends
        first_off = struct.unpack_from(fmt_val, data, 0)[0]
        if first_off % ptr_sz != 0 or first_off < ptr_sz * min_entries or first_off >= len(data):
            return None

        candidate_count = first_off // ptr_sz
        if candidate_count > max_entries:
            return None

        offsets: List[int] = []
        for i in range(candidate_count):
            off = struct.unpack_from(fmt_val, data, i * ptr_sz)[0]
            offsets.append(off)

        # Check monotonically increasing
        for j in range(len(offsets) - 1):
            if offsets[j] > offsets[j + 1] or offsets[j + 1] > len(data):
                return None

        # Build entries
        entries: List[ArchiveEntry] = []
        for i in range(candidate_count):
            start = offsets[i]
            sz = (offsets[i + 1] - start) if i + 1 < candidate_count else (len(data) - start)
            chunk = data[start : start + sz]
            ext = detect_file_extension(chunk)
            name = f"file_{i:04d}{ext}"
            entries.append(ArchiveEntry(index=i, name=name, offset=start, size=sz, data=chunk))

        return DissectedArchive(
            format_type="implicit_offsets",
            endianness=endian,
            pointer_size=ptr_sz,
            header_size=first_off,
            entries=entries,
            confidence=0.84,
            raw_data=data,
            has_count_prefix=False,
        )

    @classmethod
    def _try_magic_carving(cls, data: bytes, min_entries: int) -> Optional[DissectedArchive]:
        """Scans binary data for multiple occurrences of known magic signatures."""
        found_offsets: List[Tuple[int, str]] = []
        i = 0
        data_len = len(data)

        while i < data_len - 4:
            for magic, ext in MAGIC_EXT_MAP:
                if data.startswith(magic, i):
                    found_offsets.append((i, ext))
                    i += len(magic)
                    break
            else:
                # Check Nintendo LZ10/LZ11 (4-byte alignment typically)
                if i % 4 == 0 and data[i] in (0x10, 0x11):
                    unp_sz = data[i + 1] | (data[i + 2] << 8) | (data[i + 3] << 16)
                    if 128 <= unp_sz <= 16 * 1024 * 1024:
                        found_offsets.append((i, ".lz"))
                        i += 4
                        continue
                i += 1

        if len(found_offsets) < min_entries:
            return None

        # Sort and deduplicate offsets
        found_offsets.sort(key=lambda x: x[0])
        entries: List[ArchiveEntry] = []

        for idx, (start_off, ext) in enumerate(found_offsets):
            end_off = found_offsets[idx + 1][0] if idx + 1 < len(found_offsets) else data_len
            sz = end_off - start_off
            chunk = data[start_off:end_off]
            entries.append(ArchiveEntry(index=idx, name=f"carved_{idx:04d}{ext}", offset=start_off, size=sz, data=chunk))

        return DissectedArchive(
            format_type="magic_carved",
            endianness="<",
            pointer_size=4,
            header_size=found_offsets[0][0],
            entries=entries,
            confidence=0.75,
            raw_data=data,
            has_count_prefix=False,
        )
