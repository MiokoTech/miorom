import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from miorom.asm.disasm import UniversalDisassembler
from miorom.script.lifter import BinaryLifter


@dataclass
class FunctionFingerprint:
    address: int
    name: str
    block_count: int
    edge_count: int
    cyclomatic_complexity: int
    instruction_count: int
    call_targets: List[int] = field(default_factory=list)
    mnemonic_histogram: Dict[str, int] = field(default_factory=dict)


@dataclass
class FunctionMatch:
    func_a_address: int
    func_b_address: int
    similarity: float
    match_type: str  # "Exact", "Isomorphic", "Heuristic"
    details: str = ""

    def summary(self) -> str:
        return (
            f"0x{self.func_a_address:08X} <-> 0x{self.func_b_address:08X} "
            f"[{self.match_type}] Similarity: {self.similarity * 100:.1f}% ({self.details})"
        )


@dataclass
class BinDiffReport:
    total_funcs_a: int
    total_funcs_b: int
    matches: List[FunctionMatch] = field(default_factory=list)
    unmatched_a: List[int] = field(default_factory=list)
    unmatched_b: List[int] = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        if self.total_funcs_a == 0:
            return 0.0
        return len(self.matches) / self.total_funcs_a

    def summary(self) -> str:
        lines = [
            "==================================================",
            "        BinDiff CFG Isomorphism Report           ",
            "==================================================",
            f"  Binary A Functions : {self.total_funcs_a}",
            f"  Binary B Functions : {self.total_funcs_b}",
            f"  Matched Functions  : {len(self.matches)} ({self.match_rate * 100:.1f}%)",
            f"  Unmatched A        : {len(self.unmatched_a)}",
            f"  Unmatched B        : {len(self.unmatched_b)}",
        ]
        if self.matches:
            lines.append("  Top Function Matches:")
            for m in self.matches[:10]:
                lines.append(f"    - {m.summary()}")
            if len(self.matches) > 10:
                lines.append(f"    ... and {len(self.matches) - 10} more matches.")
        lines.append("==================================================")
        return "\n".join(lines)


class BinDiffEngine:
    """
    Control Flow Graph (CFG) Isomorphism and Function Similarity Diffing Engine.
    Matches corresponding functions across different game versions or regions.
    """

    @classmethod
    def fingerprint_function(
        cls,
        data: bytes,
        func_address: int,
        base_address: int,
        arch: str = "ppc",
        max_bytes: int = 1024,
    ) -> FunctionFingerprint:
        off = func_address - base_address
        chunk = data[off : off + max_bytes]
        ir_func = BinaryLifter.lift(chunk, base_address=func_address, arch=arch)

        v_count = len(ir_func.blocks)
        e_count = sum(len(b.successors) for b in ir_func.blocks.values())
        # Cyclomatic complexity = E - V + 2
        cyclo = max(1, e_count - v_count + 2)

        inst_count = sum(len(b.instructions) for b in ir_func.blocks.values())
        hist: Dict[str, int] = Counter()
        call_targets: List[int] = []

        for b in ir_func.blocks.values():
            for ins in b.instructions:
                hist[ins.op.value] += 1
                if ins.op.value == "CALL" and ins.args and isinstance(ins.args[0], int):
                    call_targets.append(ins.args[0])

        return FunctionFingerprint(
            address=func_address,
            name=ir_func.name,
            block_count=v_count,
            edge_count=e_count,
            cyclomatic_complexity=cyclo,
            instruction_count=inst_count,
            call_targets=call_targets,
            mnemonic_histogram=dict(hist),
        )

    @classmethod
    def compare_fingerprints(
        cls,
        f1: FunctionFingerprint,
        f2: FunctionFingerprint,
    ) -> float:
        """
        Calculates similarity score (0.0 to 1.0) between two function fingerprints
        using CFG graph topology and opcode histogram cosine similarity.
        """
        # 1. Exact match
        if (
            f1.block_count == f2.block_count
            and f1.edge_count == f2.edge_count
            and f1.instruction_count == f2.instruction_count
            and f1.mnemonic_histogram == f2.mnemonic_histogram
        ):
            return 1.0

        # 2. Graph topology score
        max_b = max(f1.block_count, f2.block_count, 1)
        b_sim = 1.0 - (abs(f1.block_count - f2.block_count) / max_b)

        max_e = max(f1.edge_count, f2.edge_count, 1)
        e_sim = 1.0 - (abs(f1.edge_count - f2.edge_count) / max_e)

        max_c = max(f1.cyclomatic_complexity, f2.cyclomatic_complexity, 1)
        c_sim = 1.0 - (abs(f1.cyclomatic_complexity - f2.cyclomatic_complexity) / max_c)

        topo_score = (b_sim + e_sim + c_sim) / 3.0

        # 3. Mnemonic histogram cosine similarity
        all_ops = set(f1.mnemonic_histogram.keys()) | set(f2.mnemonic_histogram.keys())
        dot = sum(f1.mnemonic_histogram.get(op, 0) * f2.mnemonic_histogram.get(op, 0) for op in all_ops)
        norm1 = math.sqrt(sum(v * v for v in f1.mnemonic_histogram.values()))
        norm2 = math.sqrt(sum(v * v for v in f2.mnemonic_histogram.values()))

        hist_sim = (dot / (norm1 * norm2)) if (norm1 > 0 and norm2 > 0) else 0.0

        # Weighted final score (40% topology, 60% opcode distribution)
        return (topo_score * 0.4) + (hist_sim * 0.6)

    @classmethod
    def diff_binaries(
        cls,
        data_a: bytes,
        base_a: int,
        funcs_a: List[int],
        data_b: bytes,
        base_b: int,
        funcs_b: List[int],
        arch: str = "ppc",
        threshold: float = 0.75,
    ) -> BinDiffReport:
        fps_a = [cls.fingerprint_function(data_a, fa, base_a, arch=arch) for fa in funcs_a]
        fps_b = [cls.fingerprint_function(data_b, fb, base_b, arch=arch) for fb in funcs_b]

        matches: List[FunctionMatch] = []
        matched_b_addrs: Set[int] = set()

        for fa in fps_a:
            best_score = 0.0
            best_fb: Optional[FunctionFingerprint] = None

            for fb in fps_b:
                if fb.address in matched_b_addrs:
                    continue
                score = cls.compare_fingerprints(fa, fb)
                if score > best_score:
                    best_score = score
                    best_fb = fb

            if best_fb and best_score >= threshold:
                mtype = "Exact" if best_score >= 0.999 else ("Isomorphic" if best_score >= 0.9 else "Heuristic")
                matches.append(
                    FunctionMatch(
                        func_a_address=fa.address,
                        func_b_address=best_fb.address,
                        similarity=best_score,
                        match_type=mtype,
                        details=f"{fa.block_count} blocks, {fa.instruction_count} instrs",
                    )
                )
                matched_b_addrs.add(best_fb.address)

        matched_a_addrs = {m.func_a_address for m in matches}
        unmatched_a = [fa.address for fa in fps_a if fa.address not in matched_a_addrs]
        unmatched_b = [fb.address for fb in fps_b if fb.address not in matched_b_addrs]

        return BinDiffReport(
            total_funcs_a=len(funcs_a),
            total_funcs_b=len(funcs_b),
            matches=matches,
            unmatched_a=unmatched_a,
            unmatched_b=unmatched_b,
        )
