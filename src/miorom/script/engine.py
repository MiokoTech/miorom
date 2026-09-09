from miorom.result import MioRomResult
import re
from miorom.errors import ParseError
import shlex
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any, Union

from miorom.script.opcode import (
    OpcodeArg,
    OpcodeDef,
    ArgU8,
    ArgU16,
    ArgU32,
    ArgString,
    ArgBytes,
)


@dataclass
class Instruction(MioRomResult):
    offset: int
    opcode_id: int
    name: str
    args: Dict[str, Any] = field(default_factory=dict)
    label: Optional[str] = None

    def __repr__(self) -> str:
        args_str = ", ".join(f"{k}={v!r}" for k, v in self.args.items())
        lbl = f"{self.label}: " if self.label else ""
        return f"<{lbl}0x{self.offset:04X}: {self.name} {args_str}>"


class DisassembledScript:
    """Represents a disassembled bytecode script with instructions and labels."""

    def __init__(self, instructions: Optional[List[Instruction]] = None):
        self.instructions: List[Instruction] = instructions or []
        self.labels: Dict[int, str] = {}
        for ins in self.instructions:
            if ins.label:
                self.labels[ins.offset] = ins.label

    def to_text(self) -> str:
        """Exports script to clean, human-readable assembly text."""
        lines = ["; Disassembled by MioROM Bytecode Engine", ""]

        for ins in self.instructions:
            if ins.label:
                lines.append(f"{ins.label}:")

            arg_parts = []
            for k, val in ins.args.items():
                if isinstance(val, str) and not val.startswith("LABEL_"):
                    arg_parts.append(f'"{val}"')
                elif isinstance(val, bytes):
                    arg_parts.append(val.hex().upper())
                elif isinstance(val, int) and val > 9:
                    arg_parts.append(f"0x{val:X}")
                else:
                    arg_parts.append(str(val))

            args_joined = " ".join(arg_parts)
            indent = "    "
            lines.append(f"{indent}{ins.name:<16} {args_joined}".rstrip())

        return "\n".join(lines) + "\n"

    def extract_strings(self) -> List[Tuple[int, str, str]]:
        """
        Extracts dialogue strings from instructions.
        Returns a list of (offset, arg_name, text).
        """
        strings = []
        for ins in self.instructions:
            for k, val in ins.args.items():
                if isinstance(val, str) and not val.startswith("LABEL_"):
                    strings.append((ins.offset, k, val))
        return strings

    def replace_strings(self, translations: Dict[Tuple[int, str], str]) -> int:
        """
        Updates dialogue strings in instructions using a translation dictionary
        keyed by (offset, arg_name).
        """
        updated = 0
        for ins in self.instructions:
            for k in list(ins.args.keys()):
                key = (ins.offset, k)
                if key in translations:
                    ins.args[k] = translations[key]
                    updated += 1
        return updated


class BytecodeEngine:
    """
    Generic Script Disassembler & Assembler Engine.
    Enables romhackers to reverse engineer and edit bytecode scripts.
    """

    def __init__(self, endian: str = "<"):
        self.endian = endian
        self.opcodes_by_id: Dict[int, OpcodeDef] = {}
        self.opcodes_by_name: Dict[str, OpcodeDef] = {}

    def register_opcode(
        self,
        opcode_id: int,
        name: str,
        args: Optional[List[OpcodeArg]] = None,
        description: str = ""
    ) -> "BytecodeEngine":
        """Registers an opcode definition with the engine."""
        defn = OpcodeDef(id=opcode_id, name=name, args=args or [], description=description)
        self.opcodes_by_id[opcode_id] = defn
        self.opcodes_by_name[name.upper()] = defn
        return self

    def disassemble(
        self,
        data: bytes,
        start_offset: int = 0,
        end_offset: Optional[int] = None
    ) -> DisassembledScript:
        """Disassembles binary bytecode into instructions and labels."""
        if end_offset is None:
            end_offset = len(data)

        instructions: List[Instruction] = []
        jump_targets = set()
        pos = start_offset

        # Pass 1: Parse instructions
        while pos < end_offset:
            ins_offset = pos
            op_id = data[pos]
            pos += 1

            if op_id not in self.opcodes_by_id:
                # Unknown opcode: emit as raw DB byte
                instructions.append(Instruction(
                    offset=ins_offset,
                    opcode_id=op_id,
                    name=f"DB_0x{op_id:02X}",
                    args={}
                ))
                continue

            defn = self.opcodes_by_id[op_id]
            args = {}

            for arg in defn.args:
                val, consumed = arg.unpack(data, pos, self.endian)
                pos += consumed
                args[arg.name] = val
                if arg.is_jump_target and isinstance(val, int):
                    jump_targets.add(val)

            instructions.append(Instruction(
                offset=ins_offset,
                opcode_id=op_id,
                name=defn.name,
                args=args
            ))

        # Pass 2: Associate labels with jump targets
        for ins in instructions:
            if ins.offset in jump_targets:
                ins.label = f"LABEL_{ins.offset:04X}"

        # Resolve target offsets in jump arguments to label names
        for ins in instructions:
            if ins.opcode_id in self.opcodes_by_id:
                defn = self.opcodes_by_id[ins.opcode_id]
                for arg in defn.args:
                    if arg.is_jump_target and arg.name in ins.args:
                        target = ins.args[arg.name]
                        if isinstance(target, int) and target in jump_targets:
                            ins.args[arg.name] = f"LABEL_{target:04X}"

        return DisassembledScript(instructions)

    def assemble(self, script_input: Union[str, DisassembledScript]) -> bytes:
        """
        Assembles human-readable assembly text or DisassembledScript into binary bytecode.
        Uses two passes to automatically resolve label jump targets.
        """
        if isinstance(script_input, str):
            script = self._parse_text_to_script(script_input)
        else:
            script = script_input

        # Pass 1: Calculate instruction byte sizes and map label offsets
        label_offsets: Dict[str, int] = {}
        curr_offset = 0

        for ins in script.instructions:
            if ins.label:
                label_offsets[ins.label] = curr_offset

            if ins.opcode_id in self.opcodes_by_id:
                defn = self.opcodes_by_id[ins.opcode_id]
                size = 1  # opcode byte
                for arg in defn.args:
                    val = ins.args.get(arg.name, 0)
                    if isinstance(val, str) and val.startswith("LABEL_"):
                        val = 0  # placeholder for sizing
                    size += len(arg.pack(val, self.endian))
                curr_offset += size
            else:
                curr_offset += 1

        # Pass 2: Emit binary bytecode with resolved labels
        out = bytearray()
        for ins in script.instructions:
            if ins.opcode_id not in self.opcodes_by_id:
                out.append(ins.opcode_id)
                continue

            defn = self.opcodes_by_id[ins.opcode_id]
            out.append(ins.opcode_id)

            for arg in defn.args:
                val = ins.args.get(arg.name, 0)
                # Resolve label target
                if isinstance(val, str) and val in label_offsets:
                    val = label_offsets[val]
                out.extend(arg.pack(val, self.endian))

        return bytes(out)

    def _parse_text_to_script(self, text: str) -> DisassembledScript:
        lines = text.splitlines()
        instructions: List[Instruction] = []
        pending_label = None

        for line in lines:
            line = line.strip()
            if not line or line.startswith(";"):
                continue

            if line.endswith(":"):
                pending_label = line[:-1].strip()
                continue

            # Tokenize instruction and arguments
            tokens = shlex.split(line)
            if not tokens:
                continue

            op_name = tokens[0].upper()
            if op_name not in self.opcodes_by_name:
                raise ParseError(f"Unknown opcode name: '{op_name}'")

            defn = self.opcodes_by_name[op_name]
            raw_args = tokens[1:]
            args_dict = {}

            for i, arg_def in enumerate(defn.args):
                if i < len(raw_args):
                    token = raw_args[i]
                    if token.startswith("LABEL_"):
                        args_dict[arg_def.name] = token
                    elif isinstance(arg_def, (ArgU8, ArgU16, ArgU32)):
                        # Handle hex or int
                        val = int(token, 16) if token.lower().startswith("0x") else int(token)
                        args_dict[arg_def.name] = val
                    elif isinstance(arg_def, ArgString):
                        args_dict[arg_def.name] = token
                    else:
                        args_dict[arg_def.name] = token

            ins = Instruction(
                offset=0,
                opcode_id=defn.id,
                name=defn.name,
                args=args_dict,
                label=pending_label
            )
            instructions.append(ins)
            pending_label = None

        return DisassembledScript(instructions)
