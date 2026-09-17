import os
from typing import Any, Dict, Optional

from miorom.errors import PatchError
from miorom.patch.bank_crosser import (
    BankCrossingRelocator,
    BankedStringLocation,
    BankPartitionReport,
)
from miorom.patch.bps import BpsPatcher
from miorom.patch.cheats import (
    CheatCode,
    GameBoyGameGenie,
    GameShark,
    GenesisGameGenie,
    NesGameGenie,
    SnesGameGenie,
    hard_patch_rom,
    parse_cheat_code,
)
from miorom.patch.hunks import PatchHunk, filter_hunks, merge_patches
from miorom.patch.ips import IpsPatcher
from miorom.patch.patch_writer import PatchRecord, PatchWriter
from miorom.patch.pointer_remapper import (
    MultiPointerRemapper,
    RelativePointerTable,
)
from miorom.patch.pointerizer import (
    PascalStringManager,
    PointerizedSlot,
    SlotConversionReport,
    SlotToHeapPointerizer,
)
from miorom.patch.ppf import PPFPatcher
from miorom.patch.relocator import (
    AutoRelocationManager,
    RelocatablePointer,
    RelocationRecord,
    RelocationSummary,
)
from miorom.patch.slack import FarMemoryHeap, SlackBlock, SlackSpaceManager
from miorom.patch.ups import UpsPatcher
from miorom.patch.xdelta import XdeltaPatcher
from miorom.platforms.wii.riivolution import (
    RiivolutionFile,
    apply_riivolution_to_disc,
    create_riivolution_package,
)

__all__ = [
    "IpsPatcher",
    "BpsPatcher",
    "UpsPatcher",
    "PPFPatcher",
    "PatchHunk",
    "filter_hunks",
    "merge_patches",
    "XdeltaPatcher",
    "SlackSpaceManager",
    "SlackBlock",
    "FarMemoryHeap",
    "RelocatablePointer",
    "RelocationRecord",
    "RelocationSummary",
    "AutoRelocationManager",
    "SlotToHeapPointerizer",
    "PascalStringManager",
    "PointerizedSlot",
    "SlotConversionReport",
    "BankCrossingRelocator",
    "BankPartitionReport",
    "BankedStringLocation",
    "RelativePointerTable",
    "MultiPointerRemapper",
    "PatchWriter",
    "PatchRecord",
    "CheatCode",
    "NesGameGenie",
    "SnesGameGenie",
    "GenesisGameGenie",
    "GameBoyGameGenie",
    "GameShark",
    "parse_cheat_code",
    "hard_patch_rom",
    "create_patch",
    "apply_patch",
    "inspect_patch",
    "RiivolutionFile",
    "create_riivolution_package",
    "apply_riivolution_to_disc",
]


def detect_format_from_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".ips"]:
        return "ips"
    elif ext in [".bps"]:
        return "bps"
    elif ext in [".ups"]:
        return "ups"
    elif ext in [".ppf"]:
        return "ppf"
    elif ext in [".xdelta", ".xdelta3", ".vcdiff"]:
        return "xdelta"
    return "bps"  # default modern


def create_patch(
    source_path: str,
    target_path: str,
    patch_path: str,
    fmt: Optional[str] = None
):
    """
    Create a patch from source_path to target_path.
    Auto-detects format from patch_path extension (.ips, .bps, .ups, .ppf, .xdelta) if fmt is None.
    """
    format_type = fmt.lower() if fmt else detect_format_from_filename(patch_path)

    if format_type == "ips":
        IpsPatcher.create_file(source_path, target_path, patch_path)
    elif format_type == "bps":
        BpsPatcher.create_file(source_path, target_path, patch_path)
    elif format_type == "ups":
        UpsPatcher.create_file(source_path, target_path, patch_path)
    elif format_type == "ppf":
        PPFPatcher.create_file(source_path, target_path, patch_path)
    elif format_type == "xdelta":
        XdeltaPatcher.create_patch(source_path, target_path, patch_path)
    else:
        raise PatchError(f"Unsupported patch format: '{format_type}'. Choose 'ips', 'bps', 'ups', 'ppf', or 'xdelta'.")


def apply_patch(
    source_path: str,
    patch_path: str,
    output_path: str,
    fmt: Optional[str] = None
):
    """
    Apply a patch to source_path and write output to output_path.
    Auto-detects format from patch_path extension (.ips, .bps, .ups, .ppf, .xdelta) or magic bytes if fmt is None.
    """
    format_type = fmt.lower() if fmt else None
    if not format_type:
        # Check magic bytes first
        with open(patch_path, "rb") as f:
            header = f.read(5)
        if header.startswith(b"PATCH"):
            format_type = "ips"
        elif header.startswith(b"BPS1"):
            format_type = "bps"
        elif header.startswith(b"UPS1"):
            format_type = "ups"
        elif header in (b"PPF10", b"PPF20", b"PPF30"):
            format_type = "ppf"
        else:
            format_type = detect_format_from_filename(patch_path)

    if format_type == "ips":
        IpsPatcher.apply_file(source_path, patch_path, output_path)
    elif format_type == "bps":
        BpsPatcher.apply_file(source_path, patch_path, output_path)
    elif format_type == "ups":
        UpsPatcher.apply_file(source_path, patch_path, output_path)
    elif format_type == "ppf":
        PPFPatcher.apply_file(source_path, patch_path, output_path)
    elif format_type == "xdelta":
        XdeltaPatcher.apply_patch(source_path, patch_path, output_path)
    else:
        raise PatchError(f"Unsupported patch format: '{format_type}'.")


def inspect_patch(patch_path: str) -> Dict[str, Any]:
    """
    Inspects a patch file (IPS, BPS, UPS, PPF, XDelta) and returns a metadata dictionary.
    """
    if not os.path.exists(patch_path):
        raise FileNotFoundError(f"Patch file not found: {patch_path}")

    with open(patch_path, "rb") as f:
        data = f.read()

    fmt = None
    if data.startswith(b"PATCH"):
        fmt = "ips"
    elif data.startswith(b"BPS1"):
        fmt = "bps"
    elif data.startswith(b"UPS1"):
        fmt = "ups"
    elif data[:5] in (b"PPF10", b"PPF20", b"PPF30"):
        fmt = "ppf"
    elif data.startswith(b"\xd6\xc3\xc4"):
        fmt = "xdelta"
    else:
        fmt = detect_format_from_filename(patch_path)

    info: Dict[str, Any] = {
        "format": fmt.upper(),
        "file_size": len(data),
        "filename": os.path.basename(patch_path),
    }

    if fmt == "bps":
        info.update(BpsPatcher.inspect(data))
    elif fmt == "ups":
        info.update(UpsPatcher.inspect(data))
    elif fmt == "ppf":
        info.update(PPFPatcher.parse(data))
    elif fmt == "ips":
        info.update(IpsPatcher.inspect(data))
    elif fmt == "xdelta":
        info["is_patch_valid"] = data.startswith(b"\xd6\xc3\xc4")

    return info
