"""
miorom.platforms.cdrom - Multi-Track CD-ROM Disc Engine & CUE/BIN Virtual Drive.
Supports multi-track discs (PS1, Saturn, Sega CD, PC-Engine CD),
LBA sector resolution, ISO data extraction/re-insertion, and CD-DA audio conversion to WAV.
"""

from miorom.platforms.cdrom.cue import (
    CueSheet,
    CueTrack,
    format_msf,
    lba_to_msf,
    msf_to_lba,
    parse_msf,
)
from miorom.platforms.cdrom.disc import (
    CueBinDisc,
    calculate_cdrom_edc,
)

__all__ = [
    "CueSheet",
    "CueTrack",
    "CueBinDisc",
    "calculate_cdrom_edc",
    "msf_to_lba",
    "lba_to_msf",
    "parse_msf",
    "format_msf",
]
