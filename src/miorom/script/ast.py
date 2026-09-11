from miorom.result import MioRomResult
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from miorom.script.control_flow import BasicBlock, ControlFlowGraph
from miorom.script.engine import DisassembledScript, Instruction


class ASTNode:
    """Base node for high-level script Abstract Syntax Tree."""
    pass


class Statement(ASTNode):
    """Abstract statement node."""
    pass


@dataclass
class InstructionStmt(Statement, MioRomResult):
    instruction: Instruction

    def format_call(self) -> str:
        args_str = ", ".join(f"{k}={v!r}" for k, v in self.instruction.args.items())
        return f"{self.instruction.name}({args_str})"


@dataclass
class LabelStmt(Statement, MioRomResult):
    name: str


@dataclass
class GotoStmt(Statement, MioRomResult):
    target: str


@dataclass
class ReturnStmt(Statement, MioRomResult):
    instruction: Instruction


@dataclass
class BlockStmt(Statement, MioRomResult):
    statements: List[Statement] = field(default_factory=list)


@dataclass
class IfStmt(Statement, MioRomResult):
    condition: Instruction
    then_block: BlockStmt
    else_block: Optional[BlockStmt] = None


@dataclass
class WhileStmt(Statement, MioRomResult):
    condition: Optional[Instruction]
    body: BlockStmt


class ScriptAST:
    """
    High-level Abstract Syntax Tree representation of a game script function.
    Provides pretty-printing to structured Python-like and C-like pseudocode.
    """

    def __init__(self, function_name: str = "game_event", body: Optional[BlockStmt] = None):
        self.function_name = function_name
        self.body = body or BlockStmt()

    def to_python(self, indent_str: str = "    ") -> str:
        """Render AST as Python-style pseudo-code."""
        lines = [f"def {self.function_name}():"]

        def render_statements(stmts: List[Statement], level: int):
            prefix = indent_str * level
            if not stmts:
                lines.append(f"{prefix}pass")
                return

            for s in stmts:
                if isinstance(s, LabelStmt):
                    lines.append(f"{prefix}# {s.name}:")
                elif isinstance(s, InstructionStmt):
                    lines.append(f"{prefix}{s.format_call()}")
                elif isinstance(s, ReturnStmt):
                    lines.append(f"{prefix}return  # {s.instruction.name}")
                elif isinstance(s, GotoStmt):
                    lines.append(f"{prefix}goto {s.target}")
                elif isinstance(s, IfStmt):
                    cond_args = ", ".join(f"{k}={v!r}" for k, v in s.condition.args.items() if k != "target")
                    lines.append(f"{prefix}if {s.condition.name}({cond_args}):")
                    render_statements(s.then_block.statements, level + 1)
                    if s.else_block and s.else_block.statements:
                        lines.append(f"{prefix}else:")
                        render_statements(s.else_block.statements, level + 1)
                elif isinstance(s, WhileStmt):
                    if s.condition:
                        cond_args = ", ".join(f"{k}={v!r}" for k, v in s.condition.args.items() if k != "target")
                        cond_str = f"{s.condition.name}({cond_args})"
                    else:
                        cond_str = "True"
                    lines.append(f"{prefix}while {cond_str}:")
                    render_statements(s.body.statements, level + 1)
                elif isinstance(s, BlockStmt):
                    render_statements(s.statements, level)

        render_statements(self.body.statements, 1)
        return "\n".join(lines)

    def to_c(self, indent_str: str = "    ") -> str:
        """Render AST as C-style pseudo-code."""
        lines = [f"void {self.function_name}(void) {{"]

        def render_statements(stmts: List[Statement], level: int):
            prefix = indent_str * level
            for s in stmts:
                if isinstance(s, LabelStmt):
                    lines.append(f"{prefix}{s.name}:")
                elif isinstance(s, InstructionStmt):
                    lines.append(f"{prefix}{s.format_call()};")
                elif isinstance(s, ReturnStmt):
                    lines.append(f"{prefix}return;")
                elif isinstance(s, GotoStmt):
                    lines.append(f"{prefix}goto {s.target};")
                elif isinstance(s, IfStmt):
                    cond_args = ", ".join(f"{k}={v!r}" for k, v in s.condition.args.items() if k != "target")
                    lines.append(f"{prefix}if ({s.condition.name}({cond_args})) {{")
                    render_statements(s.then_block.statements, level + 1)
                    if s.else_block and s.else_block.statements:
                        lines.append(f"{prefix}}} else {{")
                        render_statements(s.else_block.statements, level + 1)
                    lines.append(f"{prefix}}}")
                elif isinstance(s, WhileStmt):
                    if s.condition:
                        cond_args = ", ".join(f"{k}={v!r}" for k, v in s.condition.args.items() if k != "target")
                        cond_str = f"{s.condition.name}({cond_args})"
                    else:
                        cond_str = "1"
                    lines.append(f"{prefix}while ({cond_str}) {{")
                    render_statements(s.body.statements, level + 1)
                    lines.append(f"{prefix}}}")
                elif isinstance(s, BlockStmt):
                    render_statements(s.statements, level)

        render_statements(self.body.statements, 1)
        lines.append("}")
        return "\n".join(lines)


class ScriptASTBuilder:
    """
    Transforms low-level ControlFlowGraph basic blocks into structured high-level AST.
    Performs loop analysis, branch structuring (if-then-else), and goto fallback.
    """

    @classmethod
    def from_script(cls, script: DisassembledScript, function_name: str = "game_event") -> ScriptAST:
        cfg = ControlFlowGraph.from_script(script)
        return cls.from_cfg(cfg, function_name=function_name)

    @classmethod
    def from_cfg(cls, cfg: ControlFlowGraph, function_name: str = "game_event") -> ScriptAST:
        builder = cls(cfg)
        body = builder._structure_blocks()
        return ScriptAST(function_name=function_name, body=body)

    def __init__(self, cfg: ControlFlowGraph):
        self.cfg = cfg
        self.visited_blocks: Set[int] = set()

    def _structure_blocks(self) -> BlockStmt:
        root_block = BlockStmt()
        sorted_addrs = sorted(self.cfg.blocks.keys())

        i = 0
        while i < len(sorted_addrs):
            addr = sorted_addrs[i]
            if addr in self.visited_blocks:
                i += 1
                continue

            stmt = self._process_block_at(addr, sorted_addrs, i)
            if stmt:
                root_block.statements.append(stmt)
            i += 1

        return root_block

    def _process_block_at(self, addr: int, sorted_addrs: List[int], idx: int) -> Optional[Statement]:
        if addr in self.visited_blocks:
            return None
        self.visited_blocks.add(addr)

        block = self.cfg.blocks[addr]
        stmts: List[Statement] = []

        if block.label:
            stmts.append(LabelStmt(name=block.label))

        if not block.instructions:
            return BlockStmt(stmts) if stmts else None

        # Check for loop back-edge
        has_self_loop = any(succ == addr for succ in block.successors)
        if has_self_loop:
            last_ins = block.instructions[-1]
            body_instrs = block.instructions[:-1]
            body_stmts = [self._convert_instr(ins) for ins in body_instrs]
            return WhileStmt(condition=last_ins, body=BlockStmt(body_stmts))

        last_ins = block.instructions[-1]
        op_name = last_ins.name.upper()
        is_terminal = op_name in ("END", "RETURN", "EXIT", "HALT")
        is_conditional = len(block.successors) == 2 and not is_terminal

        # Non-branch instructions in this block
        prefix_instrs = block.instructions[:-1] if (is_conditional or is_terminal or "JUMP" in op_name) else block.instructions
        for ins in prefix_instrs:
            stmts.append(self._convert_instr(ins))

        if is_terminal:
            stmts.append(ReturnStmt(instruction=last_ins))
            return BlockStmt(stmts) if len(stmts) > 1 else stmts[0]

        if is_conditional:
            # Structuring If-Then-Else or If-Then
            succ1, succ2 = block.successors[0], block.successors[1]
            # Branch taken target is usually referenced in jump args
            jump_target = None
            for arg_val in last_ins.args.values():
                if isinstance(arg_val, int):
                    jump_target = arg_val
                    break
                elif isinstance(arg_val, str) and arg_val.startswith("LABEL_"):
                    try:
                        jump_target = int(arg_val.split("_")[1], 16)
                        break
                    except (ValueError, IndexError):
                        pass

            taken_addr = jump_target if jump_target in (succ1, succ2) else succ1
            fallthrough_addr = succ2 if taken_addr == succ1 else succ1

            # Check if this is an If-Else diamond
            taken_block = self.cfg.blocks.get(taken_addr)
            fall_block = self.cfg.blocks.get(fallthrough_addr)

            if taken_block and fall_block:
                # Diamond: both have same single successor (join point)
                if taken_block.successors and fall_block.successors and taken_block.successors == fall_block.successors:
                    self.visited_blocks.add(taken_addr)
                    self.visited_blocks.add(fallthrough_addr)

                    then_stmts = [self._convert_instr(ins) for ins in taken_block.instructions if "JUMP" not in ins.name.upper()]
                    else_stmts = [self._convert_instr(ins) for ins in fall_block.instructions if "JUMP" not in ins.name.upper()]

                    if_stmt = IfStmt(
                        condition=last_ins,
                        then_block=BlockStmt(then_stmts),
                        else_block=BlockStmt(else_stmts),
                    )
                    stmts.append(if_stmt)
                    return BlockStmt(stmts) if len(stmts) > 1 else stmts[0]

                # If-then without else
                elif fall_block.successors == [taken_addr]:
                    self.visited_blocks.add(fallthrough_addr)
                    then_stmts = [self._convert_instr(ins) for ins in fall_block.instructions if "JUMP" not in ins.name.upper()]
                    if_stmt = IfStmt(
                        condition=last_ins,
                        then_block=BlockStmt(then_stmts),
                        else_block=None,
                    )
                    stmts.append(if_stmt)
                    return BlockStmt(stmts) if len(stmts) > 1 else stmts[0]

            # Fallback for complex branch: emit instruction + goto
            stmts.append(InstructionStmt(last_ins))
            return BlockStmt(stmts) if len(stmts) > 1 else stmts[0]

        if "JUMP" in op_name:
            target_lbl = str(last_ins.args.get("target", f"0x{block.successors[0]:04X}" if block.successors else "UNKNOWN"))
            stmts.append(GotoStmt(target=target_lbl))

        return BlockStmt(stmts) if len(stmts) > 1 else (stmts[0] if stmts else None)

    @staticmethod
    def _convert_instr(ins: Instruction) -> Statement:
        op = ins.name.upper()
        if op in ("END", "RETURN", "EXIT", "HALT"):
            return ReturnStmt(instruction=ins)
        return InstructionStmt(instruction=ins)
