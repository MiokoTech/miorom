"""
miorom.script.script_dissector
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Event Script Bytecode Disassembler, Inline Dialogue Extractor, and Jump Splicer.

Disassembles compiled bytecode streams (SNES, GBA, PS1, Genesis RPGs),
extracts inline dialogue payloads using custom CharMaps, and safely splices
expanded translated text with unified automatic branch and jump table recalculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter

from miorom.errors import ParseError
from miorom.result import MioRomResult
from miorom.text.charmap import CharMap
from miorom.text.po_handler import PoEntry, PoHandler


# ============================================================================
# Opcode Types and Data Models
# ============================================================================

class VMOpcodeType(Enum):
    """Classification of VM bytecode instructions."""
    TEXT = "text"              # Inline text dialogue payload
    BRANCH_REL = "branch_rel"  # Relative jump (signed delta offset)
    BRANCH_ABS = "branch_abs"  # Absolute jump (pointer/target address)
    SWITCH = "switch"          # Multi-case jump table
    CONTROL = "control"        # General control / state modification
    TERMINATOR = "terminator"  # Script termination (e.g. OP_END / OP_RETURN)


@dataclass
class VMInstructionDef(MioRomResult):
    """
    Schema definition for a bytecode VM instruction.
    """
    opcode: int
    name: str
    opcode_type: VMOpcodeType
    fixed_length: int = 1         # Length of opcode + fixed operands (excluding variable text)
    operand_format: str = ""      # Struct format for operands, e.g. '<H', '<h', '<b'
    text_terminator: Optional[bytes] = b"\x00"  # For TEXT type: delimiter marking end of string
    has_length_prefix: bool = False             # If True, first byte after opcode is text length


@dataclass
class DissectedInstruction(MioRomResult):
    """
    A disassembled VM instruction instance with location and decoded operands.
    """
    index: int
    offset: int
    length: int
    opcode: int
    definition: VMInstructionDef
    raw_bytes: bytes
    text_payload: Optional[str] = None
    raw_text_bytes: Optional[bytes] = None
    branch_target: Optional[int] = None       # Absolute target address in bytecode
    relative_delta: Optional[int] = None      # Raw signed delta from instruction
    operand_offset: Optional[int] = None      # Absolute offset where the jump operand is stored
    switch_targets: List[int] = field(default_factory=list)

    @property
    def offset_hex(self) -> str:
        return f"0x{self.offset:08X}"


@dataclass
class DissectedScriptVM(MioRomResult):
    """
    A fully disassembled event script containing instructions and branch maps.
    """
    base_offset: int
    instructions: List[DissectedInstruction]
    total_bytes: int

    def get_dialogues(self) -> List[Tuple[int, str]]:
        """
        Returns list of (instruction_index, text_payload) for all dialogue instructions.
        """
        return [
            (inst.index, inst.text_payload)
            for inst in self.instructions
            if inst.text_payload is not None
        ]

    def to_po(self) -> str:
        """
        Exports all extracted dialogues to a standard GNU gettext PO catalog.
        """
        handler = PoHandler()
        for inst in self.instructions:
            if inst.text_payload is not None:
                handler.add_entry(
                    msgid=inst.text_payload,
                    msgstr="",
                    msgctxt=f"inst_{inst.index}",
                    reference=f"offset_{inst.offset_hex}",
                )
        return handler.to_string()


# ============================================================================
# Disassembler and Splicer Engine
# ============================================================================

class ScriptVMDissector:
    """
    Event Script Bytecode Disassembler, Inline Dialogue Extractor, and Jump Splicer.
    """

    @classmethod
    def disassemble(
        cls,
        data: bytes,
        start_offset: int = 0,
        opcode_table: Optional[Dict[int, VMInstructionDef]] = None,
        charmap: Optional[CharMap] = None,
        max_bytes: int = 65536,
    ) -> DissectedScriptVM:
        """
        Disassembles a bytecode event script into structured instructions.

        Args:
            data: Binary ROM or script buffer.
            start_offset: Starting byte offset of the script.
            opcode_table: Mapping of opcode byte to VMInstructionDef schema.
            charmap: Optional CharMap for decoding dialogue text payloads.
            max_bytes: Safety limit on script byte size.
        """
        if opcode_table is None:
            raise ValueError("opcode_table is required to disassemble VM bytecode")

        instructions: List[DissectedInstruction] = []
        pos = start_offset
        end_limit = min(len(data), start_offset + max_bytes)
        inst_index = 0

        while pos < end_limit:
            inst_start = pos
            opcode = data[pos]
            pos += 1

            defn = opcode_table.get(opcode)
            if defn is None:
                # Fallback to single-byte generic control instruction
                defn = VMInstructionDef(
                    opcode=opcode,
                    name=f"UNKNOWN_{opcode:02X}",
                    opcode_type=VMOpcodeType.CONTROL,
                    fixed_length=1,
                )

            text_payload: Optional[str] = None
            raw_text_bytes: Optional[bytes] = None
            branch_target: Optional[int] = None
            relative_delta: Optional[int] = None
            operand_offset: Optional[int] = None
            switch_targets: List[int] = []

            # 1. TEXT instruction
            if defn.opcode_type == VMOpcodeType.TEXT:
                if defn.has_length_prefix:
                    if pos >= end_limit:
                        break
                    text_len = data[pos]
                    pos += 1
                    raw_text_bytes = data[pos : pos + text_len]
                    pos += text_len
                else:
                    # Delimiter-terminated string
                    term = defn.text_terminator or b"\x00"
                    t_len = len(term)
                    str_start = pos
                    while pos <= end_limit - t_len:
                        if data[pos : pos + t_len] == term:
                            break
                        pos += 1
                    raw_text_bytes = data[str_start:pos]
                    pos += t_len  # consume terminator

                if charmap is not None:
                    text_payload = charmap.decode(raw_text_bytes)
                else:
                    text_payload = raw_text_bytes.decode("utf-8", errors="replace")

            # 2. RELATIVE BRANCH instruction
            elif defn.opcode_type == VMOpcodeType.BRANCH_REL:
                operand_offset = pos
                fmt = defn.operand_format or "<h"
                op_size = BinaryReader.calcsize(fmt)
                if pos + op_size <= end_limit:
                    relative_delta = BinaryReader.unpack_from(fmt, data, pos)[0]
                    pos += op_size
                    # Target is relative to instruction start or operand position
                    branch_target = inst_start + relative_delta

            # 3. ABSOLUTE JUMP instruction
            elif defn.opcode_type == VMOpcodeType.BRANCH_ABS:
                operand_offset = pos
                fmt = defn.operand_format or "<H"
                op_size = BinaryReader.calcsize(fmt)
                if pos + op_size <= end_limit:
                    branch_target = BinaryReader.unpack_from(fmt, data, pos)[0]
                    pos += op_size

            # 4. SWITCH / JUMP TABLE instruction
            elif defn.opcode_type == VMOpcodeType.SWITCH:
                # First byte is case count
                if pos < end_limit:
                    case_count = data[pos]
                    pos += 1
                    fmt = defn.operand_format or "<H"
                    op_size = BinaryReader.calcsize(fmt)
                    for _ in range(case_count):
                        if pos + op_size <= end_limit:
                            tgt = BinaryReader.unpack_from(fmt, data, pos)[0]
                            switch_targets.append(tgt)
                            pos += op_size

            # 5. CONTROL or TERMINATOR instruction
            else:
                extra_len = defn.fixed_length - 1
                if extra_len > 0 and pos + extra_len <= end_limit:
                    pos += extra_len

            inst_length = pos - inst_start
            raw_bytes = data[inst_start:pos]

            instructions.append(
                DissectedInstruction(
                    index=inst_index,
                    offset=inst_start,
                    length=inst_length,
                    opcode=opcode,
                    definition=defn,
                    raw_bytes=raw_bytes,
                    text_payload=text_payload,
                    raw_text_bytes=raw_text_bytes,
                    branch_target=branch_target,
                    relative_delta=relative_delta,
                    operand_offset=operand_offset,
                    switch_targets=switch_targets,
                )
            )
            inst_index += 1

            # Stop condition on terminal instruction
            if defn.opcode_type == VMOpcodeType.TERMINATOR:
                break

        total_bytes = pos - start_offset
        return DissectedScriptVM(
            base_offset=start_offset,
            instructions=instructions,
            total_bytes=total_bytes,
        )

    @classmethod
    def splice_and_relink(
        cls,
        bytecode: Union[bytes, bytearray],
        script: DissectedScriptVM,
        translations: Dict[int, str],
        charmap: Optional[CharMap] = None,
        opcode_table: Optional[Dict[int, VMInstructionDef]] = None,
    ) -> bytearray:
        """
        Replaces text payloads for specified instructions, automatically shifts
        all subsequent bytecode, and recalculates all relative and absolute branches.

        Args:
            bytecode: Original bytecode buffer.
            script: Disassembled DissectedScriptVM instance.
            translations: Mapping of instruction_index -> new translated text string.
            charmap: CharMap used to encode new text strings.
            opcode_table: Opcode schemas.
        """
        # 1. Determine replacement bytes for each modified instruction
        replacements: Dict[int, bytes] = {}
        for inst_idx, new_text in translations.items():
            if inst_idx < 0 or inst_idx >= len(script.instructions):
                continue
            inst = script.instructions[inst_idx]
            if inst.definition.opcode_type != VMOpcodeType.TEXT:
                continue

            # Encode text
            if charmap is not None:
                encoded_text = charmap.encode(new_text)
            else:
                encoded_text = new_text.encode("utf-8")

            # Assemble replacement instruction bytes
            out_inst = bytearray([inst.opcode])
            if inst.definition.has_length_prefix:
                out_inst.append(len(encoded_text))
                out_inst.extend(encoded_text)
            else:
                out_inst.extend(encoded_text)
                out_inst.extend(inst.definition.text_terminator or b"\x00")

            replacements[inst_idx] = bytes(out_inst)

        # 2. Build cumulative offset shift map
        # Track (orig_start, delta) for each replaced instruction
        shifts: List[Tuple[int, int]] = []
        for inst_idx, new_bytes in sorted(replacements.items()):
            inst = script.instructions[inst_idx]
            delta = len(new_bytes) - inst.length
            # The shift occurs immediately after the end of this instruction
            shifts.append((inst.offset + inst.length, delta))

        def map_offset(orig_offset: int) -> int:
            """Maps an original bytecode offset to its new position."""
            cum_shift = 0
            for shift_pos, delta in shifts:
                if orig_offset >= shift_pos:
                    cum_shift += delta
            return orig_offset + cum_shift

        # 3. Assemble new bytecode stream with replaced text
        new_buf = bytearray()
        prev_orig_pos = script.base_offset

        for inst in script.instructions:
            if inst.index in replacements:
                # Copy preceding unchanged bytes
                new_buf.extend(bytecode[prev_orig_pos : inst.offset])
                # Insert replacement instruction
                new_buf.extend(replacements[inst.index])
                prev_orig_pos = inst.offset + inst.length

        # Append trailing unchanged bytes of the script
        script_end = script.base_offset + script.total_bytes
        new_buf.extend(bytecode[prev_orig_pos:script_end])

        # 4. Recalculate and patch all branch operands in new_buf
        for inst in script.instructions:
            defn = inst.definition
            new_inst_offset = map_offset(inst.offset)

            # A. Relative branch recalculation
            if defn.opcode_type == VMOpcodeType.BRANCH_REL and inst.branch_target is not None:
                new_target = map_offset(inst.branch_target)
                new_delta = new_target - new_inst_offset
                fmt = defn.operand_format or "<h"

                # Relative operand position in new buffer
                op_pos = new_inst_offset + 1  # 1 byte opcode
                BinaryWriter.pack_into(fmt, new_buf, op_pos, new_delta)

            # B. Absolute jump recalculation
            elif defn.opcode_type == VMOpcodeType.BRANCH_ABS and inst.branch_target is not None:
                new_target = map_offset(inst.branch_target)
                fmt = defn.operand_format or "<H"
                op_pos = new_inst_offset + 1
                BinaryWriter.pack_into(fmt, new_buf, op_pos, new_target)

            # C. Switch / Jump table recalculation
            elif defn.opcode_type == VMOpcodeType.SWITCH and inst.switch_targets:
                fmt = defn.operand_format or "<H"
                op_size = BinaryReader.calcsize(fmt)
                # Offset past opcode + case_count
                curr_op_pos = new_inst_offset + 2
                for old_target in inst.switch_targets:
                    new_target = map_offset(old_target)
                    BinaryWriter.pack_into(fmt, new_buf, curr_op_pos, new_target)
                    curr_op_pos += op_size

        return new_buf
