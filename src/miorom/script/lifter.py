import hashlib
import json
import os
from collections import defaultdict
from dataclasses import asdict
from typing import Dict, List, Optional, Set, Tuple

from miorom.asm.disasm import DisasmInstruction, UniversalDisassembler
from miorom.script.ir import IRBlock, IRFunction, IRInstruction, IROp, IRVar

_CACHE_SCHEMA = 4


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
        arch_norm = arch.lower()
        has_mips_delay_slots = "mips" in arch_norm

        # Partition into basic blocks
        leaders: Set[int] = {base_address}
        for idx, ins in enumerate(disasm_list):
            if ins.is_branch or ins.is_return:
                if ins.target_address:
                    leaders.add(ins.target_address)
                if has_mips_delay_slots and idx + 1 < len(disasm_list):
                    leaders.add(ins.address + (ins.size * 2))
                else:
                    # Next instruction after branch/call is a potential leader
                    leaders.add(ins.address + ins.size)

        next_ins_addr: Dict[int, int] = {}
        for idx, ins in enumerate(disasm_list):
            if has_mips_delay_slots and (ins.is_branch or ins.is_return) and idx + 1 < len(disasm_list):
                next_ins_addr[ins.address] = disasm_list[idx + 1].address + disasm_list[idx + 1].size
            elif idx + 1 < len(disasm_list):
                next_ins_addr[ins.address] = disasm_list[idx + 1].address
            else:
                next_ins_addr[ins.address] = ins.address + ins.size

        blocks: Dict[int, IRBlock] = {}
        cur_block: Optional[IRBlock] = None

        def last_non_nop(block: IRBlock) -> Optional[IRInstruction]:
            for past_ins in reversed(block.instructions):
                if past_ins.op != IROp.NOP:
                    return past_ins
            return None

        idx = 0
        while idx < len(disasm_list):
            ins = disasm_list[idx]
            if ins.address in leaders or cur_block is None:
                lbl = f"loc_{ins.address:08X}"
                cur_block = IRBlock(label=lbl, address=ins.address)
                blocks[ins.address] = cur_block
                ir_func.add_block(cur_block)

            if has_mips_delay_slots and (ins.is_branch or ins.is_return):
                delay_slot_available = idx + 1 < len(disasm_list)
                if delay_slot_available:
                    delay_ins = disasm_list[idx + 1]
                    delay_ir = cls._lift_instruction(
                        delay_ins,
                        arch,
                        prev_ins=last_non_nop(cur_block),
                    )
                    if delay_ir:
                        cur_block.add_instruction(delay_ir)

                ir_ins = cls._lift_instruction(ins, arch, prev_ins=last_non_nop(cur_block))
                if ir_ins:
                    if not delay_slot_available:
                        ir_ins.comment = (
                            f"{ir_ins.comment}; " if ir_ins.comment else ""
                        ) + "MIPS delay slot outside lifted data"
                    cur_block.add_instruction(ir_ins)

                cur_block = None
                idx += 2 if delay_slot_available else 1
                continue

            ir_ins = cls._lift_instruction(ins, arch, prev_ins=last_non_nop(cur_block))
            if ir_ins:
                cur_block.add_instruction(ir_ins)

            if ins.is_return or ins.is_branch:
                cur_block = None
            idx += 1

        # Control flow graph edges
        for addr, b in blocks.items():
            if not b.instructions:
                continue
            last = b.instructions[-1]
            if last.op == IROp.BRANCH and last.args:
                target_addr = last.args[0]
                if isinstance(target_addr, int) and target_addr in blocks:
                    target_lbl = blocks[target_addr].label
                    if target_lbl not in b.successors:
                        b.successors.append(target_lbl)
                    if b.label not in blocks[target_addr].predecessors:
                        blocks[target_addr].predecessors.append(b.label)
            elif last.op == IROp.BRANCH_COND and last.args:
                # Taken branch edge
                target_addr = last.args[0]
                if isinstance(target_addr, int) and target_addr in blocks:
                    target_lbl = blocks[target_addr].label
                    if target_lbl not in b.successors:
                        b.successors.append(target_lbl)
                    if b.label not in blocks[target_addr].predecessors:
                        blocks[target_addr].predecessors.append(b.label)
                # Fall-through branch edge
                fallthrough_addr = next_ins_addr.get(last.pc)
                if fallthrough_addr is not None and fallthrough_addr in blocks:
                    ft_lbl = blocks[fallthrough_addr].label
                    if ft_lbl not in b.successors:
                        b.successors.append(ft_lbl)
                    if b.label not in blocks[fallthrough_addr].predecessors:
                        blocks[fallthrough_addr].predecessors.append(b.label)
            elif last.op == IROp.RETURN:
                pass
            else:
                # Non-branch, non-return block falls through to next block
                fallthrough_addr = next_ins_addr.get(last.pc)
                if fallthrough_addr is not None and fallthrough_addr in blocks:
                    ft_lbl = blocks[fallthrough_addr].label
                    if ft_lbl not in b.successors:
                        b.successors.append(ft_lbl)
                    if b.label not in blocks[fallthrough_addr].predecessors:
                        blocks[fallthrough_addr].predecessors.append(b.label)

        # SSA register versioning
        cls.convert_to_ssa(ir_func)
        cls.insert_phi_nodes(ir_func)

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
            with open(path, encoding="utf-8") as cache_file:
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
            if (
                isinstance(item, list)
                and len(item) == 2
                and isinstance(item[0], str)
            ):
                return (item[0], var_or_value(item[1]))
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
    def _lift_instruction(
        cls,
        ins: DisasmInstruction,
        arch: str,
        prev_ins: Optional[IRInstruction] = None,
    ) -> Optional[IRInstruction]:
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
            elif mnem in ("cmpw", "cmpwi", "cmplw", "cmplwi", "cmp", "cmpi", "cmpl", "cmpli") and len(ops) >= 2:
                reg = ops[1] if len(ops) >= 3 else ops[0]
                val_str = ops[2] if len(ops) >= 3 else ops[1]
                val = int(val_str, 0) if val_str.startswith("0x") else (int(val_str) if val_str.lstrip("-").isdigit() else val_str)
                return IRInstruction(IROp.CMP, args=[reg, val], pc=ins.address)
            elif mnem in ("b", "ba") and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("bl", "bla") and ins.target_address:
                return IRInstruction(IROp.CALL, dst="r3", args=[ins.target_address], pc=ins.address)
            elif mnem in ("bc", "bca") and ins.target_address:
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, f"cond_{ops[0]}_{ops[1]}"], pc=ins.address)
            elif mnem in ("beq", "bne", "blt", "bgt", "ble", "bge") and ins.target_address:
                cond_map = {"beq": "==", "bne": "!=", "blt": "<", "bgt": ">", "ble": "<=", "bge": ">="}
                cond = cond_map[mnem]
                if prev_ins and prev_ins.op == IROp.CMP and len(prev_ins.args) >= 2:
                    cond_expr = f"{prev_ins.args[0]} {cond} {prev_ins.args[1]}"
                else:
                    cond_expr = mnem
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, cond_expr], pc=ins.address)

        # ARM & Thumb Lifting
        elif arch_norm in ("arm", "arm32", "thumb", "arm_thumb"):
            if mnem == "mov" and len(ops) >= 2:
                val = int(ops[1].replace("#", ""), 0) if ops[1].startswith("#") else ops[1]
                return IRInstruction(IROp.ASSIGN, dst=ops[0], args=[val], pc=ins.address)
            elif mnem == "bx" and ops and ops[0] == "lr":
                return IRInstruction(IROp.RETURN, args=["r0"], pc=ins.address)
            elif mnem == "pop" and ops and "pc" in ops[0]:
                return IRInstruction(IROp.RETURN, args=["r0"], pc=ins.address)
            elif mnem in ("add", "adds") and len(ops) >= 2:
                if len(ops) >= 3:
                    arg2 = int(ops[2].replace("#", ""), 0) if ops[2].startswith("#") else ops[2]
                    return IRInstruction(IROp.ADD, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
                else:
                    arg1 = int(ops[1].replace("#", ""), 0) if ops[1].startswith("#") else ops[1]
                    return IRInstruction(IROp.ADD, dst=ops[0], args=[ops[0], arg1], pc=ins.address)
            elif mnem in ("sub", "subs") and len(ops) >= 2:
                if len(ops) >= 3:
                    arg2 = int(ops[2].replace("#", ""), 0) if ops[2].startswith("#") else ops[2]
                    return IRInstruction(IROp.SUB, dst=ops[0], args=[ops[1], arg2], pc=ins.address)
                else:
                    arg1 = int(ops[1].replace("#", ""), 0) if ops[1].startswith("#") else ops[1]
                    return IRInstruction(IROp.SUB, dst=ops[0], args=[ops[0], arg1], pc=ins.address)
            elif mnem == "mul" and len(ops) >= 2:
                src = ops[1] if len(ops) >= 2 else ops[0]
                return IRInstruction(IROp.MUL, dst=ops[0], args=[ops[0], src], pc=ins.address)
            elif mnem == "and" and len(ops) >= 2:
                src = ops[1] if len(ops) >= 2 else ops[0]
                return IRInstruction(IROp.AND, dst=ops[0], args=[ops[0], src], pc=ins.address)
            elif mnem == "orr" and len(ops) >= 2:
                src = ops[1] if len(ops) >= 2 else ops[0]
                return IRInstruction(IROp.OR, dst=ops[0], args=[ops[0], src], pc=ins.address)
            elif mnem == "eor" and len(ops) >= 2:
                src = ops[1] if len(ops) >= 2 else ops[0]
                return IRInstruction(IROp.XOR, dst=ops[0], args=[ops[0], src], pc=ins.address)
            elif mnem in ("lsl", "lsls") and len(ops) >= 2:
                arg = int(ops[2].replace("#", ""), 0) if len(ops) >= 3 and ops[2].startswith("#") else (ops[2] if len(ops) >= 3 else ops[1])
                src = ops[1] if len(ops) >= 3 else ops[0]
                return IRInstruction(IROp.SHL, dst=ops[0], args=[src, arg], pc=ins.address)
            elif mnem in ("lsr", "lsrs", "asr", "asrs") and len(ops) >= 2:
                arg = int(ops[2].replace("#", ""), 0) if len(ops) >= 3 and ops[2].startswith("#") else (ops[2] if len(ops) >= 3 else ops[1])
                src = ops[1] if len(ops) >= 3 else ops[0]
                return IRInstruction(IROp.SHR, dst=ops[0], args=[src, arg], pc=ins.address)
            elif mnem in ("ldr", "ldrb", "ldrh", "ldsb", "ldsh") and len(ops) >= 2:
                return IRInstruction(IROp.LOAD, dst=ops[0], args=[ops[1]], pc=ins.address)
            elif mnem in ("str", "strb", "strh") and len(ops) >= 2:
                return IRInstruction(IROp.STORE, dst=None, args=[ops[1], ops[0]], pc=ins.address)
            elif mnem in ("cmp", "cmn", "tst", "teq") and len(ops) >= 2:
                op0 = ops[0]
                raw_val = ops[1].replace("#", "") if ops[1].startswith("#") else ops[1]
                val = int(raw_val, 0) if raw_val.startswith("0x") else (int(raw_val) if raw_val.lstrip("-").isdigit() else raw_val)
                if mnem == "cmn":
                    val = -val if isinstance(val, int) else f"-({val})"
                elif mnem == "tst":
                    return IRInstruction(IROp.CMP, args=[f"({op0} & {val})", 0], pc=ins.address)
                elif mnem == "teq":
                    return IRInstruction(IROp.CMP, args=[f"({op0} ^ {val})", 0], pc=ins.address)
                return IRInstruction(IROp.CMP, args=[op0, val], pc=ins.address)
            elif mnem == "bl" and ins.target_address:
                return IRInstruction(IROp.CALL, dst="r0", args=[ins.target_address], pc=ins.address)
            elif mnem in ("b", "bal") and ins.target_address:
                if ins.is_conditional:
                    return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, "cond"], pc=ins.address)
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("beq", "bne", "bcs", "bcc", "bmi", "bpl", "bvs", "bvc", "bhi", "bls", "bge", "blt", "bgt", "ble") and ins.target_address:
                arm_cond_map = {
                    "beq": "==",
                    "bne": "!=",
                    "blt": "<",
                    "ble": "<=",
                    "bgt": ">",
                    "bge": ">=",
                    "blo": "<",
                    "bcc": "<",
                    "bls": "<=",
                    "bhi": ">",
                    "bhs": ">=",
                    "bcs": ">=",
                    "bmi": "< 0",
                    "bpl": ">= 0",
                }
                if prev_ins and prev_ins.op == IROp.CMP and len(prev_ins.args) >= 2:
                    op_sym = arm_cond_map.get(mnem, mnem)
                    if mnem in ("bmi", "bpl"):
                        cond_expr = f"{prev_ins.args[0]} {op_sym}"
                    elif mnem in ("blo", "bcc", "bls", "bhi", "bhs", "bcs"):
                        cond_expr = f"(unsigned){prev_ins.args[0]} {op_sym} (unsigned){prev_ins.args[1]}"
                    else:
                        cond_expr = f"{prev_ins.args[0]} {op_sym} {prev_ins.args[1]}"
                else:
                    cond_expr = mnem
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, cond_expr], pc=ins.address)

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
            elif mnem == "cp" and ops:
                val = int(ops[0], 0) if ops[0].startswith("0x") else (int(ops[0]) if ops[0].lstrip("-").isdigit() else ops[0])
                return IRInstruction(IROp.CMP, args=["a", val], pc=ins.address)
            elif mnem in ("jp", "jr") and ins.target_address:
                if ins.is_conditional:
                    cond_name = ops[0].lower() if ops else "cond"
                    cond_sm83_map = {"z": "==", "nz": "!=", "c": "<", "nc": ">="}
                    if prev_ins and prev_ins.op == IROp.CMP and len(prev_ins.args) >= 2 and cond_name in cond_sm83_map:
                        cond_expr = f"{prev_ins.args[0]} {cond_sm83_map[cond_name]} {prev_ins.args[1]}"
                    else:
                        cond_expr = cond_name
                    return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, cond_expr], pc=ins.address)
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
            elif mnem in ("cmp", "cmpi", "cmpa") and len(ops) >= 2:
                op0 = ops[0].replace("#", "") if ops[0].startswith("#") else ops[0]
                val = int(op0, 0) if op0.startswith("0x") else (int(op0) if op0.lstrip("-").isdigit() else op0)
                return IRInstruction(IROp.CMP, args=[ops[1], val], pc=ins.address)
            elif mnem == "tst" and ops:
                return IRInstruction(IROp.CMP, args=[ops[0], 0], pc=ins.address)
            elif mnem in ("bra", "jmp") and ins.target_address:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("beq", "bne", "blt", "ble", "bgt", "bge", "bcs", "bcc", "bmi", "bpl") and ins.target_address:
                m68k_cond_map = {
                    "beq": "==", "bne": "!=", "blt": "<", "ble": "<=", "bgt": ">", "bge": ">=",
                    "bcs": "<", "bcc": ">=", "bmi": "< 0", "bpl": ">= 0"
                }
                if prev_ins and prev_ins.op == IROp.CMP and len(prev_ins.args) >= 2:
                    op_sym = m68k_cond_map.get(mnem, mnem)
                    if mnem in ("bmi", "bpl"):
                        cond_expr = f"{prev_ins.args[0]} {op_sym}"
                    else:
                        cond_expr = f"{prev_ins.args[0]} {op_sym} {prev_ins.args[1]}"
                else:
                    cond_expr = mnem
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, cond_expr], pc=ins.address)
            elif mnem in ("bsr", "jsr") and ins.target_address:
                return IRInstruction(IROp.CALL, dst="d0", args=[ins.target_address], pc=ins.address)

        # 6502 / 65816 Lifting (NES / SNES)
        elif arch_norm in ("6502", "nes", "famicom", "2a03", "65816", "snes", "sfc", "5a22", "w65c816"):
            if mnem == "nop":
                return IRInstruction(IROp.NOP, pc=ins.address)
            elif mnem in ("rts", "rtl"):
                return IRInstruction(IROp.RETURN, args=["a"], pc=ins.address)
            elif mnem in ("lda", "ldx", "ldy") and ops:
                target_reg = "a" if mnem == "lda" else ("x" if mnem == "ldx" else "y")
                op0 = ops[0]
                if op0.startswith("#$") or op0.startswith("#"):
                    val = int(op0.replace("#$", "0x").replace("#", ""), 0)
                    return IRInstruction(IROp.ASSIGN, dst=target_reg, args=[val], pc=ins.address)
                else:
                    return IRInstruction(IROp.LOAD, dst=target_reg, args=[op0], pc=ins.address)
            elif mnem in ("sta", "stx", "sty") and ops:
                src_reg = "a" if mnem == "sta" else ("x" if mnem == "stx" else "y")
                return IRInstruction(IROp.STORE, dst=None, args=[ops[0], src_reg], pc=ins.address)
            elif mnem == "stz" and ops:
                return IRInstruction(IROp.STORE, dst=None, args=[ops[0], 0], pc=ins.address)
            elif mnem in ("cmp", "cpx", "cpy") and ops:
                target_reg = "a" if mnem == "cmp" else ("x" if mnem == "cpx" else "y")
                op0 = ops[0]
                val = int(op0.replace("#$", "0x").replace("#", ""), 0) if (op0.startswith("#$") or op0.startswith("#")) else op0
                return IRInstruction(IROp.CMP, args=[target_reg, val], pc=ins.address)
            elif mnem in ("tax", "txa", "tay", "tya", "tsx", "txs", "txy", "tyx", "tcd", "tdc", "tcs", "tsc"):
                src_dst_map = {
                    "tax": ("x", "a"), "txa": ("a", "x"),
                    "tay": ("y", "a"), "tya": ("a", "y"),
                    "tsx": ("x", "sp"), "txs": ("sp", "x"),
                    "txy": ("y", "x"), "tyx": ("x", "y"),
                    "tcd": ("d", "a"), "tdc": ("a", "d"),
                    "tcs": ("sp", "a"), "tsc": ("a", "sp"),
                }
                dst, src = src_dst_map[mnem]
                return IRInstruction(IROp.ASSIGN, dst=dst, args=[src], pc=ins.address)
            elif mnem in ("adc", "sbc") and ops:
                op_type = IROp.ADD if mnem == "adc" else IROp.SUB
                val = ops[0]
                arg = int(val.replace("#$", "0x").replace("#", ""), 0) if (val.startswith("#$") or val.startswith("#")) else val
                return IRInstruction(op_type, dst="a", args=["a", arg], pc=ins.address)
            elif mnem in ("and", "ora", "eor") and ops:
                op_type = IROp.AND if mnem == "and" else (IROp.OR if mnem == "ora" else IROp.XOR)
                val = ops[0]
                arg = int(val.replace("#$", "0x").replace("#", ""), 0) if (val.startswith("#$") or val.startswith("#")) else val
                return IRInstruction(op_type, dst="a", args=["a", arg], pc=ins.address)
            elif mnem in ("asl", "lsr"):
                op_type = IROp.SHL if mnem == "asl" else IROp.SHR
                dst_reg = ops[0] if ops else "a"
                return IRInstruction(op_type, dst=dst_reg, args=[dst_reg, 1], pc=ins.address)
            elif mnem in ("inc", "dec") and ops:
                op_type = IROp.ADD if mnem == "inc" else IROp.SUB
                dst_reg = ops[0]
                return IRInstruction(op_type, dst=dst_reg, args=[dst_reg, 1], pc=ins.address)
            elif mnem in ("inx", "iny"):
                dst_reg = "x" if mnem == "inx" else "y"
                return IRInstruction(IROp.ADD, dst=dst_reg, args=[dst_reg, 1], pc=ins.address)
            elif mnem in ("dex", "dey"):
                dst_reg = "x" if mnem == "dex" else "y"
                return IRInstruction(IROp.SUB, dst=dst_reg, args=[dst_reg, 1], pc=ins.address)
            elif mnem in ("jsr", "jsl") and ins.target_address is not None:
                return IRInstruction(IROp.CALL, dst="a", args=[ins.target_address], pc=ins.address)
            elif mnem in ("jmp", "jml", "bra", "brl") and ins.target_address is not None:
                return IRInstruction(IROp.BRANCH, args=[ins.target_address], pc=ins.address)
            elif mnem in ("beq", "bne", "bcs", "bcc", "bmi", "bpl", "bvs", "bvc") and ins.target_address is not None:
                cond_6502_map = {
                    "beq": "==", "bne": "!=", "bcc": "<", "bcs": ">=", "bmi": "< 0", "bpl": ">= 0"
                }
                if prev_ins and prev_ins.op == IROp.CMP and len(prev_ins.args) >= 2:
                    op_sym = cond_6502_map.get(mnem, mnem)
                    if mnem in ("bmi", "bpl"):
                        cond_expr = f"{prev_ins.args[0]} {op_sym}"
                    else:
                        cond_expr = f"{prev_ins.args[0]} {op_sym} {prev_ins.args[1]}"
                else:
                    cond_expr = mnem
                return IRInstruction(IROp.BRANCH_COND, args=[ins.target_address, cond_expr], pc=ins.address)

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
                    if cls._is_register_name(a):
                        v = var_counts[a]
                        new_args.append(IRVar(name=a, version=v))
                    else:
                        new_args.append(a)
                ins.args = new_args

                # Assign new version to written dst
                if ins.dst and cls._is_register_name(ins.dst):
                    var_counts[ins.dst] += 1
                    ins.dst = IRVar(name=ins.dst, version=var_counts[ins.dst])

    @classmethod
    def insert_phi_nodes(cls, ir_func: IRFunction) -> None:
        """
        Insert PHI nodes for live-in registers at CFG merge points.
        """
        block_out_versions = cls._block_out_versions(ir_func)
        max_versions = cls._max_ssa_versions(ir_func)

        for block in ir_func.blocks.values():
            if len(block.predecessors) < 2:
                continue

            live_in_regs = cls._live_in_registers(block)
            phi_nodes: List[IRInstruction] = []
            replacements: Dict[str, IRVar] = {}

            for reg_name in sorted(live_in_regs):
                incoming: List[Tuple[str, IRVar]] = []
                incoming_versions: Set[int] = set()
                missing_version = False

                for pred_label in block.predecessors:
                    pred_versions = block_out_versions.get(pred_label, {})
                    pred_var = pred_versions.get(reg_name)
                    if pred_var is None:
                        missing_version = True
                        break
                    incoming.append((pred_label, pred_var))
                    incoming_versions.add(pred_var.version)

                if missing_version or len(incoming_versions) < 2:
                    continue

                max_versions[reg_name] += 1
                phi_dst = IRVar(name=reg_name, version=max_versions[reg_name])
                phi_nodes.append(IRInstruction(op=IROp.PHI, dst=phi_dst, args=incoming, pc=block.address))
                replacements[reg_name] = phi_dst

            if not phi_nodes:
                continue

            cls._rewrite_block_live_in_uses(block, replacements)
            block.instructions = phi_nodes + block.instructions

    @classmethod
    def _is_register_name(cls, name: object) -> bool:
        if not isinstance(name, str):
            return False
        if " " in name or any(op in name for op in ("==", "!=", "<", ">", "+", "-", "*", "/", "&", "|", "^")):
            return False
        return (
            name.startswith("$")
            or name in ("a", "x", "y", "sp", "lr", "pc")
            or (name.startswith("r") and name[1:].isdigit())
            or (name.startswith("d") and name[1:].isdigit())
        )

    @classmethod
    def _block_out_versions(cls, ir_func: IRFunction) -> Dict[str, Dict[str, IRVar]]:
        versions: Dict[str, IRVar] = {}
        out_versions: Dict[str, Dict[str, IRVar]] = {}

        for block in ir_func.blocks.values():
            block_versions = dict(versions)
            for ins in block.instructions:
                if isinstance(ins.dst, IRVar):
                    block_versions[ins.dst.name] = ins.dst
            versions = block_versions
            out_versions[block.label] = dict(block_versions)

        return out_versions

    @classmethod
    def _max_ssa_versions(cls, ir_func: IRFunction) -> Dict[str, int]:
        max_versions: Dict[str, int] = defaultdict(int)

        def record(value: object) -> None:
            if isinstance(value, IRVar):
                max_versions[value.name] = max(max_versions[value.name], value.version)

        for block in ir_func.blocks.values():
            for ins in block.instructions:
                record(ins.dst)
                for arg in ins.args:
                    if isinstance(arg, tuple) and len(arg) == 2:
                        record(arg[1])
                    else:
                        record(arg)

        return max_versions

    @classmethod
    def _live_in_registers(cls, block: IRBlock) -> Set[str]:
        live_in: Set[str] = set()
        defined: Set[str] = set()

        for ins in block.instructions:
            for arg in ins.args:
                if isinstance(arg, IRVar) and arg.name not in defined:
                    live_in.add(arg.name)
            if isinstance(ins.dst, IRVar):
                defined.add(ins.dst.name)

        return live_in

    @classmethod
    def _rewrite_block_live_in_uses(cls, block: IRBlock, replacements: Dict[str, IRVar]) -> None:
        defined: Set[str] = set()

        for ins in block.instructions:
            new_args = []
            for arg in ins.args:
                if isinstance(arg, IRVar) and arg.name in replacements and arg.name not in defined:
                    new_args.append(replacements[arg.name])
                else:
                    new_args.append(arg)
            ins.args = new_args

            if isinstance(ins.dst, IRVar):
                defined.add(ins.dst.name)

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

                elif ins.op == IROp.CMP:
                    op2 = f"0x{ins.args[1]:X}" if isinstance(ins.args[1], int) else str(ins.args[1])
                    lines.append(f"    // cmp {ins.args[0]}, {op2};")

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
