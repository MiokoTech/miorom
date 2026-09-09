import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict
from typing import Dict, List, Optional, Set, Tuple, Union

from miorom.asm.disasm import DisasmInstruction, UniversalDisassembler
from miorom.script.ir import IRBlock, IRFunction, IRInstruction, IROp, IRVar

_CACHE_SCHEMA = 2


class BinaryLifter:
    """
    Automated Binary Lifter & Static Single Assignment (SSA) Micro-IR Decompiler.
    Lifts machine code (PPC, ARM, MIPS) into an architecture-neutral SSA Intermediate
    Representation (Micro-IR) and generates high-level human-readable C pseudocode.
    """

    disk_cache_dir: Optional[str] = None

    @classmethod
    def lift(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "ppc",
        function_name: Optional[str] = None,
        endian: Optional[str] = None,
    ) -> IRFunction:
        cache_key = None
        cache_path = None
        if cls.disk_cache_dir:
            digest = hashlib.sha256()
            digest.update(str(_CACHE_SCHEMA).encode("ascii"))
            digest.update((arch or "").lower().encode("utf-8"))
            digest.update((endian or "").encode("ascii"))
            digest.update(str(function_name or "").encode("utf-8"))
            digest.update(base_address.to_bytes(8, "big"))
            digest.update(data)
            cache_key = digest.hexdigest()
            cache_path = os.path.join(cls.disk_cache_dir, f"{cache_key}.json")
            cached = cls._read_cache(cache_path)
            if cached is not None:
                return cached

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

        if cache_path:
            cls._write_cache(cache_path, ir_func)

        return ir_func

    @classmethod
    def enable_disk_cache(cls, path: Optional[str] = None) -> str:
        """Enable persistent lift cache for expensive repeated CFG analysis."""
        cache_dir = path or os.path.join(os.path.expanduser("~"), ".cache", "miorom", "lift")
        os.makedirs(cache_dir, exist_ok=True)
        cls.disk_cache_dir = cache_dir
        return cache_dir

    @classmethod
    def disable_disk_cache(cls) -> None:
        cls.disk_cache_dir = None

    @classmethod
    def clear_disk_cache(cls) -> int:
        if not cls.disk_cache_dir or not os.path.isdir(cls.disk_cache_dir):
            return 0
        removed = 0
        for filename in os.listdir(cls.disk_cache_dir):
            if filename.endswith(".json"):
                try:
                    os.remove(os.path.join(cls.disk_cache_dir, filename))
                    removed += 1
                except OSError:
                    pass
        return removed

    @classmethod
    def _read_cache(cls, path: str) -> Optional[IRFunction]:
        try:
            with open(path, "r", encoding="utf-8") as cache_file:
                payload = json.load(cache_file)
            if payload.get("schema") != _CACHE_SCHEMA:
                return None
            return cls._ir_from_dict(payload["ir"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @classmethod
    def _write_cache(cls, path: str, ir_func: IRFunction) -> None:
        try:
            temp_path = f"{path}.tmp"
            with open(temp_path, "w", encoding="utf-8") as cache_file:
                json.dump(
                    {"schema": _CACHE_SCHEMA, "ir": asdict(ir_func)},
                    cache_file,
                    sort_keys=True,
                    default=lambda value: value.value if isinstance(value, IROp) else str(value),
                )
            os.replace(temp_path, path)
        except OSError:
            pass

    @classmethod
    def _ir_from_dict(cls, value: dict) -> IRFunction:
        def var_or_value(item):
            if isinstance(item, dict) and {"name", "version", "var_type"} <= set(item):
                return IRVar(**item)
            return item

        blocks: Dict[str, IRBlock] = {}
        for label, raw_block in value["blocks"].items():
            instructions = []
            for raw_instruction in raw_block["instructions"]:
                instructions.append(IRInstruction(
                    op=IROp(raw_instruction["op"]),
                    dst=var_or_value(raw_instruction["dst"]),
                    args=[var_or_value(arg) for arg in raw_instruction["args"]],
                    pc=raw_instruction["pc"],
                    comment=raw_instruction["comment"],
                ))
            blocks[label] = IRBlock(
                label=raw_block["label"],
                address=raw_block["address"],
                instructions=instructions,
                predecessors=raw_block["predecessors"],
                successors=raw_block["successors"],
            )

        return_var = value["return_var"]
        if isinstance(return_var, dict):
            return_var = IRVar(**return_var)
        parameters = [
            IRVar(**item) if isinstance(item, dict) else item
            for item in value["parameters"]
        ]
        return IRFunction(
            name=value["name"],
            entry_address=value["entry_address"],
            blocks=blocks,
            parameters=parameters,
            return_var=return_var,
        )

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
            elif mnem == "jr" and ops and ops[0] in ("$ra", "$31", "$v0", "$v1"):
                return IRInstruction(IROp.RETURN, args=["$v0"], pc=ins.address)
            elif mnem == "move" and len(ops) >= 2:
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[ops[1]], pc=ins.address)
            elif mnem == "li" and len(ops) >= 2:
                val = int(ops[1], 0) if ops[1].startswith("0x") else int(ops[1])
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem == "lui" and len(ops) >= 2:
                val = int(ops[1], 0) << 16
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem in ("addiu", "addi", "addu", "add") and len(ops) >= 3:
                arg2 = int(ops[2], 0) if ops[2].startswith("0x") else (int(ops[2]) if ops[2].lstrip("-").isdigit() else ops[2])
                return IRInstruction(IROp.ADD, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
            elif mnem in ("subu", "sub") and len(ops) >= 3:
                return IRInstruction(IROp.SUB, dst=ops[0], args=[ops[1], ops[2]], pc=ins.address)
            elif mnem in ("ori", "or") and len(ops) >= 3:
                arg2 = int(ops[2], 0) if ops[2].startswith("0x") else ops[2]
                return IRInstruction(IROp.OR, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
            elif mnem in ("andi", "and") and len(ops) >= 3:
                arg2 = int(ops[2], 0) if ops[2].startswith("0x") else ops[2]
                return IRInstruction(IROp.AND, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
            elif mnem in ("xori", "xor") and len(ops) >= 3:
                arg2 = int(ops[2], 0) if ops[2].startswith("0x") else ops[2]
                return IRInstruction(IROp.XOR, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
            elif mnem in ("sll", "sllv") and len(ops) >= 3:
                arg2 = int(ops[2], 0) if ops[2].isdigit() else ops[2]
                return IRInstruction(IROp.SHL, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
            elif mnem in ("srl", "srlv", "sra", "srav") and len(ops) >= 3:
                arg2 = int(ops[2], 0) if ops[2].isdigit() else ops[2]
                return IRInstruction(IROp.SHR, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
            elif mnem in ("lw", "lh", "lhu", "lb", "lbu", "lwc1", "ldc1") and len(ops) >= 2:
                return IRInstruction(IROp.LOAD, dst=ops[0], args=[ops[1]], pc=ins.address)
            elif mnem in ("sw", "sh", "sb", "swc1", "sdc1") and len(ops) >= 2:
                return IRInstruction(IROp.STORE, dst=None, args=[ops[1], ops[0]], pc=ins.address)
            elif mnem in ("mfc1", "mtc1") and len(ops) >= 2:
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[ops[1]], pc=ins.address)
            elif mnem.startswith(("add.", "sub.", "mul.", "div.")) and len(ops) >= 3:
                op_map = {"add": IROp.ADD, "sub": IROp.SUB, "mul": IROp.MUL, "div": IROp.DIV}
                prefix = mnem.split(".")[0]
                return IRInstruction(op_map[prefix], dst=ops[0], args=[ops[1], ops[2]], pc=ins.address)
            elif mnem in ("jal", "jalr") and ins.target_address:
                return IRInstruction(IROp.CALL, dst="$v0", args=[ins.target_address], pc=ins.address)
            elif mnem in ("j", "b") and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("beq", "bne") and len(ops) >= 3 and ins.target_address:
                cond_op = "==" if mnem == "beq" else "!="
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, f"{ops[0]} {cond_op} {ops[1]}"], pc=ins.address)
            elif mnem in ("beqz", "bnez", "blez", "bgtz", "bltz", "bgez") and len(ops) >= 2 and ins.target_address:
                c_map = {"beqz": "== 0", "bnez": "!= 0", "blez": "<= 0", "bgtz": "> 0", "bltz": "< 0", "bgez": ">= 0"}
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, f"{ops[0]} {c_map[mnem]}"], pc=ins.address)
            elif mnem in ("bc1t", "bc1f") and ins.target_address:
                cond = "fpu_cond" if mnem == "bc1t" else "!fpu_cond"
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, cond], pc=ins.address)

        # SM83 (Game Boy) Lifting
        elif arch_norm in ("sm83", "gb", "gbc", "gameboy"):
            if mnem == "nop":
                return IRInstruction(IROp.NOP, pc=ins.address)
            elif mnem == "ret":
                return IRInstruction(IROp.RETURN, args=["a"], pc=ins.address)
            elif mnem == "ld" and len(ops) >= 2:
                val = int(ops[1], 0) if ops[1].startswith("0x") else ops[1]
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem in ("jp", "jr") and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem == "call" and ins.target_address:
                return IRInstruction(IROp.CALL, dst="a", args=[ins.target_address], pc=ins.address)

        # M68K (Mega Drive / Genesis) Lifting
        elif arch_norm in ("m68k", "68000", "md", "genesis", "megadrive"):
            if mnem == "nop":
                return IRInstruction(IROp.NOP, pc=ins.address)
            elif mnem == "rts":
                return IRInstruction(IROp.RETURN, args=["d0"], pc=ins.address)
            elif mnem == "moveq" and len(ops) >= 2:
                val = int(ops[0].replace("#", ""), 0) if ops[0].startswith("#") else ops[0]
                return IRInstruction(IROp.ASSIGN, dst=ops[1], args=[val], pc=ins.address)
            elif mnem in ("bra", "jmp") and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("bsr", "jsr") and ins.target_address:
                return IRInstruction(IROp.CALL, dst="d0", args=[ins.target_address], pc=ins.address)

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
