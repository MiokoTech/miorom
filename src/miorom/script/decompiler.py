"""
miorom.script.decompiler
~~~~~~~~~~~~~~~~~~~~~~~~
High-Level Control Flow and Script Decompiler.
Reconstructs structured control flow (if/else, while loops, branch choices)
from disassembled bytecode scripts and Control Flow Graphs into human-readable
Python and C pseudo-code.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.script.engine import DisassembledScript, Instruction
from miorom.script.control_flow import ControlFlowGraph, BasicBlock
from miorom.script.ast import (
    ScriptAST,
    ScriptASTBuilder,
    BlockStmt,
    IfStmt,
    WhileStmt,
    Statement,
    InstructionStmt,
    LabelStmt,
    GotoStmt,
    ReturnStmt,
)


@dataclass
class ChoiceBranch:
    """Represents a choice option in a branching dialog tree."""
    option_index: int
    text: str
    target_label_or_offset: Union[str, int]


@dataclass
class ChoiceBlock:
    """Represents a choice/selection menu construct found in a game script."""
    offset: int
    prompt: Optional[str]
    options: List[ChoiceBranch] = field(default_factory=list)


class ScriptDecompiler:
    """
    Advanced Script Decompiler for ROM Reverse Engineering.
    Reconstructs structured control flow, loops, branch logic, and dialogue
    choice trees from bytecode scripts and Control Flow Graphs.
    """

    @classmethod
    def decompile(
        cls,
        script: DisassembledScript,
        language: str = "python",
        function_name: str = "game_event",
        structured: bool = False,
        indent: str = "    ",
    ) -> str:
        """
        Decompiles a DisassembledScript into pseudo-code.
        If structured=True, synthesizes nested if/else and while loops.
        If structured=False, generates annotated basic block representation.
        """
        cfg = ControlFlowGraph.from_script(script)
        return cls.decompile_cfg(
            cfg=cfg,
            language=language,
            function_name=function_name,
            structured=structured,
            indent=indent,
            script=script,
        )

    @classmethod
    def decompile_structured(
        cls,
        target: Union[DisassembledScript, ControlFlowGraph],
        language: str = "python",
        function_name: str = "game_event",
        indent: str = "    ",
    ) -> str:
        """
        Decompiles a script or CFG into structured if/else and loop pseudo-code.
        """
        if isinstance(target, DisassembledScript):
            cfg = ControlFlowGraph.from_script(target)
        else:
            cfg = target
        return cls.decompile_cfg(
            cfg=cfg,
            language=language,
            function_name=function_name,
            structured=True,
            indent=indent,
        )

    @classmethod
    def decompile_cfg(
        cls,
        cfg: ControlFlowGraph,
        language: str = "python",
        function_name: str = "game_event",
        structured: bool = False,
        indent: str = "    ",
        script: Optional[DisassembledScript] = None,
    ) -> str:
        """
        Decompiles a ControlFlowGraph into high-level Python or C code.
        """
        if structured:
            ast = ScriptASTBuilder.from_cfg(cfg, function_name=function_name)
            if language.lower() == "c":
                return ast.to_c(indent_str=indent)
            else:
                return ast.to_python(indent_str=indent)

        # Annotated basic-block disassembly view
        lines: List[str] = [f"def {function_name}():"] if language.lower() == "python" else [f"void {function_name}(void) {{"]
        sorted_addrs = sorted(cfg.blocks.keys())
        for idx, b_addr in enumerate(sorted_addrs):
            block = cfg.blocks[b_addr]
            if block.label:
                lines.append(f"{indent}# {block.label}:")

            for instr in block.instructions:
                op = instr.name
                args_str = ", ".join(f"{k}={v!r}" for k, v in instr.args.items())
                call_str = f"{op}({args_str})" if args_str else f"{op}()"
                if language.lower() == "c":
                    call_str += ";"
                lines.append(f"{indent}{call_str}")

            # Annotate branches
            if len(block.successors) > 1:
                succ_labels = [f"0x{s:04X}" for s in block.successors]
                comment_prefix = f"{indent}// " if language.lower() == "c" else f"{indent}# "
                lines.append(f"{comment_prefix}Branch -> {', '.join(succ_labels)}")
            elif len(block.successors) == 1:
                target = block.successors[0]
                if idx + 1 < len(sorted_addrs) and sorted_addrs[idx + 1] != target:
                    comment_prefix = f"{indent}// " if language.lower() == "c" else f"{indent}# "
                    lines.append(f"{comment_prefix}Goto 0x{target:04X}")

        if language.lower() == "c":
            lines.append("}")
        return "\n".join(lines)

    @classmethod
    def reconstruct_choices(
        cls,
        script: DisassembledScript,
        choice_opnames: Sequence[str] = ("CHOICE", "SELECT", "MENU", "BRANCH_CASE"),
    ) -> List[ChoiceBlock]:
        """
        Scans a disassembled script to reconstruct interactive dialogue choice blocks
        and their branch destinations.
        """
        choices: List[ChoiceBlock] = []
        i = 0
        instrs = script.instructions
        num_instrs = len(instrs)

        while i < num_instrs:
            ins = instrs[i]
            upper_name = ins.name.upper()

            if any(op in upper_name for op in choice_opnames):
                prompt = str(ins.args.get("prompt", ins.args.get("text", ""))) or None
                block = ChoiceBlock(offset=ins.offset, prompt=prompt)

                j = i + 1
                branch_idx = 0
                while j < num_instrs:
                    next_ins = instrs[j]
                    next_op = next_ins.name.upper()
                    if "CASE" in next_op or "OPTION" in next_op:
                        opt_text = str(next_ins.args.get("text", f"Option {branch_idx}"))
                        target = next_ins.args.get("target", next_ins.args.get("label", next_ins.offset))
                        block.options.append(
                            ChoiceBranch(option_index=branch_idx, text=opt_text, target_label_or_offset=target)
                        )
                        branch_idx += 1
                        j += 1
                    else:
                        break

                if not block.options:
                    for k, v in ins.args.items():
                        if "target" in k or "label" in k or "option" in k:
                            block.options.append(
                                ChoiceBranch(option_index=branch_idx, text=k, target_label_or_offset=v)
                            )
                            branch_idx += 1

                choices.append(block)
                if j > i + 1:
                    i = j
                    continue

            i += 1

        return choices
