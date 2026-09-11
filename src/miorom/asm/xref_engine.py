"""
miorom.asm.xref_engine
~~~~~~~~~~~~~~~~~~~~~~
Symbolic Cross-Reference (XREF) and Code/Data Flow Analysis Engine.
Extracts inbound and outbound references across multiple CPU architectures
(ARM, Thumb, PowerPC, MIPS, W65C816/MOS6502) and pointer tables, builds
bidirectional reference databases, and annotates disassembly with IDA/Ghidra style
`; CODE XREF:` and `; DATA XREF:` comments.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

from miorom.result import MioRomResult
from miorom.asm.disasm import UniversalDisassembler, DisasmInstruction
from miorom.asm.xref import XRef, XRefType, CallerGraph


class XRefDirection(Enum):
    TO = "to"        # Inbound references targeting this address (who calls/reads this?)
    FROM = "from"    # Outbound references originating at this address (what does this call/read?)


@dataclass
class XRefRecord(MioRomResult):
    """Rich cross-reference descriptor with instruction metadata."""
    source_address: int
    target_address: int
    xref_type: XRefType
    instruction_text: str = ""
    source_symbol: Optional[str] = None
    target_symbol: Optional[str] = None
    comment: str = ""

    def to_xref(self) -> XRef:
        return XRef(
            source_address=self.source_address,
            target_address=self.target_address,
            xref_type=self.xref_type,
            instruction_text=self.instruction_text,
        )


class XRefDatabase(MioRomResult):
    """
    Bidirectional index of binary code and data cross-references.
    Supports querying inbound (xrefs_to) and outbound (xrefs_from) references,
    call graph extraction, and disassembly annotation.
    """

    def __init__(self):
        self._to_map: Dict[int, List[XRefRecord]] = {}
        self._from_map: Dict[int, List[XRefRecord]] = {}
        self._symbols: Dict[int, str] = {}

    def add_symbol(self, address: int, name: str) -> None:
        self._symbols[address] = name

    def set_symbols(self, symbols: Dict[int, str]) -> None:
        self._symbols.update(symbols)

    def get_symbol(self, address: int) -> Optional[str]:
        return self._symbols.get(address)

    def add_xref(
        self,
        source_address: int,
        target_address: int,
        xref_type: XRefType,
        instruction_text: str = "",
        comment: str = "",
    ) -> XRefRecord:
        record = XRefRecord(
            source_address=source_address,
            target_address=target_address,
            xref_type=xref_type,
            instruction_text=instruction_text,
            source_symbol=self._symbols.get(source_address),
            target_symbol=self._symbols.get(target_address),
            comment=comment,
        )
        self._to_map.setdefault(target_address, []).append(record)
        self._from_map.setdefault(source_address, []).append(record)
        return record

    def xrefs_to(
        self,
        target_address: int,
        xref_type: Optional[XRefType] = None,
    ) -> List[XRefRecord]:
        """Returns all inbound references pointing to target_address."""
        refs = self._to_map.get(target_address, [])
        if xref_type is not None:
            return [r for r in refs if r.xref_type == xref_type]
        return list(refs)

    def xrefs_from(
        self,
        source_address: int,
        xref_type: Optional[XRefType] = None,
    ) -> List[XRefRecord]:
        """Returns all outbound references originating from source_address."""
        refs = self._from_map.get(source_address, [])
        if xref_type is not None:
            return [r for r in refs if r.xref_type == xref_type]
        return list(refs)

    @property
    def all_targets(self) -> Set[int]:
        return set(self._to_map.keys())

    @property
    def all_sources(self) -> Set[int]:
        return set(self._from_map.keys())

    @property
    def total_count(self) -> int:
        return sum(len(refs) for refs in self._from_map.values())

    def callers_of(self, function_address: int) -> List[int]:
        """Returns unique caller addresses that execute a call instruction to function_address."""
        call_refs = self.xrefs_to(function_address, xref_type=XRefType.CALL)
        return sorted({r.source_address for r in call_refs})

    def callees_of(self, function_address: int, function_length: Optional[int] = None) -> List[int]:
        """Returns unique function targets called within function_address range."""
        callees: Set[int] = set()
        if function_length is None:
            # Check single instruction
            for ref in self.xrefs_from(function_address, xref_type=XRefType.CALL):
                callees.add(ref.target_address)
        else:
            end_addr = function_address + function_length
            for src, refs in self._from_map.items():
                if function_address <= src < end_addr:
                    for r in refs:
                        if r.xref_type == XRefType.CALL:
                            callees.add(r.target_address)
        return sorted(callees)

    def build_call_graph(self) -> CallerGraph:
        """Constructs a CallerGraph from all CALL type xrefs."""
        graph = CallerGraph()
        for target, records in self._to_map.items():
            for rec in records:
                if rec.xref_type == XRefType.CALL:
                    graph.add_call(caller=rec.source_address, callee=target)
        return graph

    def format_xrefs_header(self, address: int, max_items: int = 5) -> List[str]:
        """
        Produces IDA / Ghidra style comment lines summarizing inbound references.
        Example:
            ; CODE XREF: sub_02001000+14↑j, sub_02001400+8↑p (2 calls)
            ; DATA XREF: dword_02045A10↓o
        """
        inbound = self.xrefs_to(address)
        if not inbound:
            return []

        lines: List[str] = []
        code_refs = [r for r in inbound if r.xref_type in (XRefType.CALL, XRefType.BRANCH)]
        data_refs = [
            r for r in inbound
            if r.xref_type in (XRefType.DATA_POINTER, XRefType.LITERAL_POOL, XRefType.SPLIT_IMMEDIATE, XRefType.READ, XRefType.WRITE)
        ]

        if code_refs:
            ref_strs = []
            for r in code_refs[:max_items]:
                sym = self._symbols.get(r.source_address, f"0x{r.source_address:08X}")
                arrow = "↑" if r.source_address < address else "↓"
                kind = "p" if r.xref_type == XRefType.CALL else "j"
                ref_strs.append(f"{sym}{arrow}{kind}")
            suffix = f" ... ({len(code_refs)} refs)" if len(code_refs) > max_items else ""
            lines.append(f"; CODE XREF: {', '.join(ref_strs)}{suffix}")

        if data_refs:
            ref_strs = []
            for r in data_refs[:max_items]:
                sym = self._symbols.get(r.source_address, f"0x{r.source_address:08X}")
                arrow = "↑" if r.source_address < address else "↓"
                ref_strs.append(f"{sym}{arrow}o")
            suffix = f" ... ({len(data_refs)} refs)" if len(data_refs) > max_items else ""
            lines.append(f"; DATA XREF: {', '.join(ref_strs)}{suffix}")

        return lines

    def annotate_disassembly(
        self,
        instructions: Iterable[DisasmInstruction],
        show_function_headers: bool = True,
    ) -> List[str]:
        """
        Generates annotated disassembly text with symbol headers and XREF comments.
        """
        output: List[str] = []
        for ins in instructions:
            addr = ins.address
            # Inbound xrefs header
            xref_lines = self.format_xrefs_header(addr)
            if xref_lines and show_function_headers:
                sym_name = self._symbols.get(addr)
                output.append("; " + "-" * 75)
                if sym_name:
                    output.append(f"; Function: {sym_name}")
                for xl in xref_lines:
                    output.append(xl)
                output.append("; " + "-" * 75)

            # Instruction string
            line = ins.to_string(symbols=self._symbols)

            # Append outbound xref annotation if available
            outbound = self.xrefs_from(addr)
            if outbound and not ins.comment:
                out_strs = []
                for o in outbound:
                    target_sym = self._symbols.get(o.target_address)
                    if target_sym:
                        out_strs.append(f"-> {target_sym} (0x{o.target_address:08X})")
                    else:
                        out_strs.append(f"-> 0x{o.target_address:08X}")
                if out_strs:
                    line += f"  ; {'; '.join(out_strs)}"

            output.append(line)
        return output

    def export_ida_map(self, module_name: str = "miorom_export") -> str:
        """
        Exports the symbol table and cross-references in standard IDA Pro .map file format.
        """
        lines = [
            f" {module_name}",
            "",
            "  Address         Publics by Value",
            "",
        ]
        for addr in sorted(self._symbols.keys()):
            name = self._symbols[addr]
            lines.append(f" 0001:{addr:08X}       {name}")

        lines.append("")
        lines.append("  Cross References")
        lines.append("")
        for target in sorted(self._to_map.keys()):
            target_sym = self._symbols.get(target, f"0x{target:08X}")
            for rec in self._to_map[target]:
                src_sym = self._symbols.get(rec.source_address, f"0x{rec.source_address:08X}")
                lines.append(f" {src_sym} -> {target_sym} [{rec.xref_type.value}]")

        return "\n".join(lines) + "\n"

    def export_ghidra_xml(self, program_name: str = "miorom_binary") -> str:
        """
        Exports symbols and cross-references in Ghidra Program XML format.
        Compatible with Ghidra's XML import facility.
        """
        from xml.sax.saxutils import escape

        xml_lines = [
            '<?xml version="1.0" standalone="yes"?>',
            '<!DOCTYPE PROGRAM SYSTEM "ghidra.dtd">',
            f'<PROGRAM NAME="{escape(program_name)}">',
            '  <SYMBOL_TABLE>',
        ]

        for addr, name in sorted(self._symbols.items()):
            xml_lines.append(
                f'    <SYMBOL ADDRESS="0x{addr:08X}" NAME="{escape(name)}" '
                f'TYPE="{"code" if addr in self._to_map else "data"}" />'
            )

        xml_lines.append('  </SYMBOL_TABLE>')
        xml_lines.append('  <XREFS>')

        for src, records in sorted(self._from_map.items()):
            for rec in records:
                xml_lines.append(
                    f'    <XREF FROM="0x{rec.source_address:08X}" '
                    f'TO="0x{rec.target_address:08X}" '
                    f'TYPE="{escape(rec.xref_type.value)}" />'
                )

        xml_lines.append('  </XREFS>')
        xml_lines.append('</PROGRAM>')
        return "\n".join(xml_lines) + "\n"


class SymbolicXrefEngine:
    """
    Cross-architecture static analyzer and symbolic cross-reference discovery engine.
    Supports ARM, Thumb, PowerPC, MIPS, W65C816, MOS 6502, and data pointer tables.
    """

    @classmethod
    def analyze(
        cls,
        data: bytes,
        base_address: int = 0,
        arch: str = "arm",
        endian: str = "<",
        symbols: Optional[Dict[int, str]] = None,
        scan_pointers: bool = True,
    ) -> XRefDatabase:
        """
        Performs a full cross-reference analysis of code and pointer structures.
        """
        db = XRefDatabase()
        if symbols:
            db.set_symbols(symbols)

        arch_norm = arch.lower().strip()

        if arch_norm in ("arm", "arm32"):
            cls._scan_arm(data, base_address, endian, db)
        elif arch_norm in ("thumb", "thumb16"):
            cls._scan_thumb(data, base_address, endian, db)
        elif arch_norm in ("ppc", "powerpc"):
            cls._scan_ppc(data, base_address, endian, db)
        elif arch_norm in ("mips", "mips32"):
            cls._scan_mips(data, base_address, endian, db)
        elif arch_norm in ("snes", "w65c816", "65816"):
            cls._scan_snes(data, base_address, db)
        elif arch_norm in ("nes", "mos6502", "6502"):
            cls._scan_mos6502(data, base_address, db)

        if scan_pointers:
            cls._scan_pointer_tables(data, base_address, endian, db)

        return db

    @classmethod
    def _scan_arm(cls, data: bytes, base: int, endian: str, db: XRefDatabase) -> None:
        n_words = len(data) // 4
        fmt = f"{endian}I"
        for i in range(n_words):
            word = struct.unpack_from(fmt, data, i * 4)[0]
            curr_addr = base + i * 4
            cond = (word >> 28) & 0xF

            # ARM literal pool load: LDR Rd, [PC, #+/-imm12]
            is_ldr_pc = ((word & 0x0E5F0000) == 0x041F0000) or ((word & 0x0E5F0000) == 0x059F0000)
            if is_ldr_pc and cond != 0xF:
                pc_val = curr_addr + 8
                u_bit = (word >> 23) & 1
                imm12 = word & 0xFFF
                pool_addr = (pc_val + imm12) if u_bit else (pc_val - imm12)
                pool_off = pool_addr - base
                if 0 <= pool_off <= len(data) - 4:
                    target_val = struct.unpack_from(fmt, data, pool_off)[0]
                    rd = (word >> 12) & 0xF
                    db.add_xref(
                        source_address=curr_addr,
                        target_address=target_val,
                        xref_type=XRefType.LITERAL_POOL,
                        instruction_text=f"LDR R{rd}, [PC, #{'+' if u_bit else '-'}{imm12}]",
                    )

            # ARM branch and link (B, BL, BLX)
            # B / BL: bits 27..25 = 101, bit 24 = link
            if (word & 0x0E000000) == 0x0A000000 and cond != 0xF:
                is_link = bool(word & 0x01000000)
                imm24 = word & 0x00FFFFFF
                # Sign extend 24-bit to 32-bit signed
                if imm24 & 0x00800000:
                    imm24 -= 0x01000000
                target_addr = (curr_addr + 8 + (imm24 << 2)) & 0xFFFFFFFF
                db.add_xref(
                    source_address=curr_addr,
                    target_address=target_addr,
                    xref_type=XRefType.CALL if is_link else XRefType.BRANCH,
                    instruction_text="BL" if is_link else "B",
                )

    @classmethod
    def _scan_thumb(cls, data: bytes, base: int, endian: str, db: XRefDatabase) -> None:
        n_halfwords = len(data) // 2
        fmt = f"{endian}H"
        i = 0
        while i < n_halfwords:
            hw = struct.unpack_from(fmt, data, i * 2)[0]
            curr_addr = base + i * 2

            # Thumb literal pool load: LDR Rd, [PC, #imm8]
            if (hw & 0xF800) == 0x4800:
                rd = (hw >> 8) & 0x7
                imm8 = (hw & 0xFF) * 4
                pc_val = (curr_addr + 4) & ~2
                target_ptr = pc_val + imm8
                off = target_ptr - base
                if 0 <= off <= len(data) - 4:
                    val = struct.unpack_from(f"{endian}I", data, off)[0]
                    db.add_xref(
                        source_address=curr_addr,
                        target_address=val,
                        xref_type=XRefType.LITERAL_POOL,
                        instruction_text=f"LDR R{rd}, [PC, #{imm8}]",
                    )

            # Thumb branch and link (BL)
            # High half: 11110xxxxxxxxxxx (0xF000)
            # Low half:  11111xxxxxxxxxxx (0xF800)
            if (hw & 0xF800) == 0xF000 and i + 1 < n_halfwords:
                hw2 = struct.unpack_from(fmt, data, (i + 1) * 2)[0]
                if (hw2 & 0xF800) == 0xF800:
                    imm11_h = hw & 0x7FF
                    if imm11_h & 0x400:
                        imm11_h -= 0x800
                    imm11_l = hw2 & 0x7FF
                    offset = (imm11_h << 12) + (imm11_l << 1)
                    target_addr = (curr_addr + 4 + offset) & 0xFFFFFFFF
                    db.add_xref(
                        source_address=curr_addr,
                        target_address=target_addr,
                        xref_type=XRefType.CALL,
                        instruction_text="BL",
                    )
                    i += 2
                    continue

            # Thumb unconditional branch (B)
            if (hw & 0xF800) == 0xE000:
                imm11 = hw & 0x7FF
                if imm11 & 0x400:
                    imm11 -= 0x800
                target_addr = (curr_addr + 4 + (imm11 << 1)) & 0xFFFFFFFF
                db.add_xref(
                    source_address=curr_addr,
                    target_address=target_addr,
                    xref_type=XRefType.BRANCH,
                    instruction_text="B",
                )

            # Thumb conditional branch (B<cond>)
            if (hw & 0xF000) == 0xD000 and ((hw >> 8) & 0xF) < 0xE:
                imm8 = hw & 0xFF
                if imm8 & 0x80:
                    imm8 -= 0x100
                target_addr = (curr_addr + 4 + (imm8 << 1)) & 0xFFFFFFFF
                db.add_xref(
                    source_address=curr_addr,
                    target_address=target_addr,
                    xref_type=XRefType.BRANCH,
                    instruction_text="B<cond>",
                )

            i += 1

    @classmethod
    def _scan_ppc(cls, data: bytes, base: int, endian: str, db: XRefDatabase) -> None:
        n_words = len(data) // 4
        fmt = f"{endian}I"
        for i in range(n_words):
            word = struct.unpack_from(fmt, data, i * 4)[0]
            curr_addr = base + i * 4
            op = (word >> 26) & 0x3F

            # PowerPC branch instructions
            if op == 18:
                li = word & 0x03FFFFFC
                if li & 0x02000000:
                    li -= 0x04000000
                aa = bool(word & 2)
                lk = bool(word & 1)
                target = (li if aa else (curr_addr + li)) & 0xFFFFFFFF
                db.add_xref(
                    source_address=curr_addr,
                    target_address=target,
                    xref_type=XRefType.CALL if lk else XRefType.BRANCH,
                    instruction_text="BL" if lk else "B",
                )

            # PowerPC split immediate (lis + addi/ori)
            if op == 15:  # ADDIS / LIS (RA=0)
                ra = (word >> 16) & 0x1F
                rd = (word >> 21) & 0x1F
                if ra == 0 and i + 1 < n_words:
                    imm_hi = word & 0xFFFF
                    next_word = struct.unpack_from(fmt, data, (i + 1) * 4)[0]
                    next_op = (next_word >> 26) & 0x3F
                    next_rd = (next_word >> 21) & 0x1F
                    next_ra = (next_word >> 16) & 0x1F
                    imm_lo = next_word & 0xFFFF

                    # ADDI (opcode 14) or ORI (opcode 24)
                    if (next_op in (14, 24)) and (next_ra == rd):
                        if next_op == 14 and (imm_lo & 0x8000):  # sign extended
                            full_addr = ((imm_hi << 16) + (imm_lo - 0x10000)) & 0xFFFFFFFF
                        else:
                            full_addr = ((imm_hi << 16) | imm_lo) & 0xFFFFFFFF
                        db.add_xref(
                            source_address=curr_addr,
                            target_address=full_addr,
                            xref_type=XRefType.SPLIT_IMMEDIATE,
                            instruction_text=f"LIS+{'ADDI' if next_op==14 else 'ORI'} r{rd}, 0x{full_addr:08X}",
                        )

    @classmethod
    def _scan_mips(cls, data: bytes, base: int, endian: str, db: XRefDatabase) -> None:
        n_words = len(data) // 4
        fmt = f"{endian}I"
        for i in range(n_words):
            word = struct.unpack_from(fmt, data, i * 4)[0]
            curr_addr = base + i * 4
            op = (word >> 26) & 0x3F

            # MIPS jump instructions (j, jal)
            if op in (2, 3):
                target_idx = word & 0x03FFFFFF
                pc_hi = (curr_addr + 4) & 0xF0000000
                target_addr = pc_hi | (target_idx << 2)
                is_call = (op == 3)
                db.add_xref(
                    source_address=curr_addr,
                    target_address=target_addr,
                    xref_type=XRefType.CALL if is_call else XRefType.BRANCH,
                    instruction_text="JAL" if is_call else "J",
                )

            # MIPS split immediate (lui + addiu/ori)
            if op == 0x0F and i + 1 < n_words:
                rt1 = (word >> 16) & 0x1F
                imm_hi = word & 0xFFFF
                w2 = struct.unpack_from(fmt, data, (i + 1) * 4)[0]
                op2 = (w2 >> 26) & 0x3F
                rs2 = (w2 >> 21) & 0x1F
                imm_lo = w2 & 0xFFFF
                if (op2 in (0x09, 0x0D)) and (rs2 == rt1):
                    if op2 == 0x09 and (imm_lo & 0x8000):
                        full_addr = ((imm_hi << 16) + (imm_lo - 0x10000)) & 0xFFFFFFFF
                    else:
                        full_addr = (imm_hi << 16) | imm_lo
                    db.add_xref(
                        source_address=curr_addr,
                        target_address=full_addr,
                        xref_type=XRefType.SPLIT_IMMEDIATE,
                        instruction_text=f"LUI+{'ADDIU' if op2==0x09 else 'ORI'} R{rt1}, 0x{full_addr:08X}",
                    )

    @classmethod
    def _scan_snes(cls, data: bytes, base: int, db: XRefDatabase) -> None:
        """Scans W65C816 16-bit / 24-bit jumps and calls."""
        length = len(data)
        off = 0
        while off < length:
            op = data[off]
            curr_addr = base + off

            # JSR abs: 0x20 (3 bytes)
            if op == 0x20 and off + 2 < length:
                addr = data[off + 1] | (data[off + 2] << 8)
                bank = (curr_addr >> 16) & 0xFF
                full = (bank << 16) | addr
                db.add_xref(curr_addr, full, XRefType.CALL, f"JSR ${addr:04X}")
                off += 3
                continue

            # JSL long: 0x22 (4 bytes)
            if op == 0x22 and off + 3 < length:
                full = data[off + 1] | (data[off + 2] << 8) | (data[off + 3] << 16)
                db.add_xref(curr_addr, full, XRefType.CALL, f"JSL ${full:06X}")
                off += 4
                continue

            # JMP abs: 0x4C (3 bytes)
            if op == 0x4C and off + 2 < length:
                addr = data[off + 1] | (data[off + 2] << 8)
                bank = (curr_addr >> 16) & 0xFF
                full = (bank << 16) | addr
                db.add_xref(curr_addr, full, XRefType.BRANCH, f"JMP ${addr:04X}")
                off += 3
                continue

            # JML long: 0x5C (4 bytes)
            if op == 0x5C and off + 3 < length:
                full = data[off + 1] | (data[off + 2] << 8) | (data[off + 3] << 16)
                db.add_xref(curr_addr, full, XRefType.BRANCH, f"JML ${full:06X}")
                off += 4
                continue

            # BRA rel8: 0x80 (2 bytes)
            if op == 0x80 and off + 1 < length:
                rel = data[off + 1]
                if rel & 0x80:
                    rel -= 0x100
                target = (curr_addr + 2 + rel) & 0xFFFFFF
                db.add_xref(curr_addr, target, XRefType.BRANCH, "BRA")
                off += 2
                continue

            off += 1

    @classmethod
    def _scan_mos6502(cls, data: bytes, base: int, db: XRefDatabase) -> None:
        """Scans NES / MOS 6502 instructions."""
        length = len(data)
        off = 0
        while off < length:
            op = data[off]
            curr_addr = base + off

            # JSR abs: 0x20 (3 bytes)
            if op == 0x20 and off + 2 < length:
                target = data[off + 1] | (data[off + 2] << 8)
                db.add_xref(curr_addr, target, XRefType.CALL, f"JSR ${target:04X}")
                off += 3
                continue

            # JMP abs: 0x4C (3 bytes)
            if op == 0x4C and off + 2 < length:
                target = data[off + 1] | (data[off + 2] << 8)
                db.add_xref(curr_addr, target, XRefType.BRANCH, f"JMP ${target:04X}")
                off += 3
                continue

            off += 1

    @classmethod
    def _scan_pointer_tables(
        cls,
        data: bytes,
        base: int,
        endian: str,
        db: XRefDatabase,
    ) -> None:
        """Detects 32-bit aligned data pointers that reference internal addresses."""
        fmt = f"{endian}I"
        data_len = len(data)
        limit = base + data_len
        for off in range(0, data_len - 3, 4):
            val = struct.unpack_from(fmt, data, off)[0]
            if base <= val < limit and val != 0:
                curr_addr = base + off
                # Avoid self-references
                if curr_addr != val:
                    db.add_xref(
                        source_address=curr_addr,
                        target_address=val,
                        xref_type=XRefType.DATA_POINTER,
                        instruction_text=f".dword 0x{val:08X}",
                    )
