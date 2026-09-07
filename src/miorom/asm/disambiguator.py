import struct
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Union

from miorom.asm.disasm import UniversalDisassembler


class ByteClassification(Enum):
    CODE = "CODE"
    JUMP_TABLE = "JUMP_TABLE"
    RODATA = "RODATA"
    STRING = "STRING"
    PADDING = "PADDING"
    UNKNOWN = "UNKNOWN"


@dataclass
class ClassifiedRange:
    start_address: int
    end_address: int
    classification: ByteClassification
    size: int
    details: str = ""

    def __repr__(self) -> str:
        return (
            f"<ClassifiedRange 0x{self.start_address:08X}..0x{self.end_address:08X} "
            f"({self.size} bytes): {self.classification.value} - {self.details}>"
        )


@dataclass
class DisambiguationReport:
    total_bytes: int
    ranges: List[ClassifiedRange] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            "==================================================",
            "       Code vs. Data Disambiguation Report        ",
            "==================================================",
            f"  Total Analyzed     : {self.total_bytes} bytes",
        ]
        for k, v in self.stats.items():
            pct = (v / self.total_bytes * 100) if self.total_bytes > 0 else 0
            lines.append(f"  - {k:<18} : {v:>8} bytes ({pct:5.1f}%)")
        lines.append("==================================================")
        return "\n".join(lines)


class CodeDataDisambiguator:
    """
    Hybrid Recursive Descent and Statistical Linear Sweep Engine.
    Disambiguates executable machine code from jump tables, string literals,
    padding bytes, and raw rodata in binary ROMs.
    """

    def __init__(self, length_or_data: Union[int, bytes, bytearray] = 0):
        length = length_or_data if isinstance(length_or_data, int) else len(length_or_data)
        self.classifications: List[ByteClassification] = [ByteClassification.UNKNOWN] * length

    @classmethod
    def analyze(
        cls,
        data: bytes,
        base_address: int,
        entry_points: Optional[List[int]] = None,
        arch: str = "ppc",
        endian: Optional[str] = None,
        min_string_len: int = 4,
    ) -> DisambiguationReport:
        total_len = len(data)
        if total_len == 0:
            return DisambiguationReport(0)

        step = 2 if arch.lower() == "thumb" else 4
        byte_labels = [ByteClassification.UNKNOWN] * total_len

        # 1. Recursive Descent from Entry Points
        entries = entry_points if entry_points else [base_address]
        visited_pcs: Set[int] = set()
        queue = deque(entries)

        def addr_to_off(addr: int) -> Optional[int]:
            off = addr - base_address
            if 0 <= off < total_len:
                return off
            return None

        while queue:
            pc = queue.popleft()
            if pc in visited_pcs:
                continue

            off = addr_to_off(pc)
            if off is None or off + step > total_len:
                continue

            visited_pcs.add(pc)

            try:
                ins = UniversalDisassembler.disassemble_instruction(
                    address=pc,
                    raw_bytes=data[off : off + step],
                    arch=arch,
                    endian=endian,
                )
            except Exception:
                continue

            # Mark instruction bytes as CODE
            for i in range(step):
                byte_labels[off + i] = ByteClassification.CODE

            # Handle control flow
            if ins.is_return:
                # Function ends here
                pass
            elif ins.is_call:
                # Call: branch target is code, and fallthrough continues
                if ins.target_address:
                    queue.append(ins.target_address)
                queue.append(pc + step)
            elif ins.is_branch:
                if ins.is_conditional:
                    # Branch taken and branch not taken (fallthrough)
                    if ins.target_address:
                        queue.append(ins.target_address)
                    queue.append(pc + step)
                else:
                    # Unconditional jump: only branch taken
                    if ins.target_address:
                        queue.append(ins.target_address)
            else:
                # Normal instruction: continue fallthrough
                queue.append(pc + step)

        # 2. Detect Padding Blocks
        # Look for contiguous sequences of 0x00 or NOPs after function boundaries
        pos = 0
        while pos < total_len:
            if byte_labels[pos] == ByteClassification.UNKNOWN:
                # Check for 0x00, 0xFF or NOP
                b = data[pos]
                if b in (0x00, 0xFF):
                    run_start = pos
                    while pos < total_len and data[pos] == b and byte_labels[pos] == ByteClassification.UNKNOWN:
                        pos += 1
                    run_len = pos - run_start
                    if run_len >= 4:
                        for idx in range(run_start, pos):
                            byte_labels[idx] = ByteClassification.PADDING
                    continue
            pos += 1

        # 3. Detect Jump Tables
        # Look for tables of 32-bit addresses in remaining unknown areas pointing into valid CODE
        code_ranges_set = {
            base_address + idx for idx, lbl in enumerate(byte_labels) if lbl == ByteClassification.CODE
        }

        pos = 0
        end_align = total_len - (total_len % 4)
        while pos + 4 <= end_align:
            if byte_labels[pos] == ByteClassification.UNKNOWN:
                # Check 4-byte address
                val = struct.unpack(f"{endian or '>'}I" if arch == "ppc" else f"{endian or '<'}I", data[pos : pos + 4])[0]
                if val in code_ranges_set:
                    run_start = pos
                    count = 0
                    while pos + 4 <= end_align:
                        cand = struct.unpack(
                            f"{endian or '>'}I" if arch == "ppc" else f"{endian or '<'}I",
                            data[pos : pos + 4]
                        )[0]
                        if cand in code_ranges_set:
                            count += 1
                            pos += 4
                        else:
                            break
                    if count >= 2:  # At least 2 consecutive code addresses constitute a jump table
                        for idx in range(run_start, pos):
                            byte_labels[idx] = ByteClassification.JUMP_TABLE
                        continue
            pos += 4

        # 4. Detect Printable Strings
        pos = 0
        while pos < total_len:
            if byte_labels[pos] == ByteClassification.UNKNOWN:
                # Check if byte is ASCII printable
                if 0x20 <= data[pos] <= 0x7E:
                    run_start = pos
                    while pos < total_len and (0x20 <= data[pos] <= 0x7E or data[pos] in (0x0A, 0x0D, 0x09)):
                        pos += 1
                    # String must be null-terminated or meet length threshold
                    if pos < total_len and data[pos] == 0:
                        pos += 1  # Include null terminator
                    run_len = pos - run_start
                    if run_len >= min_string_len:
                        for idx in range(run_start, pos):
                            byte_labels[idx] = ByteClassification.STRING
                        continue
            pos += 1

        # 5. Mark remaining as RODATA
        for idx in range(total_len):
            if byte_labels[idx] == ByteClassification.UNKNOWN:
                byte_labels[idx] = ByteClassification.RODATA

        # 6. Consolidate contiguous byte labels into ClassifiedRanges
        ranges: List[ClassifiedRange] = []
        cur_start = 0
        cur_type = byte_labels[0]

        for idx in range(1, total_len):
            if byte_labels[idx] != cur_type:
                sz = idx - cur_start
                ranges.append(
                    ClassifiedRange(
                        start_address=base_address + cur_start,
                        end_address=base_address + idx,
                        classification=cur_type,
                        size=sz,
                        details=f"{cur_type.value} block",
                    )
                )
                cur_start = idx
                cur_type = byte_labels[idx]

        # Append final range
        sz = total_len - cur_start
        ranges.append(
            ClassifiedRange(
                start_address=base_address + cur_start,
                end_address=base_address + total_len,
                classification=cur_type,
                size=sz,
                details=f"{cur_type.value} block",
            )
        )

        # 7. Compute statistics
        stats: Dict[str, int] = {}
        for r in ranges:
            name = r.classification.value
            stats[name] = stats.get(name, 0) + r.size

        return DisambiguationReport(total_bytes=total_len, ranges=ranges, stats=stats)
