"""
miorom.diff.patch_auditor
~~~~~~~~~~~~~~~~~~~~~~~~~
Semantic Patch Safety Boundary Validator.
Validates IPS, BPS, and binary hunk patches against critical memory regions
(headers, DMA tables, vectors, foreign overlays) to detect asset collisions before ROM flashing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple
from miorom.patch.hunks import PatchHunk
from miorom.result import MioRomResult


@dataclass
class PatchCollision(MioRomResult):
    region_name: str
    region_start: int
    region_end: int
    hunk_offset: int
    hunk_size: int


@dataclass
class AuditReport(MioRomResult):
    is_safe: bool
    total_hunks: int
    total_bytes_modified: int
    collisions: List[PatchCollision]


class PatchAuditor:
    """
    Audits binary patches against protected regions to prevent asset corruption.
    """

    @classmethod
    def audit(
        cls,
        hunks: List[PatchHunk],
        protected_regions: List[Tuple[str, int, int]], # (name, start, end)
    ) -> AuditReport:
        collisions: List[PatchCollision] = []
        total_bytes = 0

        for h in hunks:
            h_start = h.offset
            h_end = h.offset + len(h.data)
            total_bytes += len(h.data)

            for name, r_start, r_end in protected_regions:
                # Check overlap [h_start, h_end) with [r_start, r_end)
                if max(h_start, r_start) < min(h_end, r_end):
                    collisions.append(PatchCollision(
                        region_name=name,
                        region_start=r_start,
                        region_end=r_end,
                        hunk_offset=h_start,
                        hunk_size=len(h.data),
                    ))

        return AuditReport(
            is_safe=(len(collisions) == 0),
            total_hunks=len(hunks),
            total_bytes_modified=total_bytes,
            collisions=collisions,
        )
