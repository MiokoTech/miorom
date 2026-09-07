"""
miorom.script.vm_profiler
~~~~~~~~~~~~~~~~~~~~~~~~~
Bytecode Virtual Machine Opcode Profiler & Grammar Synthesizer.
Traces VM interpreter dispatch loops, analyzes machine code handlers to deduce
argument lengths and operand byte sizes, and synthesizes structured opcode schemas
for BytecodeEngine and ScriptDecompiler.
"""

from dataclasses import dataclass, field
from enum import Enum
import struct
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction
from miorom.asm.slicer import JumpTable


class OpcodeCategory(Enum):
    FLOW = "flow"            # Jump, call, return, yield
    ARITHMETIC = "arith"     # Add, sub, mul, bitwise
    MEMORY = "memory"        # Load, store variable/flag
    DIALOGUE = "dialogue"    # Print text, display box
    SYSTEM = "system"        # Wait, nop, sound effect, camera
    UNKNOWN = "unknown"


@dataclass
class OpcodeSpec:
    """Dissected specification for a single VM bytecode instruction."""
    opcode: int
    handler_address: int
    arg_size: int = 0
    arg_format: str = ""
    category: OpcodeCategory = OpcodeCategory.UNKNOWN
    guessed_name: str = ""
    description: str = ""


@dataclass
class VMSpecification:
    """Complete specification of a reconstructed script VM bytecode grammar."""
    dispatch_address: int
    opcode_count: int
    opcodes: Dict[int, OpcodeSpec] = field(default_factory=dict)

    def to_engine_config(self) -> Dict[int, Dict[str, Any]]:
        """Converts into configuration dictionary ready for BytecodeEngine."""
        config: Dict[int, Dict[str, Any]] = {}
        for op_id, spec in self.opcodes.items():
            config[op_id] = {
                "name": spec.guessed_name or f"OP_{op_id:02X}",
                "arg_size": spec.arg_size,
                "arg_format": spec.arg_format,
                "category": spec.category.value,
            }
        return config

    def to_python_schema(self) -> str:
        """Synthesizes readable Python instruction set code."""
        lines = ["# Reconstructed Bytecode Virtual Machine Schema", "INSTRUCTION_SET = {"]
        for op_id, spec in sorted(self.opcodes.items()):
            name = spec.guessed_name or f"OP_{op_id:02X}"
            lines.append(
                f"    0x{op_id:02X}: {{'name': '{name}', 'arg_size': {spec.arg_size}, "
                f"'arg_format': '{spec.arg_format}', 'category': '{spec.category.value}'}},"
            )
        lines.append("}")
        return "\n".join(lines)


class VMBytecodeSynthesizer:
    """
    Automated reverse engineering engine for proprietary script VMs.
    """

    @classmethod
    def profile_handler(
        cls,
        code: bytes,
        handler_addr: int,
        base_address: int,
        arch: str = "arm",
        endian: str = "<",
        max_instructions: int = 40,
    ) -> OpcodeSpec:
        """
        Disassembles and analyzes an individual opcode handler to estimate argument size and type.
        """
        step = 2 if arch.lower() == "thumb" else 4
        instructions: List[DisasmInstruction] = []
        cur_pc = handler_addr

        arg_bytes = 0
        has_branch = False
        has_call = False
        has_return = False

        for _ in range(max_instructions):
            off = cur_pc - base_address
            if not (0 <= off <= len(code) - step):
                break

            try:
                raw_chunk = code[off : off + step]
                ins = UniversalDisassembler.disassemble_instruction(
                    address=cur_pc,
                    raw_bytes=raw_chunk,
                    arch=arch,
                    endian=endian,
                )
                instructions.append(ins)
            except Exception:
                break

            dis = ins.disassembly.lower()

            # Analyze PC advance / argument reads from script pointer
            # In ARM: LDRB Rn, [Rm], #1 / LDRH Rn, [Rm], #2 / LDR Rn, [Rm], #4
            if "#1" in dis or "ldrb" in dis:
                arg_bytes = max(arg_bytes, 1)
            elif "#2" in dis or "ldrh" in dis:
                arg_bytes = max(arg_bytes, 2)
            elif "#4" in dis or ("ldr " in dis and "#4" in dis):
                arg_bytes = max(arg_bytes, 4)

            if ins.is_return:
                has_return = True
                break
            if ins.is_call:
                has_call = True
            if ins.is_branch and not ins.is_conditional:
                # Unconditional jump (often loop back to dispatcher)
                break

            cur_pc += step

        # Determine category and arg format
        if arg_bytes == 1:
            fmt = f"{endian}B"
        elif arg_bytes == 2:
            fmt = f"{endian}H"
        elif arg_bytes == 4:
            fmt = f"{endian}I"
        else:
            fmt = ""

        if has_return:
            cat = OpcodeCategory.FLOW
            name = "RET"
        elif has_call:
            cat = OpcodeCategory.SYSTEM
            name = "CALL"
        else:
            cat = OpcodeCategory.ARITHMETIC if arg_bytes > 0 else OpcodeCategory.SYSTEM
            name = f"EXEC_{arg_bytes}B"

        return OpcodeSpec(
            opcode=0,
            handler_address=handler_addr,
            arg_size=arg_bytes,
            arg_format=fmt,
            category=cat,
            guessed_name=name,
        )

    @classmethod
    def synthesize_from_jump_table(
        cls,
        code: bytes,
        jump_table: JumpTable,
        base_address: int,
        arch: str = "arm",
        endian: str = "<",
    ) -> VMSpecification:
        """
        Reconstructs the full instruction set from a VM dispatcher's switch-case jump table.
        """
        vm_spec = VMSpecification(
            dispatch_address=jump_table.jump_address,
            opcode_count=jump_table.entry_count,
        )

        for op_id, handler_addr in enumerate(jump_table.case_targets):
            spec = cls.profile_handler(
                code=code,
                handler_addr=handler_addr,
                base_address=base_address,
                arch=arch,
                endian=endian,
            )
            spec.opcode = op_id
            spec.guessed_name = f"OP_{op_id:02X}_{spec.guessed_name}"
            vm_spec.opcodes[op_id] = spec

        return vm_spec
