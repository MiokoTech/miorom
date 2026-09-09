from miorom.result import MioRomResult
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from miorom.script.vm import ScriptVM, VMOpcodeSpec


@dataclass
class OpcodeCandidate(MioRomResult):
    code: int
    count: int
    inferred_args: List[str]
    confidence: float

    def signature(self) -> str:
        args_str = f" [{', '.join(self.inferred_args)}]" if self.inferred_args else ""
        return f"Opcode 0x{self.code:02X} (seen {self.count} times){args_str}"


@dataclass
class ArcheologyReport(MioRomResult):
    total_bytes: int
    detected_opcodes: List[OpcodeCandidate] = field(default_factory=list)
    estimated_endian: str = ">"

    def summary(self) -> str:
        lines = [
            "==================================================",
            "      Script Bytecode Archeology Report           ",
            "==================================================",
            f"  Script Stream Size : {self.total_bytes} bytes",
            f"  Detected Opcodes   : {len(self.detected_opcodes)}",
            f"  Estimated Endian   : {self.estimated_endian}",
        ]
        if self.detected_opcodes:
            lines.append("  Inferred Opcode Signatures:")
            for op in self.detected_opcodes:
                lines.append(f"    - {op.signature()} (Confidence: {op.confidence * 100:.0f}%)")
        lines.append("==================================================")
        return "\n".join(lines)


class ScriptArcheologist:
    """
    Opcode Archeology & Bytecode Virtual Machine Reverse-Engineering Engine.
    Analyzes raw bytecode streams, infers argument types and lengths,
    and auto-synthesizes ScriptVM definitions.
    """

    @classmethod
    def analyze_stream(
        cls,
        data: bytes,
        endian: str = ">",
    ) -> ArcheologyReport:
        total_len = len(data)
        if total_len < 4:
            return ArcheologyReport(total_len)

        # 1. Frequency analysis of potential leading bytes
        byte_counts = Counter(data)
        common_bytes = [b for b, count in byte_counts.most_common(20)]

        # 2. Heuristic scan of instruction patterns
        opcodes: Dict[int, OpcodeCandidate] = {}
        pos = 0

        while pos < total_len:
            op_byte = data[pos]
            pos += 1

            # Check if followed by null-terminated ASCII string
            str_end = data.find(b"\x00", pos)
            is_string = False
            if 0 <= str_end - pos <= 256 and str_end != -1:
                candidate_str = data[pos:str_end]
                if len(candidate_str) >= 3 and all(0x20 <= c <= 0x7E or c in (0x0A, 0x0D, 0x09) for c in candidate_str):
                    is_string = True
                    pos = str_end + 1
                    if op_byte not in opcodes:
                        opcodes[op_byte] = OpcodeCandidate(code=op_byte, count=1, inferred_args=["str"], confidence=0.85)
                    else:
                        opcodes[op_byte].count += 1
                    continue

            # Fallback single byte / fixed arguments
            if op_byte not in opcodes:
                opcodes[op_byte] = OpcodeCandidate(code=op_byte, count=1, inferred_args=[], confidence=0.6)
            else:
                opcodes[op_byte].count += 1

        candidates = sorted(list(opcodes.values()), key=lambda x: x.count, reverse=True)
        return ArcheologyReport(
            total_bytes=total_len,
            detected_opcodes=candidates,
            estimated_endian=endian,
        )

    @classmethod
    def synthesize_vm(cls, report: ArcheologyReport) -> ScriptVM:
        """
        Synthesize a working ScriptVM instance from the archeology report.
        """
        vm = ScriptVM(opcode_size=1, endian=report.estimated_endian)
        for idx, op in enumerate(report.detected_opcodes):
            name = f"OP_{op.code:02X}"
            vm.register(op.code, name, op.inferred_args)
        return vm
