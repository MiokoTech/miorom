"""Patch primitive for programmatic inspection, filtering, and composition."""

from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List

from miorom.result import MioRomResult


@dataclass
class PatchHunk(MioRomResult):
    """One concrete write into a target image."""

    offset: int
    data: bytes

    def to_dict(self) -> Dict[str, object]:
        return {"offset": self.offset, "data": self.data.hex()}

    @classmethod
    def from_dict(cls, data: Dict[str, object]) -> "PatchHunk":
        return cls(offset=data["offset"], data=bytes.fromhex(data["data"]))


def merge_patches(*hunk_groups: Iterable[PatchHunk]) -> List[PatchHunk]:
    """Merge hunks by offset; later writes replace overlapping earlier writes."""
    writes: Dict[int, int] = {}
    for hunks in hunk_groups:
        for hunk in hunks:
            for index, byte in enumerate(hunk.data):
                writes[hunk.offset + index] = byte

    if not writes:
        return []
    merged: List[PatchHunk] = []
    offsets = sorted(writes)
    start = offsets[0]
    previous = start
    for offset in offsets[1:]:
        if offset != previous + 1:
            merged.append(PatchHunk(start, bytes(writes[pos] for pos in range(start, previous + 1))))
            start = offset
        previous = offset
    merged.append(PatchHunk(start, bytes(writes[pos] for pos in range(start, previous + 1))))
    return merged


def filter_hunks(hunks: Iterable[PatchHunk], predicate: Callable[[PatchHunk], bool]) -> List[PatchHunk]:
    """Keep only hunks matching a caller-defined predicate."""
    return [hunk for hunk in hunks if predicate(hunk)]

