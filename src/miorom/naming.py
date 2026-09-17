"""
miorom.naming
~~~~~~~~~~~~~
Rule-based function auto-naming from IR analysis signals.
Every rule is explicit, auditable code — no AI/ML. Users can add/remove rules.
"""

from dataclasses import dataclass
from typing import Any, Callable, List, Optional

from miorom.result import MioRomResult
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

    def __init__(
        self,
        rules: Optional[List[NamingRule]] = None,
        symbol_map: Optional[Any] = None,
        symbol_resolver: Optional[Callable[[int], Optional[str]]] = None,
    ):
        self.symbol_map = symbol_map
        self.symbol_resolver = symbol_resolver
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

    def _is_checksum_routine(self, func: IRFunction) -> bool:
        """Detect XOR-shift loops or calls to named checksum functions."""
        xor_count = sum(
            1 for block in func.blocks.values() for ins in block.instructions if ins.op == IROp.XOR
        )
        shl_count = sum(
            1 for block in func.blocks.values() for ins in block.instructions if ins.op == IROp.SHL
        )
        call_names = [
            self._resolve_call_target_name(ins.args[0])
            for block in func.blocks.values()
            for ins in block.instructions
            if ins.op == IROp.CALL and ins.args
        ]
        for name in call_names:
            if name is None:
                continue
            lower = name.lower()
            if "crc" in lower or "checksum" in lower or "hash" in lower:
                return True
        return xor_count >= 4 and shl_count >= 2

    def _resolve_call_target_name(self, target: object) -> Optional[str]:
        if isinstance(target, str):
            return target
        if not isinstance(target, int):
            return None

        if self.symbol_resolver is not None:
            resolved = self.symbol_resolver(target)
            if resolved is not None:
                return str(resolved)

        if self.symbol_map is None:
            return None

        resolve = getattr(self.symbol_map, "resolve", None)
        if not callable(resolve):
            return None

        symbol = resolve(target)
        if symbol is None:
            return None
        return str(getattr(symbol, "name", symbol))

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
                if not current_name.startswith("sub_"):
                    return current_name
                return f"{rule.prefix}{current_name[4:]}"
        return current_name

    def add_rule(self, rule: NamingRule) -> None:
        self.rules.append(rule)

    def remove_rule(self, prefix: str) -> None:
        self.rules = [r for r in self.rules if r.prefix != prefix]
