"""
miorom.script.branch
~~~~~~~~~~~~~~~~~~~~
Universal Relative Branch & Jump Table Scanner for Binary Game Scripts.
Discovers relative branches, function calls, and switch tables in arbitrary
bytecode streams without requiring a full disassembler definition.
Also provides safe in-place offset remapping with signed overflow protection.
"""

from dataclasses import dataclass, field
import struct
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union

from miorom.result import MioRomResult

from miorom.errors import PointerOverflowError


@dataclass
class RelativeBranch(MioRomResult):
    """Discovered relative branch or call instruction in bytecode."""
    pc: int                         # Address of the opcode
    opcode: int                     # Opcode byte
    offset: int                     # Signed relative jump offset
    target: int                     # Absolute target address (pc + base_pc_delta + offset)
    offset_pos: int                 # Address where the relative offset is stored
    offset_fmt: str = "<h"          # Struct format for the offset (e.g. '<h', '<b', '<i')

    def __repr__(self) -> str:
        return f"RelativeBranch(pc=0x{self.pc:04X}, opcode=0x{self.opcode:02X}, target=0x{self.target:04X})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pc": self.pc,
            "opcode": self.opcode,
            "offset": self.offset,
            "target": self.target,
            "offset_pos": self.offset_pos,
            "offset_fmt": self.offset_fmt,
        }


@dataclass
class SwitchCase(MioRomResult):
    """A single target entry in a jump/switch table."""
    index: int
    offset_pos: int
    offset: int
    target: int


@dataclass
class SwitchTable(MioRomResult):
    """Discovered switch or jump table in bytecode."""
    pc: int                         # Opcode address
    opcode: int                     # Switch opcode
    case_count: int                 # Number of cases
    cases: List[SwitchCase] = field(default_factory=list)
    base_pc_delta: int = 2          # Target formula: offset_pos + base_pc_delta + offset

    def __repr__(self) -> str:
        return f"SwitchTable(pc=0x{self.pc:04X}, opcode=0x{self.opcode:02X}, cases={self.case_count})"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pc": self.pc,
            "opcode": self.opcode,
            "case_count": self.case_count,
            "cases": [case.to_dict() for case in self.cases],
            "base_pc_delta": self.base_pc_delta,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SwitchTable":
        return cls(
            pc=data["pc"],
            opcode=data["opcode"],
            case_count=data["case_count"],
            cases=[SwitchCase.from_dict(case) for case in data.get("cases", [])],
            base_pc_delta=data.get("base_pc_delta", 2),
        )


class BytecodeBranchScanner:
    """
    Heuristic and deterministic scanner for relative branches and jump tables.
    """

    @classmethod
    def scan_relative_branches(
        cls,
        data: bytes,
        branch_opcodes: Set[int],
        offset_fmt: str = "<h",
        offset_pos_in_instr: int = 1,
        instr_len: int = 3,
        base_pc_delta: int = 3,
        code_range: Optional[Tuple[int, int]] = None,
        excluded_ranges: Optional[Sequence[Tuple[int, int]]] = None,
    ) -> List[RelativeBranch]:
        """
        Scans binary bytecode stream for relative branch/call instructions.

        :param data: Bytecode buffer.
        :param branch_opcodes: Set of opcode bytes to treat as relative branches.
        :param offset_fmt: Struct format for signed relative offset (default '<h').
        :param offset_pos_in_instr: Offset within the instruction where relative offset starts.
        :param instr_len: Total length of instruction.
        :param base_pc_delta: Base added to signed offset (default 3, i.e. target = pc + 3 + offset).
        :param code_range: (start, end) code bounds.
        :param excluded_ranges: Ranges (e.g. string literals) to ignore.
        """
        code_start, code_end = code_range if code_range else (0, len(data))
        off_size = struct.calcsize(offset_fmt)
        excluded = excluded_ranges or []

        def in_excluded(pos: int) -> bool:
            return any(s <= pos < e for s, e in excluded)

        def mid_excluded(pos: int) -> bool:
            return any(s < pos < e for s, e in excluded)

        branches: List[RelativeBranch] = []
        limit = code_end - max(instr_len, offset_pos_in_instr + off_size)

        for pc in range(code_start, limit + 1):
            if in_excluded(pc):
                continue
            opc = data[pc]
            if opc in branch_opcodes:
                off_addr = pc + offset_pos_in_instr
                off = struct.unpack_from(offset_fmt, data, off_addr)[0]
                target = pc + base_pc_delta + off
                # Target must land within code bounds and not in the middle of excluded data
                if code_start <= target < code_end and not mid_excluded(target):
                    branches.append(
                        RelativeBranch(
                            pc=pc,
                            opcode=opc,
                            offset=off,
                            target=target,
                            offset_pos=off_addr,
                            offset_fmt=offset_fmt,
                        )
                    )

        return branches

    @classmethod
    def iter_relative_branches(
        cls,
        data: bytes,
        branch_opcodes: Set[int],
        offset_fmt: str = "<h",
        offset_pos_in_instr: int = 1,
        instr_len: int = 3,
        base_pc_delta: int = 3,
        code_range: Optional[Tuple[int, int]] = None,
        excluded_ranges: Optional[Sequence[Tuple[int, int]]] = None,
    ) -> Iterator[RelativeBranch]:
        """Yield relative branches progressively for early-exit pipelines."""
        yield from cls.scan_relative_branches(
            data=data,
            branch_opcodes=branch_opcodes,
            offset_fmt=offset_fmt,
            offset_pos_in_instr=offset_pos_in_instr,
            instr_len=instr_len,
            base_pc_delta=base_pc_delta,
            code_range=code_range,
            excluded_ranges=excluded_ranges,
        )

    @classmethod
    def scan_switch_tables(
        cls,
        data: bytes,
        switch_opcodes: Set[int],
        count_fmt: str = "<B",
        offset_fmt: str = "<h",
        base_pc_delta: int = 2,
        min_cases: int = 1,
        max_cases: int = 32,
        code_range: Optional[Tuple[int, int]] = None,
        excluded_ranges: Optional[Sequence[Tuple[int, int]]] = None,
    ) -> List[SwitchTable]:
        """
        Scans binary bytecode stream for switch / jump tables.
        Layout: [switch_opcode][count][relative_offset_0][relative_offset_1]...
        """
        code_start, code_end = code_range if code_range else (0, len(data))
        cnt_size = struct.calcsize(count_fmt)
        off_size = struct.calcsize(offset_fmt)
        excluded = excluded_ranges or []

        def in_excluded(pos: int) -> bool:
            return any(s <= pos < e for s, e in excluded)

        def mid_excluded(pos: int) -> bool:
            return any(s < pos < e for s, e in excluded)

        tables: List[SwitchTable] = []
        limit = code_end - (1 + cnt_size + off_size * min_cases)

        for pc in range(code_start, limit + 1):
            if in_excluded(pc):
                continue
            opc = data[pc]
            if opc in switch_opcodes:
                cnt = struct.unpack_from(count_fmt, data, pc + 1)[0]
                if not (min_cases <= cnt <= max_cases):
                    continue

                table_end = pc + 1 + cnt_size + (cnt * off_size)
                if table_end > code_end:
                    continue

                cases: List[SwitchCase] = []
                all_valid = True
                for k in range(cnt):
                    off_pos = pc + 1 + cnt_size + (k * off_size)
                    off = struct.unpack_from(offset_fmt, data, off_pos)[0]
                    target = off_pos + base_pc_delta + off
                    if not (code_start <= target < code_end and not mid_excluded(target)):
                        all_valid = False
                        break
                    cases.append(SwitchCase(index=k, offset_pos=off_pos, offset=off, target=target))

                if all_valid and len(cases) == cnt:
                    tables.append(
                        SwitchTable(
                            pc=pc,
                            opcode=opc,
                            case_count=cnt,
                            cases=cases,
                            base_pc_delta=base_pc_delta,
                        )
                    )

        return tables

    @classmethod
    def iter_switch_tables(
        cls,
        data: bytes,
        switch_opcodes: Set[int],
        code_range: Optional[Tuple[int, int]] = None,
        base_pc_delta: int = 2,
        max_cases: int = 256,
        excluded_ranges: Optional[Sequence[Tuple[int, int]]] = None,
    ) -> Iterator[SwitchTable]:
        """Yield switch tables progressively for early-exit pipelines."""
        yield from cls.scan_switch_tables(
            data=data,
            switch_opcodes=switch_opcodes,
            code_range=code_range,
            base_pc_delta=base_pc_delta,
            max_cases=max_cases,
            excluded_ranges=excluded_ranges,
        )

    @classmethod
    def relocate_branches(
        cls,
        buffer: bytearray,
        branches: Sequence[RelativeBranch],
        mapper: Callable[[int], int],
        base_pc_delta: int = 3,
        check_overflow: bool = True,
    ) -> int:
        """
        Remaps all relative branches in-place using the provided offset mapper.
        Returns the number of branches relocated.
        """
        count = 0
        for b in branches:
            new_off_pos = mapper(b.offset_pos)
            new_pc = mapper(b.pc)
            new_target = mapper(b.target)
            new_off = new_target - (new_pc + base_pc_delta)

            if check_overflow:
                if b.offset_fmt.endswith("b"):
                    if not (-128 <= new_off <= 127):
                        raise PointerOverflowError(
                            f"Relative branch offset {new_off} overflows int8 at 0x{new_pc:X}",
                            offset=new_off_pos,
                            expected=(-128, 127),
                            actual=new_off,
                        )
                elif b.offset_fmt.endswith("h"):
                    if not (-32768 <= new_off <= 32767):
                        raise PointerOverflowError(
                            f"Relative branch offset {new_off} overflows int16 at 0x{new_pc:X}",
                            offset=new_off_pos,
                            expected=(-32768, 32767),
                            actual=new_off,
                        )
                else:
                    if not (-(1 << (struct.calcsize(b.offset_fmt) * 8 - 1)) <= new_off
                            < (1 << (struct.calcsize(b.offset_fmt) * 8 - 1))):
                        raise PointerOverflowError(
                            f"Relative branch offset {new_off} overflows {b.offset_fmt} at 0x{new_pc:X}",
                            offset=mapper(b.offset_pos),
                            actual=new_off,
                        )

            struct.pack_into(b.offset_fmt, buffer, new_off_pos, new_off)
            count += 1

        return count

    @classmethod
    def relocate_switch_tables(
        cls,
        buffer: bytearray,
        tables: Sequence[SwitchTable],
        mapper: Callable[[int], int],
        base_pc_delta: int = 2,
        offset_fmt: str = "<h",
        check_overflow: bool = True,
    ) -> int:
        """
        Remaps all switch table target offsets in-place.
        Returns the number of switch entries relocated.
        """
        count = 0
        for st in tables:
            for case in st.cases:
                new_off_pos = mapper(case.offset_pos)
                new_target = mapper(case.target)
                new_off = new_target - (new_off_pos + base_pc_delta)

                if check_overflow:
                    if offset_fmt.endswith("h"):
                        if not (-32768 <= new_off <= 32767):
                            raise PointerOverflowError(
                                f"Switch table offset {new_off} overflows int16 at 0x{new_off_pos:X}",
                                offset=new_off_pos,
                                expected=(-32768, 32767),
                                actual=new_off,
                            )

                struct.pack_into(offset_fmt, buffer, new_off_pos, new_off)
                count += 1

        return count
