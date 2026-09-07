import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


def msf_to_lba(m: int, s: int, f: int) -> int:
    """Convert Minutes:Seconds:Frames (75 fps) to LBA sector index."""
    return (m * 60 + s) * 75 + f


def lba_to_msf(lba: int) -> Tuple[int, int, int]:
    """Convert LBA sector index to (m, s, f)."""
    m = lba // (60 * 75)
    rem = lba % (60 * 75)
    s = rem // 75
    f = rem % 75
    return m, s, f


def parse_msf(msf_str: str) -> int:
    """Parse 'MM:SS:FF' string to LBA."""
    parts = msf_str.strip().split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid MSF timestamp '{msf_str}'. Expected MM:SS:FF.")
    return msf_to_lba(int(parts[0]), int(parts[1]), int(parts[2]))


def format_msf(lba: int) -> str:
    """Format LBA sector index to 'MM:SS:FF' string."""
    m, s, f = lba_to_msf(lba)
    return f"{m:02d}:{s:02d}:{f:02d}"


@dataclass
class CueTrack:
    """Represents a single track within a CD CUE sheet."""
    number: int
    track_type: str  # "MODE1/2352", "MODE2/2352", "AUDIO", "MODE1/2048", "MODE2/2336"
    file_name: str
    file_type: str = "BINARY"
    indexes: Dict[int, int] = field(default_factory=dict)  # index_num -> relative LBA in file
    pregap: int = 0   # LBA frames
    postgap: int = 0  # LBA frames
    start_lba: int = 0  # Absolute LBA on disc
    sector_count: int = 0

    @property
    def sector_size(self) -> int:
        if "/" in self.track_type:
            return int(self.track_type.split("/")[1])
        if self.track_type == "AUDIO":
            return 2352
        return 2352

    @property
    def is_data_track(self) -> bool:
        return self.track_type.startswith("MODE")

    @property
    def is_audio_track(self) -> bool:
        return self.track_type == "AUDIO"


class CueSheet:
    """
    Parser and serializer for CDRWIN .CUE sheet files.
    Supports single-bin and multi-bin disc configurations, subchannels, and tracks.
    """

    def __init__(self):
        self.tracks: List[CueTrack] = []
        # List of (file_name, file_type, [tracks_in_file])
        self.files: List[Tuple[str, str, List[CueTrack]]] = []

    @classmethod
    def from_string(cls, content: str) -> "CueSheet":
        cue = cls()
        current_file = None
        current_file_type = "BINARY"
        current_track: Optional[CueTrack] = None
        tracks_in_current_file: List[CueTrack] = []

        lines = content.splitlines()
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            # FILE "filename" BINARY
            file_match = re.match(r'^FILE\s+["\']?([^"\']+)["\']?\s+([A-Za-z0-9]+)$', line, re.IGNORECASE)
            if file_match:
                if current_file is not None and tracks_in_current_file:
                    cue.files.append((current_file, current_file_type, tracks_in_current_file))
                    tracks_in_current_file = []
                current_file = file_match.group(1)
                current_file_type = file_match.group(2).upper()
                current_track = None
                continue

            # TRACK 01 MODE1/2352
            track_match = re.match(r'^TRACK\s+(\d+)\s+([A-Za-z0-9/]+)$', line, re.IGNORECASE)
            if track_match:
                track_num = int(track_match.group(1))
                track_type = track_match.group(2).upper()
                fn = current_file if current_file else ""
                current_track = CueTrack(
                    number=track_num,
                    track_type=track_type,
                    file_name=fn,
                    file_type=current_file_type,
                )
                cue.tracks.append(current_track)
                tracks_in_current_file.append(current_track)
                continue

            # INDEX 01 00:00:00
            index_match = re.match(r'^INDEX\s+(\d+)\s+(\d{2}:\d{2}:\d{2})$', line, re.IGNORECASE)
            if index_match and current_track is not None:
                idx_num = int(index_match.group(1))
                lba = parse_msf(index_match.group(2))
                current_track.indexes[idx_num] = lba
                continue

            # PREGAP 00:02:00
            pregap_match = re.match(r'^PREGAP\s+(\d{2}:\d{2}:\d{2})$', line, re.IGNORECASE)
            if pregap_match and current_track is not None:
                current_track.pregap = parse_msf(pregap_match.group(1))
                continue

            # POSTGAP 00:02:00
            postgap_match = re.match(r'^POSTGAP\s+(\d{2}:\d{2}:\d{2})$', line, re.IGNORECASE)
            if postgap_match and current_track is not None:
                current_track.postgap = parse_msf(postgap_match.group(1))
                continue

        if current_file is not None and tracks_in_current_file:
            cue.files.append((current_file, current_file_type, tracks_in_current_file))

        return cue

    @classmethod
    def from_file(cls, path: str) -> "CueSheet":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return cls.from_string(f.read())

    def to_string(self) -> str:
        """Serialize CueSheet back to CUE formatted text."""
        lines = []
        for fn, ftype, tracks in self.files:
            lines.append(f'FILE "{fn}" {ftype}')
            for trk in tracks:
                lines.append(f"  TRACK {trk.number:02d} {trk.track_type}")
                if trk.pregap > 0:
                    lines.append(f"    PREGAP {format_msf(trk.pregap)}")
                for idx_num in sorted(trk.indexes.keys()):
                    lines.append(f"    INDEX {idx_num:02d} {format_msf(trk.indexes[idx_num])}")
                if trk.postgap > 0:
                    lines.append(f"    POSTGAP {format_msf(trk.postgap)}")
        return "\n".join(lines) + "\n"
