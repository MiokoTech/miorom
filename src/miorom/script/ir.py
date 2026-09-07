from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Union


class IROp(Enum):
    ASSIGN = "ASSIGN"
    ADD = "ADD"
    SUB = "SUB"
    MUL = "MUL"
    DIV = "DIV"
    AND = "AND"
    OR = "OR"
    XOR = "XOR"
    SHL = "SHL"
    SHR = "SHR"
    LOAD = "LOAD"
    STORE = "STORE"
    CALL = "CALL"
    RETURN = "RETURN"
    BRANCH = "BRANCH"
    BRANCH_COND = "BRANCH_COND"
    PHI = "PHI"
    NOP = "NOP"


@dataclass
class IRVar:
    name: str
    version: int = 0
    var_type: str = "int"

    @property
    def ssa_name(self) -> str:
        return f"{self.name}_{self.version}" if self.version > 0 else self.name

    def __repr__(self) -> str:
        return self.ssa_name


@dataclass
class IRInstruction:
    op: IROp
    dst: Optional[Union[IRVar, str]] = None
    args: List[Union[IRVar, str, int]] = field(default_factory=list)
    pc: Optional[int] = None
    comment: Optional[str] = None

    def to_string(self) -> str:
        dst_str = f"{self.dst} = " if self.dst else ""
        args_str = ", ".join(str(a) for a in self.args)
        comment_str = f"  // {self.comment}" if self.comment else ""
        return f"{dst_str}{self.op.value}({args_str}){comment_str}"

    def __repr__(self) -> str:
        return self.to_string()


@dataclass
class IRBlock:
    label: str
    address: int
    instructions: List[IRInstruction] = field(default_factory=list)
    predecessors: List[str] = field(default_factory=list)
    successors: List[str] = field(default_factory=list)

    def add_instruction(self, ins: IRInstruction):
        self.instructions.append(ins)


@dataclass
class IRFunction:
    name: str
    entry_address: int
    blocks: Dict[str, IRBlock] = field(default_factory=dict)
    parameters: List[IRVar] = field(default_factory=list)
    return_var: Optional[IRVar] = None

    def add_block(self, block: IRBlock):
        self.blocks[block.label] = block
