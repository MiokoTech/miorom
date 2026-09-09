"""
miorom.script.repacker
~~~~~~~~~~~~~~~~~~~~~~
Smart Script Event Unpacker & Repacker with Arbitrary Text Expansion.
Deconstructs mixed opcode/dialogue event scripts into symbolic labeled units,
allows arbitrary string lengthening (no length restrictions), and performs
two-pass re-assembly with automatic jump target recalculation and external
pointer table rewriting.
"""

from miorom.result import MioRomResult
from dataclasses import dataclass, field
import struct
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union

from miorom.script.engine import BytecodeEngine, DisassembledScript, Instruction
from miorom.text.po_handler import PoHandler, PoEntry


@dataclass
class ScriptRepackReport(MioRomResult):
    """Report on script repacking and text expansion."""
    original_size: int
    new_size: int
    size_delta: int
    total_strings_updated: int
    labels_relocated: int
    external_pointers_updated: Dict[int, int] = field(default_factory=dict)

    @property
    def expansion_summary(self) -> str:
        sign = "+" if self.size_delta >= 0 else ""
        return (
            f"Script size: {self.original_size} -> {self.new_size} bytes "
            f"({sign}{self.size_delta} bytes). "
            f"Updated {self.total_strings_updated} strings, "
            f"{self.labels_relocated} branch labels, "
            f"{len(self.external_pointers_updated)} external entry pointers."
        )


class SmartScriptRepacker:
    """
    High-level orchestrator for unpacking event scripts to editable translations
    and repacking with zero boundary or jump-target corruption.
    """

    def __init__(self, engine: BytecodeEngine):
        self.engine = engine

    def unpack_to_po(
        self,
        script_data: bytes,
        start_offset: int = 0,
        end_offset: Optional[int] = None,
        external_entry_points: Optional[List[int]] = None,
    ) -> Tuple[DisassembledScript, PoHandler]:
        """
        Unpacks a binary script into a symbolic DisassembledScript and creates a PO catalog
        for all dialogue strings embedded in instruction arguments.
        """
        script = self.engine.disassemble(
            data=script_data,
            start_offset=start_offset,
            end_offset=end_offset,
        )

        # Mark external entry points as labels if present
        if external_entry_points:
            for ep in external_entry_points:
                lbl = f"ENTRY_{ep:04X}"
                for ins in script.instructions:
                    if ins.offset == ep and not ins.label:
                        ins.label = lbl
                        script.labels[ep] = lbl

        po_handler = PoHandler()
        extracted_strings = script.extract_strings()

        for idx, (ins_off, arg_name, text) in enumerate(extracted_strings):
            po_handler.add_entry(
                msgid=text,
                msgstr="",
                msgctxt=f"str_{idx:04d}",
                comment=f"Offset: 0x{ins_off:04X}, Arg: {arg_name}",
            )

        return script, po_handler

    def repack_with_translations(
        self,
        script: DisassembledScript,
        po_source: Union[PoHandler, Dict[str, str], Dict[Tuple[int, str], str]],
        external_entry_points: Optional[List[int]] = None,
    ) -> Tuple[bytes, ScriptRepackReport]:
        """
        Inserts translations (which can be arbitrarily long), re-calculates all branch
        offsets and external pointers, and emits the new compiled script bytecode.
        """
        # Map translations to instructions
        # Compute original size before updating strings
        orig_sz = 0
        for ins in script.instructions:
            if ins.opcode_id in self.engine.opcodes_by_id:
                defn = self.engine.opcodes_by_id[ins.opcode_id]
                size = 1
                for a in defn.args:
                    val = ins.args.get(a.name, 0)
                    if isinstance(val, str) and (val.startswith("LABEL_") or val.startswith("ENTRY_")):
                        val = 0
                    size += len(a.pack(val, self.engine.endian))
                orig_sz += size
            else:
                orig_sz += 1

        strings_updated = 0
        extracted = script.extract_strings()

        if isinstance(po_source, PoHandler):
            # Key by index or text
            for idx, entry in enumerate(po_source.entries):
                if entry.msgstr:
                    if idx < len(extracted):
                        ins_off, arg_name, _ = extracted[idx]
                        for ins in script.instructions:
                            if ins.offset == ins_off and arg_name in ins.args:
                                ins.args[arg_name] = entry.msgstr
                                strings_updated += 1
                                break
        elif isinstance(po_source, dict):
            for k, v in po_source.items():
                if isinstance(k, tuple) and len(k) == 2:
                    ins_off, arg_name = k
                    for ins in script.instructions:
                        if ins.offset == ins_off and arg_name in ins.args:
                            ins.args[arg_name] = v
                            strings_updated += 1
                elif isinstance(k, str):
                    # Keyed by msgid
                    for ins in script.instructions:
                        for a_name, val in ins.args.items():
                            if val == k:
                                ins.args[a_name] = v
                                strings_updated += 1

        # Track external entry labels
        ep_labels: Dict[int, str] = {}
        if external_entry_points:
            for ep in external_entry_points:
                ep_lbl = f"ENTRY_{ep:04X}"
                ep_labels[ep] = ep_lbl
                for ins in script.instructions:
                    if ins.offset == ep:
                        ins.label = ep_lbl
                        break

        # Pass 1: Measure new instruction lengths and record updated label offsets
        new_label_offsets: Dict[str, int] = {}
        curr_offset = 0

        for ins in script.instructions:
            if ins.label:
                new_label_offsets[ins.label] = curr_offset
            new_label_offsets[f"LABEL_{ins.offset:04X}"] = curr_offset

            if ins.opcode_id in self.engine.opcodes_by_id:
                defn = self.engine.opcodes_by_id[ins.opcode_id]
                size = 1  # Opcode byte
                for arg in defn.args:
                    val = ins.args.get(arg.name, 0)
                    if isinstance(val, str) and (val.startswith("LABEL_") or val.startswith("ENTRY_")):
                        val = 0  # Placeholder integer for sizing
                    size += len(arg.pack(val, self.engine.endian))
                curr_offset += size
            else:
                curr_offset += 1

        # Pass 2: Emit binary bytecode with resolved labels
        out = bytearray()
        for ins in script.instructions:
            if ins.opcode_id not in self.engine.opcodes_by_id:
                out.append(ins.opcode_id)
                continue

            defn = self.engine.opcodes_by_id[ins.opcode_id]
            out.append(ins.opcode_id)

            for arg in defn.args:
                val = ins.args.get(arg.name, 0)
                if isinstance(val, str):
                    if val in new_label_offsets:
                        val = new_label_offsets[val]
                    elif val.startswith("LABEL_"):
                        val = int(val[6:], 16)
                out.extend(arg.pack(val, self.engine.endian))

        # Calculate updated external pointers
        updated_external_pointers: Dict[int, int] = {}
        for old_ep, ep_lbl in ep_labels.items():
            if ep_lbl in new_label_offsets:
                updated_external_pointers[old_ep] = new_label_offsets[ep_lbl]

        report = ScriptRepackReport(
            original_size=orig_sz,
            new_size=len(out),
            size_delta=len(out) - orig_sz,
            total_strings_updated=strings_updated,
            labels_relocated=len(new_label_offsets),
            external_pointers_updated=updated_external_pointers,
        )

        return bytes(out), report
