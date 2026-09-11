"""
from miorom.errors import ParseError
miorom.script.vm
~~~~~~~~~~~~~~~~
Declarative Event & Cutscene Script Virtual Machine (VM) Engine.
Enables reverse engineers to easily define game-specific VM opcodes, disassemble
binary script files into human-readable text, and recompile them with automatic
label and branch target resolution.
"""

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.result import MioRomResult
import ast
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union


@dataclass
class VMOpcodeSpec(MioRomResult):
    code: int
    name: str
    args: List[str]  # e.g. ["u16", "str_utf16", "label"]


class ScriptVM:
    """
    Virtual Machine definition for game event/dialogue bytecode scripts.

    Example:
        vm = ScriptVM(opcode_size=1, endian=">")

        @vm.opcode(0x01, "EXIT")
        @vm.opcode(0x05, "MESSAGE", args=["speaker:u16", "text:str_utf16"])
        @vm.opcode(0x10, "JUMP", args=["target:label"])

        text_script = vm.disassemble(bytecode)
        recompiled = vm.assemble(text_script)
    """

    def __init__(self, opcode_size: int = 1, endian: str = ">"):
        self.opcode_size = opcode_size
        self.endian = endian
        self._opcodes: Dict[int, VMOpcodeSpec] = {}
        self._name_to_opcode: Dict[str, VMOpcodeSpec] = {}

    @property
    def opcodes(self) -> Dict[int, VMOpcodeSpec]:
        return self._opcodes

    def opcode(self, code: int, name: str, args: Optional[List[str]] = None):
        """Decorator or method to register an opcode specification."""
        spec = VMOpcodeSpec(code=code, name=name.upper(), args=args or [])
        self._opcodes[code] = spec
        self._name_to_opcode[name.upper()] = spec

        def decorator(fn):
            return fn
        return decorator

    def register(self, code: int, name: str, args: Optional[List[str]] = None) -> "ScriptVM":
        self.opcode(code, name, args)
        return self

    # ------------------------------------------------------------------
    # Opcode I/O Helpers
    # ------------------------------------------------------------------

    def _read_opcode(self, bytecode: bytes, p: int) -> int:
        if self.opcode_size == 1:
            return BinaryReader.unpack_u8(bytecode, p)
        elif self.opcode_size == 2:
            return BinaryReader.unpack_u16(bytecode, p, endian=self.endian)
        return BinaryReader.unpack_u32(bytecode, p, endian=self.endian)

    def _pack_opcode(self, code: int) -> bytes:
        if self.opcode_size == 1:
            return BinaryWriter.pack_u8(code)
        elif self.opcode_size == 2:
            return BinaryWriter.pack_u16(code, endian=self.endian)
        return BinaryWriter.pack_u32(code, endian=self.endian)

    # ------------------------------------------------------------------
    # Disassembler
    # ------------------------------------------------------------------

    def disassemble(self, bytecode: bytes, start_offset: int = 0) -> str:
        """Disassemble bytecode into readable assembly text with labels."""
        p = start_offset
        limit = len(bytecode)

        # Pass 1: Find all jump targets to place labels
        jump_targets = set()
        while p < limit:
            if p + self.opcode_size > limit:
                break
            code = self._read_opcode(bytecode, p)
            if code not in self._opcodes:
                p += self.opcode_size
                continue
            spec = self._opcodes[code]
            p += self.opcode_size
            for arg_desc in spec.args:
                arg_type = arg_desc.split(":")[-1]
                if arg_type == "label":
                    target = BinaryReader.unpack_u32(bytecode, p, endian=self.endian)
                    jump_targets.add(target)
                    p += 4
                elif arg_type in ("u8", "s8"):
                    p += 1
                elif arg_type in ("u16", "s16"):
                    p += 2
                elif arg_type in ("u32", "s32"):
                    p += 4
                elif arg_type == "str_utf16":
                    while p + 1 < limit:
                        val = BinaryReader.unpack_u16(bytecode, p, endian=self.endian)
                        p += 2
                        if val == 0:
                            break
                elif arg_type == "str_ascii":
                    while p < limit:
                        val = bytecode[p]
                        p += 1
                        if val == 0:
                            break

        # Pass 2: Generate formatted text
        lines: List[str] = []
        p = start_offset
        while p < limit:
            if p in jump_targets:
                lines.append(f"\nlabel_{p:04x}:")

            if p + self.opcode_size > limit:
                break

            curr_addr = p
            code = self._read_opcode(bytecode, p)
            if code not in self._opcodes:
                lines.append(f"    .byte 0x{code:02x}")
                p += self.opcode_size
                continue

            spec = self._opcodes[code]
            p += self.opcode_size
            arg_vals = []

            for arg_desc in spec.args:
                arg_type = arg_desc.split(":")[-1]
                if arg_type == "label":
                    target = BinaryReader.unpack_u32(bytecode, p, endian=self.endian)
                    arg_vals.append(f"label_{target:04x}")
                    p += 4
                elif arg_type == "u8":
                    val = bytecode[p]
                    arg_vals.append(str(val))
                    p += 1
                elif arg_type == "u16":
                    val = BinaryReader.unpack_u16(bytecode, p, endian=self.endian)
                    arg_vals.append(str(val))
                    p += 2
                elif arg_type == "u32":
                    val = BinaryReader.unpack_u32(bytecode, p, endian=self.endian)
                    arg_vals.append(str(val))
                    p += 4
                elif arg_type == "str_utf16":
                    chars = []
                    while p + 1 < limit:
                        val = BinaryReader.unpack_u16(bytecode, p, endian=self.endian)
                        p += 2
                        if val == 0:
                            break
                        chars.append(chr(val))
                    arg_vals.append(repr("".join(chars)))
                elif arg_type == "str_ascii":
                    chars = []
                    while p < limit:
                        val = bytecode[p]
                        p += 1
                        if val == 0:
                            break
                        chars.append(chr(val))
                    arg_vals.append(repr("".join(chars)))

            args_str = " " + ", ".join(arg_vals) if arg_vals else ""
            lines.append(f"    {spec.name}{args_str}")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Assembler
    # ------------------------------------------------------------------

    def assemble(self, asm_text: str) -> bytes:
        """Assemble assembly text back into bytecode, resolving all labels."""
        raw_lines = [line.strip() for line in asm_text.splitlines() if line.strip() and not line.strip().startswith("#")]

        # Pass 1: Compute label positions and instruction lengths
        labels: Dict[str, int] = {}
        cur_pos = 0

        # Structured representation: (spec, [arg_tokens])
        parsed_instructions: List[Tuple[Optional[VMOpcodeSpec], List[str]]] = []

        for line in raw_lines:
            if line.endswith(":"):
                lbl_name = line[:-1].strip()
                labels[lbl_name] = cur_pos
                continue

            # Parse instruction
            parts = line.split(None, 1)
            op_name = parts[0].upper()
            raw_args = []
            if len(parts) > 1:
                # Tokenize args safely respecting quotes
                raw_args = [a.strip() for a in re.findall(r'("(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[^\s,]+)', parts[1])]

            if op_name == ".BYTE":
                val = int(raw_args[0], 0) if raw_args else 0
                cur_pos += 1
                parsed_instructions.append((None, [val]))
                continue

            if op_name not in self._name_to_opcode:
                raise ParseError(f"Unknown opcode '{op_name}' during assembly.")

            spec = self._name_to_opcode[op_name]
            cur_pos += self.opcode_size
            parsed_instructions.append((spec, raw_args))

            for i, arg_desc in enumerate(spec.args):
                arg_type = arg_desc.split(":")[-1]
                if arg_type in ("label", "u32", "s32"):
                    cur_pos += 4
                elif arg_type in ("u16", "s16"):
                    cur_pos += 2
                elif arg_type in ("u8", "s8"):
                    cur_pos += 1
                elif arg_type == "str_utf16":
                    # Safe literal evaluation
                    s_val = ast.literal_eval(raw_args[i]) if i < len(raw_args) else ""
                    cur_pos += (len(s_val) * 2) + 2
                elif arg_type == "str_ascii":
                    s_val = ast.literal_eval(raw_args[i]) if i < len(raw_args) else ""
                    cur_pos += len(s_val) + 1

        # Pass 2: Emit binary bytecode
        out = bytearray()
        for spec, args in parsed_instructions:
            if spec is None:
                # Raw byte
                out.append(args[0] & 0xFF)
                continue

            out.extend(self._pack_opcode(spec.code))
            for i, arg_desc in enumerate(spec.args):
                arg_type = arg_desc.split(":")[-1]
                arg_str = args[i] if i < len(args) else "0"

                if arg_type == "label":
                    lbl = arg_str.strip()
                    target_addr = labels.get(lbl, 0)
                    out.extend(BinaryWriter.pack_u32(target_addr, endian=self.endian))
                elif arg_type == "u8":
                    out.append(int(arg_str, 0) & 0xFF)
                elif arg_type == "u16":
                    out.extend(BinaryWriter.pack_u16(int(arg_str, 0), endian=self.endian))
                elif arg_type == "u32":
                    out.extend(BinaryWriter.pack_u32(int(arg_str, 0), endian=self.endian))
                elif arg_type == "str_utf16":
                    # Safe literal evaluation
                    s_val = ast.literal_eval(arg_str)
                    for ch in s_val:
                        out.extend(BinaryWriter.pack_u16(ord(ch), endian=self.endian))
                    out.extend(b"\x00\x00")
                elif arg_type == "str_ascii":
                    # Safe literal evaluation
                    s_val = ast.literal_eval(arg_str)
                    out.extend(s_val.encode("ascii", errors="replace") + b"\x00")

        return bytes(out)
