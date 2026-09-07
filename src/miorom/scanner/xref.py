import struct
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

from miorom.asm.disasm import DisasmInstruction, UniversalDisassembler


class XRefType(Enum):
    CODE_CALL = "CALL"
    CODE_JUMP = "JUMP"
    DATA_READ = "READ"
    DATA_WRITE = "WRITE"
    POINTER_REF = "POINTER"


@dataclass
class XRefEntry:
    source: int
    target: int
    xref_type: XRefType
    context: Optional[str] = None

    def __repr__(self) -> str:
        ctx = f" ({self.context})" if self.context else ""
        return f"<XRef 0x{self.source:08X} -[{self.xref_type.value}]-> 0x{self.target:08X}{ctx}>"


class XRefGraph:
    """
    Bi-directional cross-reference database connecting functions, pointers, and memory blocks.
    """

    def __init__(self):
        self.forward_refs: Dict[int, List[XRefEntry]] = defaultdict(list)
        self.backward_refs: Dict[int, List[XRefEntry]] = defaultdict(list)

    def add_xref(self, source: int, target: int, xref_type: XRefType, context: Optional[str] = None):
        entry = XRefEntry(source=source, target=target, xref_type=xref_type, context=context)
        self.forward_refs[source].append(entry)
        self.backward_refs[target].append(entry)

    def get_callers_of(self, target_address: int) -> List[int]:
        """Return list of addresses that call this function."""
        return [
            entry.source
            for entry in self.backward_refs.get(target_address, [])
            if entry.xref_type in (XRefType.CODE_CALL, XRefType.CODE_JUMP)
        ]

    def get_callees_from(self, source_address: int) -> List[int]:
        """Return list of addresses called by this function/instruction."""
        return [
            entry.target
            for entry in self.forward_refs.get(source_address, [])
            if entry.xref_type in (XRefType.CODE_CALL, XRefType.CODE_JUMP)
        ]

    def get_data_references(self, target_address: int) -> List[int]:
        """Return list of instruction or pointer addresses referencing target_address."""
        return [entry.source for entry in self.backward_refs.get(target_address, [])]

    def find_pointer_chains(self, target_address: int, max_depth: int = 3) -> List[List[int]]:
        """
        Search backwards for multi-level pointer chains pointing to target_address:
        [Root_Ptr] -> [Secondary_Ptr] -> [Target].
        """
        chains: List[List[int]] = []
        queue = deque([([target_address], 0)])

        while queue:
            current_path, depth = queue.popleft()
            if depth >= max_depth:
                continue

            tip = current_path[-1]
            refs = self.get_data_references(tip)
            if not refs:
                if len(current_path) > 1:
                    chains.append(list(reversed(current_path)))
                continue

            for r in refs:
                if r not in current_path:
                    new_path = current_path + [r]
                    queue.append((new_path, depth + 1))
                    if len(new_path) > 1:
                        chains.append(list(reversed(new_path)))

        return chains

    def to_mermaid(self, center_address: int, radius: int = 2) -> str:
        """
        Export a localized cross-reference sub-graph to Mermaid diagram format.
        """
        lines = ["graph TD"]
        visited_nodes: Set[int] = set()
        queue = deque([(center_address, 0)])

        while queue:
            addr, dist = queue.popleft()
            if addr in visited_nodes or dist > radius:
                continue
            visited_nodes.add(addr)

            # Draw outgoing
            for e in self.forward_refs.get(addr, []):
                lines.append(f"    loc_{e.source:08X}[\"0x{e.source:08X}\"] -->|{e.xref_type.value}| loc_{e.target:08X}[\"0x{e.target:08X}\"]")
                if dist + 1 <= radius:
                    queue.append((e.target, dist + 1))

            # Draw incoming
            for e in self.backward_refs.get(addr, []):
                lines.append(f"    loc_{e.source:08X}[\"0x{e.source:08X}\"] -->|{e.xref_type.value}| loc_{e.target:08X}[\"0x{e.target:08X}\"]")
                if dist + 1 <= radius:
                    queue.append((e.source, dist + 1))

        return "\n".join(lines)


class XRefAnalyzer:
    """
    Constructs an XRefGraph by analyzing instructions and pointer tables.
    """

    @classmethod
    def analyze(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "ppc",
        endian: Optional[str] = None,
    ) -> XRefGraph:
        graph = XRefGraph()
        instructions = UniversalDisassembler.disassemble(
            data=data,
            base_address=base_address,
            arch=arch,
            endian=endian,
        )

        total_len = len(data)
        valid_range = (base_address, base_address + total_len)

        # 1. Code XRefs (branches and calls)
        for ins in instructions:
            if ins.target_address:
                xtype = XRefType.CODE_CALL if ins.is_call else XRefType.CODE_JUMP
                graph.add_xref(
                    source=ins.address,
                    target=ins.target_address,
                    xref_type=xtype,
                    context=ins.mnemonic,
                )

        # 2. Data Pointer Tables XRefs
        end_align = total_len - (total_len % 4)
        fmt = f"{endian or '>'}I" if arch == "ppc" else f"{endian or '<'}I"

        for off in range(0, end_align, 4):
            val = struct.unpack_from(fmt, data, off)[0]
            if valid_range[0] <= val < valid_range[1]:
                src_addr = base_address + off
                graph.add_xref(
                    source=src_addr,
                    target=val,
                    xref_type=XRefType.POINTER_REF,
                    context="Pointer Table",
                )

        return graph
