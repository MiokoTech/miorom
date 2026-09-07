from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple, Union

from miorom.asm.disasm import DisasmInstruction, UniversalDisassembler
from miorom.script.ir import IRBlock, IRFunction, IRInstruction, IROp, IRVar


class BinaryLifter:
    """
    Automated Binary Lifter & Static Single Assignment (SSA) Micro-IR Decompiler.
    Lifts machine code (PPC, ARM, MIPS) into an architecture-neutral SSA Intermediate
    Representation (Micro-IR) and generates high-level human-readable C pseudocode.
    """

    @classmethod
    def lift(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "ppc",
        function_name: Optional[str] = None,
        endian: Optional[str] = None,
    ) -> IRFunction:
        disasm_list = UniversalDisassembler.disassemble(
            data=data,
            base_address=base_address,
            arch=arch,
            endian=endian,
        )

        func_name = function_name or f"sub_{base_address:08X}"
        ir_func = IRFunction(name=func_name, entry_address=base_address)

        # 1. Split into basic blocks
        leaders: Set[int] = {base_address}
        for ins in disasm_list:
            if ins.is_branch or ins.is_return:
                if ins.target_address:
                    leaders.add(ins.target_address)
                # Next instruction after branch/call is a potential leader
                leaders.add(ins.address + ins.size)

        blocks: Dict[int, IRBlock] = {}
        cur_block: Optional[IRBlock] = None

        for ins in disasm_list:
            if ins.address in leaders or cur_block is None:
                lbl = f"loc_{ins.address:08X}"
                cur_block = IRBlock(label=lbl, address=ins.address)
                blocks[ins.address] = cur_block
                ir_func.add_block(cur_block)

            ir_ins = cls._lift_instruction(ins, arch)
            if ir_ins:
                cur_block.add_instruction(ir_ins)

            if ins.is_return or (ins.is_branch and not ins.is_conditional):
                cur_block = None

        # 2. Build CFG edges
        for addr, b in blocks.items():
            if not b.instructions:
                continue
            last = b.instructions[-1]
            if last.op == IROp.BRANCH and last.args:
                target_addr = last.args[0]
                if isinstance(target_addr, int) and target_addr in blocks:
                    target_lbl = blocks[target_addr].label
                    b.successors.append(target_lbl)
                    blocks[target_addr].predecessors.append(b.label)
            elif last.op == IROp.BRANCH_COND and last.args:
                target_addr = last.args[0]
                if isinstance(target_addr, int) and target_addr in blocks:
                    target_lbl = blocks[target_addr].label
                    b.successors.append(target_lbl)
                    blocks[target_addr].predecessors.append(b.label)

        # 3. Apply SSA Versioning
        cls.convert_to_ssa(ir_func)

        return ir_func

    @classmethod
    def _lift_instruction(cls, ins: DisasmInstruction, arch: str) -> Optional[IRInstruction]:
        arch_norm = arch.lower()
        mnem = ins.mnemonic.lower()
        ops = ins.operands

        # PowerPC Lifting
        if arch_norm in ("ppc", "powerpc", "wii", "gc"):
            if mnem == "nop":
                return IRInstruction(IROp.NOP, pc=ins.address)
            elif mnem == "blr":
                return IRInstruction(IROp.RETURN, args=["r3"], pc=ins.address)
            elif mnem == "li" and len(ops) >= 2:
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[int(ops[1], 0)], pc=ins.address)
            elif mnem == "lis" and len(ops) >= 2:
                val = int(ops[1], 0) << 16
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem == "addi" and len(ops) >= 3:
                return IRInstruction(IROp.ADD, dst=ops[0], args=[ops[1], int(ops[2], 0)], pc=ins.address)
            elif mnem == "add" and len(ops) >= 3:
                return IRInstruction(IROp.ADD, dst=ops[0], args=[ops[1], ops[2]], pc=ins.address)
            elif mnem == "subf" and len(ops) >= 3:
                return IRInstruction(IROp.SUB, dst=ops[0], args=[ops[2], ops[1]], pc=ins.address)
            elif mnem == "lwz" and len(ops) >= 2:
                return IRInstruction(IROp.LOAD, dst=ops[0], args=[ops[1]], pc=ins.address)
            elif mnem == "stw" and len(ops) >= 2:
                return IRInstruction(IROp.STORE, dst=None, args=[ops[1], ops[0]], pc=ins.address)
            elif mnem in ("b", "ba") and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("bl", "bla") and ins.target_address:
                return IRInstruction(IROp.CALL, dst="r3", args=[ins.target_address], pc=ins.address)
            elif mnem in ("bc", "bca") and ins.target_address:
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, f"cond_{ops[0]}_{ops[1]}"], pc=ins.address)

        # ARM Lifting
        elif arch_norm in ("arm", "arm32"):
            if mnem == "mov" and len(ops) >= 2:
                val = int(ops[1].replace("#", ""), 0) if ops[1].startswith("#") else ops[1]
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem == "bx" and ops and ops[0] == "lr":
                return IRInstruction(IROp.RETURN, args=["r0"], pc=ins.address)
            elif mnem == "bl" and ins.target_address:
                return IRInstruction(IROp.CALL, dst="r0", args=[ins.target_address], pc=ins.address)
            elif mnem == "b" and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)

        # MIPS Lifting
        elif "mips" in arch_norm:
            if mnem == "nop":
                return IRInstruction(IROp.NOP, pc=ins.address)
            elif mnem == "jr" and ops and ops[0] in ("$ra", "$31"):
                return IRInstruction(IROp.RETURN, args=["$v0"], pc=ins.address)
            elif mnem == "lui" and len(ops) >= 2:
                val = int(ops[1], 0) << 16
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem in ("addiu", "addi") and len(ops) >= 3:
                return IRInstruction(IROp.ADD, dst=ops[0], args=[ops[1], int(ops[2], 0)], pc=ins.address)
            elif mnem == "jal" and ins.target_address:
                return IRInstruction(IROp.CALL, dst="$v0", args=[ins.target_address], pc=ins.address)
            elif mnem == "j" and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)

        # Generic fallback
        return IRInstruction(IROp.NOP, pc=ins.address, comment=f"{ins.mnemonic} {', '.join(ops)}")

    @classmethod
    def convert_to_ssa(cls, ir_func: IRFunction):
        """
        Rename variables to Static Single Assignment (SSA) form with monotonically increasing versions.
        """
        var_counts: Dict[str, int] = defaultdict(int)

        for b in ir_func.blocks.values():
            for ins in b.instructions:
                # Replace read args with current version
                new_args = []
                for a in ins.args:
                    if isinstance(a, str) and (a.startswith("r") or a.startswith("$")):
                        v = var_counts[a]
                        new_args.append(IRVar(name=a, version=v))
                    else:
                        new_args.append(a)
                ins.args = new_args

                # Assign new version to written dst
                if ins.dst and isinstance(ins.dst, str) and (ins.dst.startswith("r") or ins.dst.startswith("$")):
                    var_counts[ins.dst] += 1
                    ins.dst = IRVar(name=ins.dst, version=var_counts[ins.dst])

    @classmethod
    def decompile_to_c(cls, ir_func: IRFunction, symbols: Optional[Dict[int, str]] = None) -> str:
        """
        Decompile an IRFunction into readable C pseudocode.
        """
        sym_map = symbols or {}
        lines: List[str] = [
            f"int {ir_func.name}() {{",
        ]

        # Declare local variables
        assigned_vars: Set[str] = set()
        for b in ir_func.blocks.values():
            for ins in b.instructions:
                if isinstance(ins.dst, IRVar):
                    assigned_vars.add(ins.dst.ssa_name)

        if assigned_vars:
            vars_sorted = sorted(list(assigned_vars))
            lines.append(f"    int {', '.join(vars_sorted)};")
            lines.append("")

        for b in ir_func.blocks.values():
            lines.append(f"{b.label}:")
            for ins in b.instructions:
                if ins.op == IROp.NOP:
                    continue

                if ins.op == IROp.ASSIGN:
                    val = f"0x{ins.args[0]:X}" if isinstance(ins.args[0], int) else str(ins.args[0])
                    lines.append(f"    {ins.dst} = {val};")

                elif ins.op == IROp.ADD:
                    op2 = f"0x{ins.args[1]:X}" if isinstance(ins.args[1], int) else str(ins.args[1])
                    lines.append(f"    {ins.dst} = {ins.args[0]} + {op2};")

                elif ins.op == IROp.SUB:
                    op2 = f"0x{ins.args[1]:X}" if isinstance(ins.args[1], int) else str(ins.args[1])
                    lines.append(f"    {ins.dst} = {ins.args[0]} - {op2};")

                elif ins.op == IROp.LOAD:
                    lines.append(f"    {ins.dst} = *({ins.args[0]});")

                elif ins.op == IROp.STORE:
                    lines.append(f"    *({ins.args[0]}) = {ins.args[1]};")

                elif ins.op == IROp.CALL:
                    target = ins.args[0]
                    target_name = sym_map.get(target, f"sub_{target:08X}" if isinstance(target, int) else str(target))
                    lines.append(f"    {ins.dst} = {target_name}();")

                elif ins.op == IROp.BRANCH:
                    target = ins.args[0]
                    target_lbl = f"loc_{target:08X}" if isinstance(target, int) else str(target)
                    lines.append(f"    goto {target_lbl};")

                elif ins.op == IROp.BRANCH_COND:
                    target = ins.args[0]
                    cond = ins.args[1] if len(ins.args) > 1 else "cond"
                    target_lbl = f"loc_{target:08X}" if isinstance(target, int) else str(target)
                    lines.append(f"    if ({cond}) goto {target_lbl};")

                elif ins.op == IROp.RETURN:
                    ret_val = ins.args[0] if ins.args else "0"
                    lines.append(f"    return {ret_val};")

            lines.append("")

        lines.append("}")
        return "\n".join(lines)
