"""
miorom.asm.xref
~~~~~~~~~~~~~~~
Bidirectional Cross-Reference (XREF) and Function Call Graph Engine.
Traces literal pools, split-immediate loads (MIPS lui/addiu, PPC lis/addi),
direct branches, and pointer references to uncover which code routines access
specific text lines, graphics, or script blocks.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
from enum import Enum
import struct
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction


class XRefType(Enum):
    DATA_POINTER = "data_pointer"        # Raw 32-bit address in pointer table or rodata
    LITERAL_POOL = "literal_pool"        # LDR Rn, [PC, #offset]
    SPLIT_IMMEDIATE = "split_immediate"  # MIPS lui+addiu, PPC lis+addi, ARM movw+movt
    CALL = "call"                        # BL, JAL, etc.
    BRANCH = "branch"                    # B, J, etc.
    READ = "read"                        # Data load
    WRITE = "write"                      # Data store


@dataclass
class XRef(MioRomResult):
    """Represents a single cross-reference link."""
    source_address: int                  # Code or data address where reference originates
    target_address: int                  # Destination address being referenced
    xref_type: XRefType
    instruction_text: str = ""
    source_function: Optional[int] = None

    def __repr__(self) -> str:
        return (
            f"<XRef 0x{self.source_address:08X} -> 0x{self.target_address:08X} "
            f"({self.xref_type.value}) {self.instruction_text}>"
        )


@dataclass
class CallerGraph(MioRomResult):
    """Call graph structure representing caller/callee relationships."""
    functions: Set[int] = field(default_factory=set)
    callers_of: Dict[int, Set[int]] = field(default_factory=dict)
    callees_of: Dict[int, Set[int]] = field(default_factory=dict)

    def add_call(self, caller: int, callee: int):
        self.functions.add(caller)
        self.functions.add(callee)
        self.callers_of.setdefault(callee, set()).add(caller)
        self.callees_of.setdefault(caller, set()).add(callee)

    def to_mermaid(self) -> str:
        """Generates GitHub/Markdown compatible Mermaid flowchart diagram."""
        lines = ["graph TD"]
        for caller, targets in self.callees_of.items():
            for callee in sorted(targets):
                lines.append(f'    fn_{caller:08X}["sub_{caller:08X}"] --> fn_{callee:08X}["sub_{callee:08X}"]')
        return "\n".join(lines)


class GlobalXrefEngine:
    """
    Scans binary images for multi-architecture cross-references and builds callgraphs.
    """

    @classmethod
    def scan_literal_pools_arm(
        cls,
        data: bytes,
        base_address: int,
        endian: str = "<",
    ) -> List[XRef]:
        """
        Scans ARM32 code for LDR Rn, [PC, #imm] literal pool constant references.
        """
        xrefs: List[XRef] = []
        n_words = len(data) // 4
        for i in range(n_words):
            word = struct.unpack_from(f"{endian}I", data, i * 4)[0]
            # LDR Rd, [PC, #+/-imm12]: bits 27..20 = 0101x001 (0x051 or 0x059) and Rn = 15 (PC)
            # cond: 31..28, 010: 27..25, I: 24=0, P: 23, U: 22, B: 21=0, W: 20=0, Rn: 19..16=15 (0xF)
            cond = (word >> 28) & 0xF
            is_ldr_pc = ((word & 0x0E5F0000) == 0x041F0000) or ((word & 0x0E5F0000) == 0x059F0000)

            if is_ldr_pc and cond != 0xF:
                pc_val = (base_address + i * 4) + 8
                u_bit = (word >> 23) & 1
                imm12 = word & 0xFFF
                pool_addr = (pc_val + imm12) if u_bit else (pc_val - imm12)

                pool_off = pool_addr - base_address
                if 0 <= pool_off <= len(data) - 4:
                    target_addr = struct.unpack_from(f"{endian}I", data, pool_off)[0]
                    xrefs.append(
                        XRef(
                            source_address=base_address + i * 4,
                            target_address=target_addr,
                            xref_type=XRefType.LITERAL_POOL,
                            instruction_text=f"LDR R{(word>>12)&0xF}, [PC, #{'+' if u_bit else '-'}{imm12}]",
                        )
                    )
        return xrefs

    @classmethod
    def scan_split_immediates_mips(
        cls,
        data: bytes,
        base_address: int,
        endian: str = ">",
    ) -> List[XRef]:
        """
        Scans MIPS code for LUI Rt, imm + ADDIU/ORI Rt, Rt, imm 32-bit address loads.
        """
        xrefs: List[XRef] = []
        n_words = len(data) // 4
        for i in range(n_words - 1):
            w1 = struct.unpack_from(f"{endian}I", data, i * 4)[0]
            w2 = struct.unpack_from(f"{endian}I", data, (i + 1) * 4)[0]

            # LUI Rt, imm16 (opcode 001111 = 0x0F)
            op1 = (w1 >> 26) & 0x3F
            if op1 == 0x0F:
                rt1 = (w1 >> 16) & 0x1F
                imm_hi = w1 & 0xFFFF

                # Next instruction: ADDIU Rt, Rs, imm (op 001001 = 0x09) or ORI (op 001101 = 0x0D)
                op2 = (w2 >> 26) & 0x3F
                rs2 = (w2 >> 21) & 0x1F
                rt2 = (w2 >> 16) & 0x1F
                imm_lo = w2 & 0xFFFF

                if (op2 in (0x09, 0x0D)) and (rs2 == rt1):
                    if op2 == 0x09 and (imm_lo & 0x8000):  # Sign extended addiu
                        full_addr = ((imm_hi << 16) + (imm_lo - 0x10000)) & 0xFFFFFFFF
                    else:
                        full_addr = (imm_hi << 16) | imm_lo

                    xrefs.append(
                        XRef(
                            source_address=base_address + i * 4,
                            target_address=full_addr,
                            xref_type=XRefType.SPLIT_IMMEDIATE,
                            instruction_text=f"LUI+ADDIU/ORI R{rt1}, 0x{full_addr:08X}",
                        )
                    )
        return xrefs

    @classmethod
    def scan_all_xrefs(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "arm",
        endian: str = "<",
    ) -> Dict[int, List[XRef]]:
        """
        Produces a complete mapping of target_address -> List[XRef].
        """
        all_xrefs: List[XRef] = []
        arch_norm = arch.lower()

        if "arm" in arch_norm:
            all_xrefs.extend(cls.scan_literal_pools_arm(data, base_address, endian=endian))
        elif "mips" in arch_norm:
            all_xrefs.extend(cls.scan_split_immediates_mips(data, base_address, endian=endian))

        # Also scan 4-byte aligned pointers within pointer tables
        fmt = f"{endian}I"
        data_len = len(data)
        for off in range(0, data_len - 3, 4):
            val = struct.unpack_from(fmt, data, off)[0]
            if base_address <= val < base_address + data_len:
                all_xrefs.append(
                    XRef(
                        source_address=base_address + off,
                        target_address=val,
                        xref_type=XRefType.DATA_POINTER,
                        instruction_text=f".dword 0x{val:08X}",
                    )
                )

        target_map: Dict[int, List[XRef]] = {}
        for x in all_xrefs:
            target_map.setdefault(x.target_address, []).append(x)

        return target_map

    @classmethod
    def build_call_graph(
        cls,
        data: bytes,
        base_address: int,
        arch: str = "arm",
        endian: str = "<",
    ) -> CallerGraph:
        """
        Scans call/branch instructions across binary to construct a full caller/callee graph.
        """
        graph = CallerGraph()
        step = 2 if arch.lower() == "thumb" else 4
        cur_func = base_address

        for off in range(0, len(data) - step + 1, step):
            addr = base_address + off
            try:
                ins = UniversalDisassembler.disassemble_instruction(
                    address=addr,
                    raw_bytes=data[off : off + step],
                    arch=arch,
                    endian=endian,
                )
                if ins.is_return:
                    cur_func = addr + step
                elif ins.is_call and ins.target_address:
                    graph.add_call(caller=cur_func, callee=ins.target_address)
            except Exception:
                continue

        return graph
