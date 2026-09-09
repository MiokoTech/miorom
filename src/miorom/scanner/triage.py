"""
miorom.scanner.triage
~~~~~~~~~~~~~~~~~~~~~
Automated ROM Triage Engine and Asset Classifier.
Scans raw ROM dumps, unpacked filesystem directories, and binary containers to
instantly categorize files into Text, Graphics, Audio, Machine Code, Compressed Streams,
and Padding, recommending the exact reverse engineering tools to apply.
"""

from miorom.result import MioRomResult
import math
import os
import struct
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterator, List, Optional, Tuple, Union


class AssetType(str, Enum):
    TEXT_SCRIPT = "TEXT_SCRIPT"
    COMPRESSED_DATA = "COMPRESSED_DATA"
    EXECUTABLE_CODE = "EXECUTABLE_CODE"
    TEXTURE_GRAPHICS = "TEXTURE_GRAPHICS"
    AUDIO_MUSIC = "AUDIO_MUSIC"
    ARCHIVE_CONTAINER = "ARCHIVE_CONTAINER"
    DATA_TABLE = "DATA_TABLE"
    PADDING_EMPTY = "PADDING_EMPTY"
    UNKNOWN = "UNKNOWN"


@dataclass
class FileTriageRecord(MioRomResult):
    """Detailed triage findings for a single binary file or chunk."""
    path: str
    size: int
    entropy: float
    asset_type: AssetType
    format_detected: str
    confidence: float
    details: str
    suggested_tool: str

    def __repr__(self) -> str:
        return f"<FileTriageRecord '{os.path.basename(self.path)}' type={self.asset_type.value} entropy={self.entropy:.2f}>"


@dataclass
class TriageReport(MioRomResult):
    """Summary report across an entire directory or asset collection."""
    records: List[FileTriageRecord] = field(default_factory=list)

    @property
    def total_files(self) -> int:
        return len(self.records)

    def filter_by_type(self, asset_type: Union[AssetType, str]) -> List[FileTriageRecord]:
        target = asset_type.value if isinstance(asset_type, AssetType) else asset_type
        return [r for r in self.records if r.asset_type.value == target]

    def summary(self) -> str:
        counts = Counter(r.asset_type.value for r in self.records)
        lines = [
            f"=== ROM Triage Report: {self.total_files} files analyzed ===",
            f"{'Category':<22} {'Count':<8} {'Suggested Tools'}",
            "-" * 65,
        ]
        tool_hints = {
            AssetType.TEXT_SCRIPT.value: "CharMap, RelativeSearcher, ScriptVM",
            AssetType.COMPRESSED_DATA.value: "CompressionCarver, decompress",
            AssetType.EXECUTABLE_CODE.value: "UniversalInstructionScanner, Disassembler",
            AssetType.TEXTURE_GRAPHICS.value: "TileDecoder, Palette, ImageBridge",
            AssetType.AUDIO_MUSIC.value: "SSEQSequence, AudioEngine",
            AssetType.ARCHIVE_CONTAINER.value: "NARCArchive, TocPair, FstInjector",
            AssetType.DATA_TABLE.value: "PointerScanner, CascadingRelocator",
            AssetType.PADDING_EMPTY.value: "SlackSpaceManager",
        }
        for cat, cnt in counts.most_common():
            lines.append(f"{cat:<22} {cnt:<8} {tool_hints.get(cat, '-')}")
        return "\n".join(lines)


class RomTriageEngine:
    """
    Automated triage scanner for rapid reverse engineering reconnaissance.
    """

    @staticmethod
    def calculate_entropy(data: bytes) -> float:
        if not data:
            return 0.0
        counts = Counter(data)
        length = len(data)
        return -sum((c / length) * math.log2(c / length) for c in counts.values())

    @classmethod
    def triage_buffer(cls, data: bytes, name: str = "buffer.bin") -> FileTriageRecord:
        """Classifies a binary buffer into its likely asset category."""
        size = len(data)
        if size == 0:
            return FileTriageRecord(
                path=name,
                size=0,
                entropy=0.0,
                asset_type=AssetType.PADDING_EMPTY,
                format_detected="Empty",
                confidence=1.0,
                details="0-byte empty file",
                suggested_tool="-",
            )

        ent = cls.calculate_entropy(data)

        # 1. Check for pure padding (entropy < 1.0)
        if ent < 1.0 and (data[0] in (0x00, 0xFF) and data.count(data[0]) > size * 0.95):
            return FileTriageRecord(
                path=name,
                size=size,
                entropy=ent,
                asset_type=AssetType.PADDING_EMPTY,
                format_detected=f"Filler 0x{data[0]:02X}",
                confidence=0.99,
                details=f"Padding region filled with 0x{data[0]:02X}",
                suggested_tool="SlackSpaceManager",
            )

        # 2. Check Magic signatures
        magic4 = data[:4]
        magic8 = data[:8] if size >= 8 else b""

        # Known archives
        if magic4 == b"NARC":
            return FileTriageRecord(name, size, ent, AssetType.ARCHIVE_CONTAINER, "NARC", 0.99, "Nintendo NARC Archive", "NARCArchive")
        if magic4 == b"NLCM":
            return FileTriageRecord(name, size, ent, AssetType.ARCHIVE_CONTAINER, "NLCM", 0.99, "Neverland NLCM Container", "TocPair")
        if data[:3] == b"U\xAA8-" or magic4 == b"\x55\xAA\x38\x2D":
            return FileTriageRecord(name, size, ent, AssetType.ARCHIVE_CONTAINER, "U8", 0.99, "Nintendo U8 Archive", "U8Archive")

        # Known graphics
        if magic4 == b"PNG\r" or data[:8] == b"\x89PNG\r\n\x1a\n":
            return FileTriageRecord(name, size, ent, AssetType.TEXTURE_GRAPHICS, "PNG", 1.0, "PNG Image", "ImageBridge")
        if data[:2] == b"BM":
            return FileTriageRecord(name, size, ent, AssetType.TEXTURE_GRAPHICS, "BMP", 0.95, "BMP Bitmap", "ImageBridge")
        if magic4 in (b"RGCN", b"NCGR"):
            return FileTriageRecord(name, size, ent, AssetType.TEXTURE_GRAPHICS, "NCGR", 0.99, "Nintendo DS Character Graphics Tile", "TileDecoder")
        if magic4 in (b"RLCN", b"NCLR"):
            return FileTriageRecord(name, size, ent, AssetType.TEXTURE_GRAPHICS, "NCLR", 0.99, "Nintendo DS Palette", "Palette")

        # Known fonts
        if magic4 in (b"RTFN", b"NFTR"):
            return FileTriageRecord(name, size, ent, AssetType.TEXTURE_GRAPHICS, "NFTR", 0.99, "Nintendo DS NFTR Font", "NFTRFont")
        if magic4 in (b"RFNB", b"BRFNT"):
            return FileTriageRecord(name, size, ent, AssetType.TEXTURE_GRAPHICS, "BRFNT", 0.99, "Wii BRFNT Font", "BRFNTFont")

        # Known audio
        if magic4 in (b"QESS", b"SSEQ"):
            return FileTriageRecord(name, size, ent, AssetType.AUDIO_MUSIC, "SSEQ", 0.99, "Nintendo DS Sound Sequence", "SSEQSequence")
        if magic4 == b"RIFF":
            return FileTriageRecord(name, size, ent, AssetType.AUDIO_MUSIC, "WAV/RIFF", 0.99, "RIFF Wave Audio", "AudioEngine")
        if magic4 == b"MThd":
            return FileTriageRecord(name, size, ent, AssetType.AUDIO_MUSIC, "MIDI", 0.99, "Standard MIDI Audio", "AudioEngine")

        # Known executables
        if data[:4] == b"\x7FELF":
            return FileTriageRecord(name, size, ent, AssetType.EXECUTABLE_CODE, "ELF", 0.99, "ELF Executable", "UniversalInstructionScanner")

        # Known compression formats
        if magic4 == b"Yaz0":
            return FileTriageRecord(name, size, ent, AssetType.COMPRESSED_DATA, "Yaz0", 1.0, "Yaz0 Compressed Stream", "CompressionCarver")
        if data[0] in (0x10, 0x11, 0x30, 0x24, 0x28) and size >= 4:
            cand_sz = data[1] | (data[2] << 8) | (data[3] << 16)
            if cand_sz > size and ent > 6.0:
                fmt_name = "LZ10" if data[0] == 0x10 else ("LZ11" if data[0] == 0x11 else "RLE")
                return FileTriageRecord(name, size, ent, AssetType.COMPRESSED_DATA, fmt_name, 0.90, f"Nintendo {fmt_name} Stream", "CompressionCarver")

        # 3. High entropy check (> 7.2 => Compressed or Encrypted)
        if ent >= 7.2:
            return FileTriageRecord(
                name, size, ent, AssetType.COMPRESSED_DATA, "HighEntropy", 0.85,
                f"Entropy {ent:.2f} indicates compressed payload or crypto", "CompressionCarver",
            )

        # 4. Printable ASCII / text density sampling
        sample = data[:min(size, 4096)]
        printable = sum(1 for b in sample if 32 <= b <= 126 or b in (9, 10, 13))
        ascii_ratio = printable / len(sample)

        if ascii_ratio >= 0.70:
            return FileTriageRecord(
                name, size, ent, AssetType.TEXT_SCRIPT, "ASCII_Text", 0.90,
                f"Printable text ratio: {ascii_ratio:.1%}", "CharMap, RelativeSearcher",
            )

        # 5. Pointer Table / Data Matrix
        # Frequent nulls and pointer patterns: e.g. 0x0000 / 0x0800 in 32-bit words
        if size >= 16 and size % 4 == 0:
            words = [struct.unpack_from("<I", sample, k)[0] for k in range(0, min(len(sample), 64), 4)]
            # Monotonically increasing addresses indicates a pointer table
            increasing = sum(1 for idx in range(len(words) - 1) if 0 < words[idx] < words[idx + 1] < size * 10)
            if increasing >= len(words) // 2:
                return FileTriageRecord(
                    name, size, ent, AssetType.DATA_TABLE, "PointerTable", 0.80,
                    "Monotonically increasing 32-bit word table", "PointerScanner, CascadingRelocator",
                )

        # 6. Moderate entropy machine code (5.5 - 7.1)
        if 5.5 <= ent <= 7.1:
            return FileTriageRecord(
                name, size, ent, AssetType.EXECUTABLE_CODE, "MachineCode", 0.65,
                f"Instruction entropy range {ent:.2f}", "UniversalInstructionScanner",
            )

        return FileTriageRecord(
            name, size, ent, AssetType.UNKNOWN, "GenericBinary", 0.50,
            f"Unclassified binary blob (entropy: {ent:.2f})", "SmartInspector",
        )

    @classmethod
    def triage_directory(cls, dir_path: str, recursive: bool = True) -> TriageReport:
        """Recursively scans a directory and classifies all contained files."""
        report = TriageReport()
        report.records.extend(cls.iter_directory(dir_path, recursive=recursive))
        return report

    @classmethod
    def iter_directory(cls, dir_path: str, recursive: bool = True) -> Iterator[FileTriageRecord]:
        """Yield triage records for each readable file without waiting for the full report."""
        if not os.path.exists(dir_path):
            raise FileNotFoundError(f"Directory not found: {dir_path}")

        for root, _, files in os.walk(dir_path):
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, "rb") as f:
                        data = f.read()
                    rec = cls.triage_buffer(data, name=file_path)
                    yield rec
                except Exception:
                    pass
            if not recursive:
                break
