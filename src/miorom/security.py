from __future__ import annotations

import os

from miorom.errors import MioromError


class UnsafeArchivePathError(MioromError):
    """Raised when an archive entry would write outside the output directory."""

    def __init__(self, entry_name: str, resolved_path: str, output_dir: str) -> None:
        self.entry_name = entry_name
        self.resolved_path = resolved_path
        self.output_dir = output_dir
        super().__init__(
            f"Entry path {entry_name!r} resolves outside output directory "
            f"{output_dir!r} (would write to {resolved_path!r})."
        )


def sanitize_extract_path(output_dir: str, entry_name: str) -> str:
    """Resolve an archive entry name inside a strict output directory boundary."""
    output_root = os.path.realpath(output_dir)
    cleaned = entry_name.replace("\\", "/")

    if cleaned.startswith("/") or (len(cleaned) >= 2 and cleaned[1] == ":"):
        raise UnsafeArchivePathError(entry_name, cleaned, output_root)

    candidate = os.path.realpath(os.path.join(output_root, cleaned.lstrip("/")))

    try:
        common = os.path.commonpath([output_root, candidate])
    except ValueError:
        common = None

    if common != output_root:
        raise UnsafeArchivePathError(entry_name, candidate, output_root)

    return candidate
