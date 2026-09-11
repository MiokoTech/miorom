import struct
import json
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from miorom.asm.disasm import DisasmInstruction, UniversalDisassembler
from miorom.script.ir import IRBlock, IRFunction, IROp
from miorom.result import MioRomResult


class XRefType(Enum):
    CODE_CALL = "CALL"
    CODE_JUMP = "JUMP"
    DATA_READ = "READ"
    DATA_WRITE = "WRITE"
    POINTER_REF = "POINTER"


@dataclass
class XRefEntry(MioRomResult):
    source: int
    target: int
    xref_type: XRefType
    context: Optional[str] = None

    def __repr__(self) -> str:
        ctx = f" ({self.context})" if self.context else ""
        return f"<XRef 0x{self.source:08X} -[{self.xref_type.value}]-> 0x{self.target:08X}{ctx}>"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "xref_type": self.xref_type.value,
            "context": self.context,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "XRefEntry":
        return cls(
            source=data["source"],
            target=data["target"],
            xref_type=XRefType(data["xref_type"]),
            context=data.get("context"),
        )


class XRefGraph:
    """
    Bi-directional cross-reference database connecting functions, pointers, and memory blocks.
    """

    def __init__(self):
        self.forward_refs: Dict[int, List[XRefEntry]] = defaultdict(list)
        self.backward_refs: Dict[int, List[XRefEntry]] = defaultdict(list)

    def save(self, path: str) -> None:
        """Serialize XRefGraph to JSON for persistent analysis sessions."""
        entries = []
        for target_addr, ref_list in self.backward_refs.items():
            for e in ref_list:
                entries.append({
                    "source": e.source,
                    "target": e.target,
                    "type": e.xref_type.value,
                    "context": e.context,
                })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"entries": entries}, f, indent=2)

    @classmethod
    def load(cls, path: str) -> "XRefGraph":
        """Load XRefGraph from a JSON file created by save()."""
        graph = cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for e in data.get("entries", []):
            graph.add_xref(
                source=e["source"],
                target=e["target"],
                xref_type=XRefType(e["type"]),
                context=e.get("context"),
            )
        return graph

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

    def to_mermaid_ir(self, ir_functions: List[IRFunction], center_address: int, radius: int = 2) -> str:
        """
        Render an XRef sub-graph while grouping code references by IR basic blocks.
        """
        lines = ["graph TD"]
        block_labels: Dict[Tuple[int, str], str] = {}

        def mermaid_id(function: IRFunction, block: IRBlock) -> str:
            label = re.sub(r"[^0-9A-Za-z_]", "_", block.label)
            return f"f_{function.entry_address:08X}_{label}"

        for function in ir_functions:
            for block in function.blocks.values():
                block_labels[(function.entry_address, block.label)] = mermaid_id(function, block)

        center_owner = None
        for function in ir_functions:
            for block in function.blocks.values():
                if block.address <= center_address:
                    center_owner = function
                    break
            if center_owner is not None:
                break
        visible_functions = {center_owner.entry_address} if center_owner else set()

        for function in ir_functions:
            if abs(function.entry_address - center_address) > radius:
                continue
            lines.append(f"    subgraph sub_{function.entry_address:08X}[\"{function.name} @ 0x{function.entry_address:08X}\"]")
            for block in function.blocks.values():
                block_id = block_labels[(function.entry_address, block.label)]
                label = f"0x{block.address:08X}\\n{len(block.instructions)} instr"
                lines.append(f"        {block_id}[\"{label}\"]")
            lines.append("    end")

        def block_for_address(address: int) -> Optional[Tuple[IRFunction, IRBlock]]:
            for function in ir_functions:
                sorted_blocks = sorted(function.blocks.values(), key=lambda item: item.address)
                for index, block in enumerate(sorted_blocks):
                    end_address = sorted_blocks[index + 1].address if index + 1 < len(sorted_blocks) else None
                    if block.address <= address and (end_address is None or address < end_address):
                        return function, block
            return None

        visited_nodes: Set[int] = set()
        rendered_edges: Set[Tuple[int, int, XRefType]] = set()
        queue = deque([(center_address, 0)])

        while queue:
            address, distance = queue.popleft()
            if address in visited_nodes or distance > radius:
                continue
            visited_nodes.add(address)

            for entry in self.forward_refs.get(address, []) + self.backward_refs.get(address, []):
                source_owner = block_for_address(entry.source)
                target_owner = block_for_address(entry.target)
                if source_owner and target_owner:
                    source_function, source_block = source_owner
                    target_function, target_block = target_owner
                    visible_functions.add(source_function.entry_address)
                    visible_functions.add(target_function.entry_address)
                    source_id = block_labels[(source_function.entry_address, source_block.label)]
                    target_id = block_labels[(target_function.entry_address, target_block.label)]
                    if (source_id, target_id, entry.xref_type) not in rendered_edges:
                        lines.append(f"    {source_id} -->|{entry.xref_type.value}| {target_id}")
                        rendered_edges.add((source_id, target_id, entry.xref_type))

            for entry in self.forward_refs.get(address, []):
                if distance + 1 <= radius:
                    queue.append((entry.target, distance + 1))
            for entry in self.backward_refs.get(address, []):
                if distance + 1 <= radius:
                    queue.append((entry.source, distance + 1))

        for function in ir_functions:
            if function.entry_address not in visible_functions:
                continue
            for block in function.blocks.values():
                source_id = block_labels[(function.entry_address, block.label)]
                for successor in block.successors:
                    if successor in function.blocks:
                        target_id = block_labels[(function.entry_address, successor)]
                        lines.append(f"    {source_id} -. CFG .-> {target_id}")

        return "\n".join(lines)


class XRefAnalyzer:
    """
    Constructs an XRefGraph by analyzing instructions and pointer tables.
    """

    @classmethod
    def analyze_ir(cls, ir_funcs: List[IRFunction]) -> XRefGraph:
        """
        Build XRefGraph from BinaryLifter IRFunction basic blocks.
        More accurate than linear disasm — CFG edges distinguish real targets
        from data-in-the-middle-of-code.
        """
        graph = XRefGraph()
        for func in ir_funcs:
            for block in func.blocks.values():
                for ins in block.instructions:
                    if ins.op == IROp.CALL and ins.args:
                        try:
                            target = int(ins.args[0])
                            graph.add_xref(
                                source=ins.pc or func.entry_address,
                                target=target,
                                xref_type=XRefType.CODE_CALL,
                                context=f"{func.name}:{ins.op.value}",
                            )
                        except (ValueError, TypeError):
                            pass
                    elif ins.op == IROp.BRANCH and ins.args:
                        try:
                            target = int(ins.args[0])
                            graph.add_xref(
                                source=ins.pc or func.entry_address,
                                target=target,
                                xref_type=XRefType.CODE_JUMP,
                                context=f"{func.name}:BRANCH",
                            )
                        except (ValueError, TypeError):
                            pass
                    elif ins.op in (IROp.LOAD, IROp.STORE) and ins.args:
                        for arg in ins.args:
                            try:
                                addr = int(arg)
                                if addr > 0x100:
                                    graph.add_xref(
                                        source=ins.pc or func.entry_address,
                                        target=addr,
                                        xref_type=XRefType.DATA_READ if ins.op == IROp.LOAD else XRefType.DATA_WRITE,
                                        context=f"{func.name}:{ins.op.value}",
                                    )
                            except (ValueError, TypeError):
                                pass
        return graph

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

        # Code cross-references (branches and calls)
        for ins in instructions:
            if ins.target_address:
                xtype = XRefType.CODE_CALL if ins.is_call else XRefType.CODE_JUMP
                graph.add_xref(
                    source=ins.address,
                    target=ins.target_address,
                    xref_type=xtype,
                    context=ins.mnemonic,
                )

        # Data pointer cross-references
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
