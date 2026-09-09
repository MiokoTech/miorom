"""
miorom.naming
~~~~~~~~~~~~~
Rule-based function auto-naming from IR analysis signals.
Every rule is explicit, auditable code — no AI/ML. Users can add/remove rules.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass
from typing import Callable, List, Optional

from miorom.script.ir import IRFunction, IROp


@dataclass
class NamingRule(MioRomResult):
    """A single naming heuristic rule."""
    prefix: str
    predicate: Callable[[IRFunction], bool]
    description: str


class FunctionNamer:
    """
    Applies registered naming rules to IRFunction instances.
    Rules are evaluated in order; first match wins (unless force=True).

    Built-in rules:
        checksum_ — function calls routines with "crc"/"checksum" in name or
                    performs XOR/shift-heavy arithmetic typical of CRC.
        util_     — function has no CALL instructions (pure arithmetic).
        func_     — default fallback (same as BinaryLifter sub_ prefix).
    """

    def __init__(self, rules: Optional[List[NamingRule]] = None):
        self.rules = rules or [
            NamingRule(
                prefix="checksum_",
                predicate=self._is_checksum_routine,
                description="Calls CRC/checksum routines or performs XOR-heavy arithmetic",
            ),
            NamingRule(
                prefix="util_",
                predicate=self._is_pure_utility,
                description="No external calls, pure arithmetic/logic",
            ),
        ]

    @staticmethod
    def _is_checksum_routine(func: IRFunction) -> bool:
        """Detect XOR-shift loops or calls to named checksum functions."""
        xor_count = sum(
            1 for block in func.blocks.values() for ins in block.instructions if ins.op == IROp.XOR
        )
        shl_count = sum(
            1 for block in func.blocks.values() for ins in block.instructions if ins.op == IROp.SHL
        )
        call_names = [
            str(ins.args[0]) for block in func.blocks.values() for ins in block.instructions
            if ins.op == IROp.CALL and ins.args
        ]
        for name in call_names:
            lower = name.lower()
            if "crc" in lower or "checksum" in lower or "hash" in lower:
                return True
        return xor_count >= 4 and shl_count >= 2

    @staticmethod
    def _is_pure_utility(func: IRFunction) -> bool:
        """No CALL instructions at all."""
        return not any(
            ins.op == IROp.CALL for block in func.blocks.values() for ins in block.instructions
        )

    def name_function(self, func: IRFunction, current_name: str) -> str:
        """Return the best-guess name for a function based on registered rules."""
        for rule in self.rules:
            if rule.predicate(func):
                if not current_name.startswith(f"sub_"):
                    return current_name
                return f"{rule.prefix}{current_name[4:]}"
        return current_name

    def add_rule(self, rule: NamingRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, prefix: str) -> None:
        self.rules = [r for r in self.rules if r.prefix != prefix]
