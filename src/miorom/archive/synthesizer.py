from miorom.result import MioRomResult
import math
import struct
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


from miorom.errors import ParseError

@dataclass
class SynthesizedEntry(MioRomResult):
    index: int
    offset: int
    size: int
    data: bytes
    entropy: float
    guessed_type: str  # "COMPRESSED", "TEXT", "AUDIO", "IMAGE", "RAW"


@dataclass
class ArchiveLayout(MioRomResult):
    magic: bytes
    magic_ascii: str
    file_count: int
    toc_offset: int
    toc_stride: int
    endian: str
    entries: List[SynthesizedEntry] = field(default_factory=list)
    generated_python_code: str = ""

    def summary(self) -> str:
        lines = [
            "==================================================",
            "      Synthesized Archive Container Layout        ",
            "==================================================",
            f"  Magic Header       : {self.magic.hex().upper()} ('{self.magic_ascii}')",
            f"  File Count         : {self.file_count}",
            f"  TOC Offset         : 0x{self.toc_offset:04X} (Stride: {self.toc_stride} bytes)",
            f"  Endianness         : {'Big-Endian' if self.endian == '>' else 'Little-Endian'}",
            f"  Detected Entries   : {len(self.entries)}",
        ]
        if self.entries:
            lines.append("  Sub-files preview:")
            for e in self.entries[:5]:
                lines.append(f"    - [{e.index:03d}] Off: 0x{e.offset:06X}, Size: {e.size:>6} B, Ent: {e.entropy:4.2f} [{e.guessed_type}]")
            if len(self.entries) > 5:
                lines.append(f"    ... and {len(self.entries) - 5} more entries.")
        lines.append("==================================================")
        return "\n".join(lines)


class ArchiveSynthesizer:
    """
    Heuristic Reverse-Engineer for undocumented proprietary archive containers (.bin, .dat, .pak).
    Detects table of contents, extracts entries, calculates entropy,
    and auto-generates Python unpacker/repacker code.
    """

    @classmethod
    def analyze(cls, data: bytes) -> ArchiveLayout:
        total_len = len(data)
        if total_len < 16:
            raise ParseError(f"Data size {total_len} is too small to be a container archive.")

        # 1. Detect magic (first 4 bytes)
        magic = data[:4]
        try:
            magic_ascii = magic.decode("ascii").strip("\x00")
        except Exception:
            magic_ascii = magic.hex()

        # 2. Test endianness and file count at candidate header offsets (4, 8, 12, 16)
        best_endian = None
        best_count = 0
        best_toc_off = 0
        best_stride = 0
        best_entries: List[Tuple[int, int]] = []

        for endian in ("<", ">"):
            for count_off in (4, 8, 0, 12):
                if count_off + 4 > total_len:
                    continue
                cand_count = struct.unpack(f"{endian}I", data[count_off : count_off + 4])[0]
                # Reasonable file count bounds
                if not (2 <= cand_count <= 10000):
                    continue

                # Test candidate TOC starting offsets
                for toc_off in (count_off + 4, 16, 32, 64, 128, 256):
                    if toc_off >= total_len:
                        continue
                    # Test strides (8: offset, size; 12: offset, size, id; 16: offset, size, hash, flags)
                    for stride in (8, 12, 16):
                        toc_len = cand_count * stride
                        if toc_off + toc_len > total_len:
                            continue

                        valid_entries = cls._validate_toc(data, toc_off, cand_count, stride, endian)
                        if valid_entries and len(valid_entries) > len(best_entries):
                            best_endian = endian
                            best_count = cand_count
                            best_toc_off = toc_off
                            best_stride = stride
                            best_entries = valid_entries

        # Fallback: simple table of offsets starting at 0x00 or 0x04
        if not best_entries:
            for endian in ("<", ">"):
                cand_entries = cls._probe_offset_table(data, endian)
                if len(cand_entries) >= 2 and len(cand_entries) > len(best_entries):
                    best_endian = endian
                    best_count = len(cand_entries)
                    best_toc_off = 0
                    best_stride = 4
                    best_entries = cand_entries

        if not best_entries:
            raise RuntimeError("Could not heuristically identify container TOC structure in binary.")

        # 3. Extract entries and classify types
        extracted: List[SynthesizedEntry] = []
        for idx, (off, sz) in enumerate(best_entries):
            sub_data = data[off : off + sz]
            ent = cls._calculate_entropy(sub_data)
            gtype = cls._guess_content_type(sub_data, ent)
            extracted.append(
                SynthesizedEntry(
                    index=idx,
                    offset=off,
                    size=sz,
                    data=sub_data,
                    entropy=ent,
                    guessed_type=gtype,
                )
            )

        # 4. Generate Python class code
        py_code = cls._generate_python_class(
            magic=magic,
            endian=best_endian or "<",
            toc_offset=best_toc_off,
            toc_stride=best_stride,
            file_count=best_count,
        )

        return ArchiveLayout(
            magic=magic,
            magic_ascii=magic_ascii,
            file_count=best_count,
            toc_offset=best_toc_off,
            toc_stride=best_stride,
            endian=best_endian or "<",
            entries=extracted,
            generated_python_code=py_code,
        )

    @classmethod
    def _validate_toc(
        cls,
        data: bytes,
        toc_off: int,
        count: int,
        stride: int,
        endian: str,
    ) -> Optional[List[Tuple[int, int]]]:
        entries: List[Tuple[int, int]] = []
        total_len = len(data)
        prev_off = 0

        for i in range(count):
            e_off = toc_off + i * stride
            off, sz = struct.unpack(f"{endian}II", data[e_off : e_off + 8])

            # Offsets must be >= TOC end and < total_len
            if off < toc_off + count * stride or off >= total_len:
                return None
            if sz > total_len or off + sz > total_len:
                return None
            if off < prev_off:  # Must be forward
                return None

            prev_off = off
            entries.append((off, sz))

        return entries

    @classmethod
    def _probe_offset_table(cls, data: bytes, endian: str) -> List[Tuple[int, int]]:
        entries: List[Tuple[int, int]] = []
        total_len = len(data)
        pos = 0
        offsets: List[int] = []

        while pos + 4 <= total_len:
            val = struct.unpack(f"{endian}I", data[pos : pos + 4])[0]
            if not offsets:
                # First offset must be after candidate table
                if 16 <= val < total_len:
                    offsets.append(val)
                else:
                    break
            else:
                if val >= offsets[-1] and val < total_len:
                    offsets.append(val)
                else:
                    break
            pos += 4

        if len(offsets) >= 2:
            for i in range(len(offsets) - 1):
                sz = offsets[i + 1] - offsets[i]
                entries.append((offsets[i], sz))
            # Last entry size up to EOF or alignment
            last_sz = total_len - offsets[-1]
            entries.append((offsets[-1], last_sz))

        return entries

    @classmethod
    def _calculate_entropy(cls, sub: bytes) -> float:
        if not sub:
            return 0.0
        counts = Counter(sub)
        l = len(sub)
        return -sum((c / l) * math.log2(c / l) for c in counts.values())

    @classmethod
    def _guess_content_type(cls, sub: bytes, entropy: float) -> str:
        if not sub:
            return "EMPTY"
        if sub[:4] in (b"Yaz0", b"LZ10", b"LZ11") or entropy >= 7.2:
            return "COMPRESSED"
        if sub[:4] in (b"\x89PNG", b"GIF8", b"BM\x00\x00") or sub[:3] == b"TPL":
            return "IMAGE"
        if sub[:4] in (b"RIFF", b"SNDS", b"SDAT"):
            return "AUDIO"
        # Check printable ASCII text
        printable = sum(1 for b in sub if 0x20 <= b <= 0x7E or b in (0x0A, 0x0D, 0x09))
        if printable / len(sub) >= 0.75:
            return "TEXT"
        return "RAW"

    @classmethod
    def _generate_python_class(
        cls,
        magic: bytes,
        endian: str,
        toc_offset: int,
        toc_stride: int,
        file_count: int,
    ) -> str:
        end_str = "Big-Endian" if endian == ">" else "Little-Endian"
        return f'''"""
Synthesized Archive Unpacker and Repacker
Auto-generated by miorom.archive.ArchiveSynthesizer
Format: {end_str}, Magic: {magic.hex()}
"""
import struct
from typing import List

class SynthesizedArchive:
    MAGIC = {repr(magic)}
    ENDIAN = "{endian}"
    TOC_OFFSET = {toc_offset}
    TOC_STRIDE = {toc_stride}

    def __init__(self, data: bytes):
        self.data = data
        self.files: List[bytes] = []
        self._unpack()

    def _unpack(self):
        count = {file_count}
        for i in range(count):
            e_off = self.TOC_OFFSET + i * self.TOC_STRIDE
            off, size = struct.unpack_from(f"{{self.ENDIAN}}II", self.data, e_off)
            self.files.append(self.data[off : off + size])

    def pack(self) -> bytes:
        out = bytearray(self.data[:self.TOC_OFFSET])
        cur_off = self.TOC_OFFSET + len(self.files) * self.TOC_STRIDE
        # align to 16 bytes
        rem = cur_off % 16
        if rem != 0:
            cur_off += 16 - rem
        
        toc = bytearray()
        payload = bytearray()
        
        for f in self.files:
            toc += struct.pack(f"{{self.ENDIAN}}II", cur_off + len(payload), len(f))
            payload += f
            # 16-byte alignment
            pad = (16 - (len(payload) % 16)) % 16
            payload += b"\\x00" * pad

        return bytes(out + toc + payload)
'''
