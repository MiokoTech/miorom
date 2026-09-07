"""
miorom.save.diff_hunter
~~~~~~~~~~~~~~~~~~~~~~~
Save-State Diff-Fuzzing & Pointer Trail Hunter.
Compares sequential emulator save-states / memory dumps to isolate dynamic game state
variables, and traces multi-level pointer chains through RAM back to static base anchors.
"""

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union


@dataclass
class RAMSnapshot:
    name: str
    data: bytes
    ram_base: int = 0x80000000


@dataclass
class DiffMatch:
    offset: int
    ram_addr: int
    values: List[int]
    stride: int

    def summary(self) -> str:
        vals_str = " -> ".join(f"0x{v:X} ({v})" for v in self.values)
        return f"[0x{self.ram_addr:08X}] (offset 0x{self.offset:08X}): {vals_str}"


@dataclass
class PointerTrail:
    base_ram: int
    offsets: List[int]
    resolved_target: int

    def expression(self) -> str:
        expr = f"[0x{self.base_ram:08X}]"
        for off in self.offsets:
            expr = f"[{expr} + 0x{off:X}]"
        return f"{expr} -> 0x{self.resolved_target:08X}"


@dataclass
class DiffHunterReport:
    snapshots_analyzed: int
    matches: List[DiffMatch] = field(default_factory=list)
    pointer_trails: List[PointerTrail] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "==================================================",
            "    Save-State Diff & Pointer Trail Report        ",
            "==================================================",
            f"  Snapshots Analyzed : {self.snapshots_analyzed}",
            f"  Diff Matches Found : {len(self.matches)}",
            f"  Pointer Trails     : {len(self.pointer_trails)}",
        ]
        if self.matches:
            lines.append("  Top Matches:")
            for m in self.matches[:10]:
                lines.append(f"    - {m.summary()}")
        if self.pointer_trails:
            lines.append("  Discovered Pointer Trails:")
            for pt in self.pointer_trails[:5]:
                lines.append(f"    - {pt.expression()}")
        lines.append("==================================================")
        return "\n".join(lines)


class SaveStateDiffHunter:
    """
    Differential Memory Snapshot Analyzer & Pointer Chain Tracer.
    """

    @classmethod
    def diff_snapshots(
        cls,
        snapshots: List[RAMSnapshot],
        condition: str = "changed",
        stride: int = 4,
        endian: str = ">",
    ) -> List[DiffMatch]:
        """
        Compare multiple snapshots in chronological order under a filter condition.
        Supported conditions:
          - 'changed': value changes between any consecutive snapshot
          - 'increased': value strictly increases (v0 < v1 < v2 ...)
          - 'decreased': value strictly decreases (v0 > v1 > v2 ...)
          - 'unchanged': value remains constant across all snapshots
        """
        if len(snapshots) < 2:
            return []

        min_len = min(len(s.data) for s in snapshots)
        ram_base = snapshots[0].ram_base
        fmt = f"{endian}{'I' if stride == 4 else ('H' if stride == 2 else 'B')}"

        matches: List[DiffMatch] = []

        for offset in range(0, min_len - stride + 1, stride):
            vals = [struct.unpack_from(fmt, s.data, offset)[0] for s in snapshots]

            is_match = False
            if condition == "changed":
                is_match = any(vals[i] != vals[i + 1] for i in range(len(vals) - 1))
            elif condition == "increased":
                is_match = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
            elif condition == "decreased":
                is_match = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
            elif condition == "unchanged":
                is_match = all(vals[i] == vals[0] for i in range(1, len(vals)))

            if is_match:
                matches.append(
                    DiffMatch(
                        offset=offset,
                        ram_addr=ram_base + offset,
                        values=vals,
                        stride=stride,
                    )
                )

        return matches

    @classmethod
    def find_pointer_trails(
        cls,
        snapshot: RAMSnapshot,
        target_ram: int,
        max_depth: int = 2,
        max_offset: int = 0x200,
        endian: str = ">",
    ) -> List[PointerTrail]:
        """
        Walk backward from `target_ram` to find pointer paths in RAM.
        Finds addresses `P` such that `*P + offset == target_ram`, up to `max_depth`.
        """
        data = snapshot.data
        ram_base = snapshot.ram_base
        n = len(data)
        trails: List[PointerTrail] = []

        # Find level-1 pointers: [ptr_val] + offset = target_ram
        # where ptr_val <= target_ram and target_ram - ptr_val <= max_offset
        def find_pointers_to(target: int) -> List[Tuple[int, int]]:
            # returns list of (pointer_ram_addr, offset_delta)
            results = []
            for off in range(0, n - 4, 4):
                val = struct.unpack_from(f"{endian}I", data, off)[0]
                # Check if val points near target
                delta = target - val
                if 0 <= delta <= max_offset:
                    results.append((ram_base + off, delta))
            return results

        lvl1 = find_pointers_to(target_ram)

        for p1_ram, off1 in lvl1:
            if max_depth == 1:
                trails.append(PointerTrail(p1_ram, [off1], target_ram))
                continue

            # Look for level-2 pointers pointing to p1_ram
            lvl2 = find_pointers_to(p1_ram)
            if not lvl2:
                trails.append(PointerTrail(p1_ram, [off1], target_ram))
            else:
                for p2_ram, off2 in lvl2:
                    trails.append(PointerTrail(p2_ram, [off2, off1], target_ram))

        return trails[:20]  # Cap results
