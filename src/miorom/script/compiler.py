import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Union

from miorom.script.vm import ScriptVM


class MioScriptCompiler:
    """
    Universal High-Level Script Bytecode Compiler (MioScript DSL).
    Translates high-level structured narrative scripts (with if-else, loops, functions, and string arguments)
    into game-engine bytecode via ScriptVM.
    """

    def __init__(self, vm: Optional[ScriptVM] = None):
        self.vm = vm or self._create_default_vm()
        self._label_counter = 0

    @classmethod
    def _create_default_vm(cls) -> ScriptVM:
        vm = ScriptVM(opcode_size=1, endian=">")
        vm.register(0x00, "NOP")
        vm.register(0x01, "EXIT")
        vm.register(0x02, "MESSAGE", ["text:str"])
        vm.register(0x03, "JUMP", ["target:label"])
        vm.register(0x04, "JUMP_IF_FALSE", ["target:label"])
        vm.register(0x05, "SET_FLAG", ["flag_id:u16", "value:u16"])
        vm.register(0x06, "CHECK_FLAG", ["flag_id:u16"])
        vm.register(0x07, "WAIT", ["frames:u16"])
        return vm

    def _new_label(self, prefix: str = "__lbl") -> str:
        self._label_counter += 1
        return f"{prefix}_{self._label_counter}"

    def compile_to_assembly(self, source_code: str) -> str:
        """
        Compile high-level MioScript source code into linear VM assembly with resolved control flow labels.
        """
        asm_lines: List[str] = []
        lines = source_code.splitlines()

        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1

            if not line or line.startswith("#") or line.startswith("//"):
                continue

            # Labels: label_name:
            if line.endswith(":") and " " not in line:
                asm_lines.append(line)
                continue

            # IF Statement: if (cond) { ... } [else { ... }]
            match_if = re.match(r"^if\s*\((.*?)\)\s*\{?$", line)
            if match_if:
                cond_expr = match_if.group(1).strip()
                lbl_else = self._new_label("__else")
                lbl_endif = self._new_label("__endif")

                # Emit condition check
                asm_lines.extend(self._compile_condition(cond_expr))
                asm_lines.append(f"    JUMP_IF_FALSE {lbl_else}")

                # Collect THEN block
                then_lines = []
                brace_depth = 1
                has_else = False

                while i < len(lines) and brace_depth > 0:
                    inner_line = lines[i].strip()
                    i += 1
                    if "}" in inner_line:
                        brace_depth -= 1
                        if "else" in inner_line:
                            has_else = True
                            break
                        if brace_depth == 0:
                            break
                    then_lines.append(inner_line)

                # Recursively compile THEN body
                then_asm = self.compile_to_assembly("\n".join(then_lines))
                if then_asm:
                    asm_lines.append(then_asm)

                if has_else:
                    asm_lines.append(f"    JUMP {lbl_endif}")
                    asm_lines.append(f"{lbl_else}:")

                    # Collect ELSE block
                    else_lines = []
                    brace_depth = 1
                    while i < len(lines) and brace_depth > 0:
                        inner_line = lines[i].strip()
                        i += 1
                        if "}" in inner_line:
                            brace_depth -= 1
                            if brace_depth == 0:
                                break
                        else_lines.append(inner_line)

                    else_asm = self.compile_to_assembly("\n".join(else_lines))
                    if else_asm:
                        asm_lines.append(else_asm)
                    asm_lines.append(f"{lbl_endif}:")
                else:
                    asm_lines.append(f"{lbl_else}:")

                continue

            # Function call statement: name(arg1, arg2, ...)
            match_call = re.match(r"^([a-zA-Z_0-9]+)\s*\((.*)\);?$", line)
            if match_call:
                fn_name = match_call.group(1).upper()
                raw_args = match_call.group(2).strip()

                # Parse arguments
                parsed_args = self._parse_call_args(raw_args)

                # Map common aliases to VM opcodes
                op_map = {
                    "DIALOGUE": "MESSAGE",
                    "SAY": "MESSAGE",
                    "GOTO": "JUMP",
                    "SLEEP": "WAIT",
                }
                mapped_op = op_map.get(fn_name, fn_name)

                args_str = " ".join(parsed_args)
                asm_lines.append(f"    {mapped_op} {args_str}".strip())
                continue

            # Raw command line
            asm_lines.append(f"    {line}")

        return "\n".join(asm_lines)

    def _compile_condition(self, cond: str) -> List[str]:
        # Handle check_flag(X)
        match_flag = re.match(r"^check_flag\s*\((.*?)\)$", cond)
        if match_flag:
            flag_id = match_flag.group(1).strip()
            return [f"    CHECK_FLAG {flag_id}"]
        return [f"    CHECK {cond}"]

    def _parse_call_args(self, raw_args: str) -> List[str]:
        if not raw_args:
            return []
        # Support string literals with quotes and numbers
        args = []
        token_regex = re.compile(r'("[^"]*"|\S+)')
        for m in token_regex.finditer(raw_args):
            tok = m.group(1).rstrip(",")
            if tok:
                args.append(tok)
        return args

    def compile(self, source_code: str) -> bytes:
        """
        Compile high-level MioScript source code directly into executable bytecode.
        """
        asm_script = self.compile_to_assembly(source_code)
        return self.vm.assemble(asm_script)
