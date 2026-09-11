from miorom.result import MioRomResult
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any
from miorom.script.engine import DisassembledScript, Instruction


@dataclass
class BasicBlock(MioRomResult):
    start_addr: int
    end_addr: int
    instructions: List[Instruction] = field(default_factory=list)
    successors: List[int] = field(default_factory=list)
    predecessors: List[int] = field(default_factory=list)
    label: Optional[str] = None


class ControlFlowGraph:
    """
    Control Flow Graph (CFG) generator for binary game scripts.
    Partitions raw disassembly instructions into structured basic blocks
    and tracks branch/jump control flow edges.
    """

    def __init__(self):
        self.blocks: Dict[int, BasicBlock] = {}
        self.entry_addr: int = 0

    @classmethod
    def from_script(cls, script: DisassembledScript) -> "ControlFlowGraph":
        cfg = cls()
        if not script.instructions:
            return cfg

        cfg.entry_addr = script.instructions[0].offset

        # Basic block leader offsets
        leaders: Set[int] = {script.instructions[0].offset}

        # Any labeled address is a leader
        for target_addr in script.labels.keys():
            leaders.add(target_addr)

        # Instructions following jumps or terminals
        for i, instr in enumerate(script.instructions):
            op_name = instr.name.upper()
            is_terminal = op_name in ("END", "RETURN", "EXIT", "HALT")
            is_jump = "JUMP" in op_name or "CALL" in op_name or any(
                isinstance(v, str) and v.startswith("LABEL_") for v in instr.args.values()
            )

            if is_jump or is_terminal:
                for arg_val in instr.args.values():
                    if isinstance(arg_val, int):
                        leaders.add(arg_val)
                    elif isinstance(arg_val, str) and arg_val.startswith("LABEL_"):
                        try:
                            lbl_addr = int(arg_val.split("_")[1], 16)
                            leaders.add(lbl_addr)
                        except (ValueError, IndexError):
                            pass
                if i + 1 < len(script.instructions):
                    leaders.add(script.instructions[i + 1].offset)

        # Filter leaders by instruction offset
        instruction_offsets = {ins.offset for ins in script.instructions}
        actual_leaders = sorted(leaders.intersection(instruction_offsets))
        leader_set = set(actual_leaders)

        # Partition instructions into basic blocks
        cur_block: Optional[BasicBlock] = None
        for instr in script.instructions:
            if instr.offset in leader_set:
                cur_block = BasicBlock(
                    start_addr=instr.offset,
                    end_addr=instr.offset,
                    instructions=[instr],
                    label=instr.label,
                )
                cfg.blocks[instr.offset] = cur_block
            else:
                if cur_block:
                    cur_block.instructions.append(instr)
                    cur_block.end_addr = instr.offset

        # Control flow graph edges
        sorted_block_addrs = sorted(cfg.blocks.keys())
        for idx, b_addr in enumerate(sorted_block_addrs):
            block = cfg.blocks[b_addr]
            if not block.instructions:
                continue

            last_instr = block.instructions[-1]
            op_name = last_instr.name.upper()
            is_terminal = op_name in ("END", "RETURN", "EXIT", "HALT")

            jump_targets = []
            for arg_val in last_instr.args.values():
                if isinstance(arg_val, int):
                    jump_targets.append(arg_val)
                elif isinstance(arg_val, str) and arg_val.startswith("LABEL_"):
                    try:
                        lbl_addr = int(arg_val.split("_")[1], 16)
                        jump_targets.append(lbl_addr)
                    except (ValueError, IndexError):
                        pass

            # Jump edges
            for target_addr in jump_targets:
                if target_addr in cfg.blocks:
                    if target_addr not in block.successors:
                        block.successors.append(target_addr)
                    if b_addr not in cfg.blocks[target_addr].predecessors:
                        cfg.blocks[target_addr].predecessors.append(b_addr)

            # Fallthrough edge to next block
            is_unconditional = (op_name == "JUMP") or is_terminal
            if not is_unconditional:
                if idx + 1 < len(sorted_block_addrs):
                    next_addr = sorted_block_addrs[idx + 1]
                    if next_addr not in block.successors:
                        block.successors.append(next_addr)
                    if b_addr not in cfg.blocks[next_addr].predecessors:
                        cfg.blocks[next_addr].predecessors.append(b_addr)

        return cfg


class ScriptDecompiler:
    """
    Decompiles a ControlFlowGraph or DisassembledScript into structured,
    human-readable Python-like pseudo-code.
    """

    @classmethod
    def decompile(cls, script: DisassembledScript) -> str:
        cfg = ControlFlowGraph.from_script(script)
        lines: List[str] = ["def game_event():"]

        for b_addr in sorted(cfg.blocks.keys()):
            block = cfg.blocks[b_addr]
            if block.label:
                lines.append(f"    # {block.label}:")

            for instr in block.instructions:
                op = instr.name
                args_str = ", ".join(f"{k}={v!r}" for k, v in instr.args.items())
                lines.append(f"    {op}({args_str})")

            # Annotate branches
            if len(block.successors) > 1:
                succ_labels = [f"0x{s:04X}" for s in block.successors]
                lines.append(f"    # Branch -> {', '.join(succ_labels)}")
            elif len(block.successors) == 1:
                # Check if it's a jump rather than fallthrough
                target = block.successors[0]
                sorted_addrs = sorted(cfg.blocks.keys())
                cur_idx = sorted_addrs.index(b_addr)
                if cur_idx + 1 < len(sorted_addrs) and sorted_addrs[cur_idx + 1] != target:
                    lines.append(f"    # Goto 0x{target:04X}")

        return "\n".join(lines)
