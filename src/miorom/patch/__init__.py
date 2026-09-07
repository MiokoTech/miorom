import os
from typing import Optional
from miorom.patch.ips import IpsPatcher
from miorom.patch.bps import BpsPatcher
from miorom.patch.xdelta import XdeltaPatcher
from miorom.patch.slack import SlackSpaceManager, SlackBlock
from miorom.patch.relocator import (
    RelocatablePointer,
    RelocationRecord,
    RelocationSummary,
    AutoRelocationManager,
)
from miorom.patch.pointerizer import (
    SlotToHeapPointerizer,
    PascalStringManager,
    PointerizedSlot,
    SlotConversionReport,
)

from miorom.patch.bank_crosser import (
    BankCrossingRelocator,
    BankPartitionReport,
    BankedStringLocation,
)
from miorom.patch.pointer_remapper import (
    RelativePointerTable,
    MultiPointerRemapper,
)
from miorom.patch.patch_writer import PatchWriter, PatchRecord

__all__ = [
    "IpsPatcher",
    "BpsPatcher",
    "XdeltaPatcher",
    "SlackSpaceManager",
    "SlackBlock",
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
    "create_patch",
    "apply_patch",
]


def detect_format_from_filename(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in [".ips"]:
        return "ips"
    elif ext in [".bps"]:
        return "bps"
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
    Auto-detects format from patch_path extension (.ips, .bps, .xdelta) if fmt is None.
    """
    format_type = fmt.lower() if fmt else detect_format_from_filename(patch_path)

    if format_type == "ips":
        IpsPatcher.create_file(source_path, target_path, patch_path)
    elif format_type == "bps":
        BpsPatcher.create_file(source_path, target_path, patch_path)
    elif format_type == "xdelta":
        XdeltaPatcher.create_patch(source_path, target_path, patch_path)
    else:
        raise ValueError(f"Unsupported patch format: '{format_type}'. Choose 'ips', 'bps', or 'xdelta'.")


def apply_patch(
    source_path: str,
    patch_path: str,
    output_path: str,
    fmt: Optional[str] = None
):
    """
    Apply a patch to source_path and write output to output_path.
    Auto-detects format from patch_path extension (.ips, .bps, .xdelta) or magic bytes if fmt is None.
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
        else:
            format_type = detect_format_from_filename(patch_path)

    if format_type == "ips":
        IpsPatcher.apply_file(source_path, patch_path, output_path)
    elif format_type == "bps":
        BpsPatcher.apply_file(source_path, patch_path, output_path)
    elif format_type == "xdelta":
        XdeltaPatcher.apply_patch(source_path, patch_path, output_path)
    else:
        raise ValueError(f"Unsupported patch format: '{format_type}'.")
