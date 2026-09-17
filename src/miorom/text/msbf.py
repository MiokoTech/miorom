"""
miorom.text.msbf
~~~~~~~~~~~~~~~~
Nintendo MSBF (Message Studio Binary Flow) Dialogue Flowchart Engine.
Standard companion format to MSBT (.msbt) used across Nintendo Wii, NDS (late), 3DS,
and Switch titles (e.g., The Legend of Zelda: Skyward Sword, Super Mario Galaxy 2,
Animal Crossing: City Folk, The Legend of Zelda: Twilight Princess HD).

Features:
- Pure-Python, zero external dependencies.
- Strict declarative binary primitives via miorom.core.schema.BinaryStruct.
- High-level directed node graph model (MessageNode, ChoiceNode, EventNode).
- Bidirectional MSBT linking: resolves message indices to MSBT string labels and text previews.
- Visual storytelling flowchart generation via Mermaid Markdown (flowchart TD).
- JSON/dictionary import and export for automated translation scripts and modding pipelines.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

from miorom.core.schema import (
    U8,
    U16,
    U32,
    BinaryStruct,
    Padding,
    RawBytes,
)
from miorom.errors import ParseError
from miorom.result import MioRomResult
from miorom.text.msbt import MSBTFile

# ==============================================================================
# Constants & Magics
# ==============================================================================

MSBF_MAGIC = b"MsgFlwBn"

SECTION_FLW3 = b"FLW3"
SECTION_FEN1 = b"FEN1"
SECTION_FOP1 = b"FOP1"

NODE_TYPE_MESSAGE = 1
NODE_TYPE_CHOICE = 2
NODE_TYPE_EVENT = 3
NODE_TYPE_ENTRY = 4


# ==============================================================================
# Declarative Low-Level Binary Structures (schema.BinaryStruct)
# ==============================================================================

class MSBFHeaderStruct(BinaryStruct):
    """
    Root 32-byte header of a Nintendo MSBF flow container.
    """
    magic = RawBytes(8, default=MSBF_MAGIC)
    bom = RawBytes(2, default=b"\xFE\xFF")
    _pad1 = Padding(2)
    encoding = U8(default=1)                # 0 = UTF-8, 1 = UTF-16
    version = U8(default=3)
    section_count = U16(default=3)
    _pad2 = Padding(2)
    file_size = U32(default=0)
    _pad3 = Padding(10)


class MSBFSectionHeaderStruct(BinaryStruct):
    """
    16-byte header prepending every MSBF section (FLW3, FEN1, FOP1).
    """
    magic = RawBytes(4)
    size = U32(default=0)
    _reserved = Padding(8)


class FLW3HeaderStruct(BinaryStruct):
    """
    Header of the FLW3 flow node pool section.
    """
    node_count = U16(default=0)
    branch_count = U16(default=0)
    _pad = Padding(4)


class FLW3NodeStruct(BinaryStruct):
    """
    Individual 16-byte flow node descriptor within the FLW3 section.
    """
    node_type = U16(default=1)              # 1=Message, 2=Choice/Branch, 3=Event
    param1 = U16(default=0)                 # Sub-type / param
    next_node_index = U16(default=0xFFFF)   # Next node index or branch table start index
    param2 = U16(default=0)                 # Number of branch choices (for ChoiceNode)
    item_id = U32(default=0)                # MSBT text index or Event ID
    _extra = RawBytes(4, default=b"\x00" * 4)


# ==============================================================================
# High-Level Analytical Node Graph Models
# ==============================================================================

@dataclass
class FlowNode(MioRomResult):
    """Base class for all flowchart nodes."""
    node_id: int
    node_type: int


@dataclass
class MessageNode(FlowNode):
    """
    Dialogue text step referencing an MSBT text entry.
    """
    message_index: int = 0
    next_node_id: Optional[int] = None
    msbt_label: str = ""
    text_preview: str = ""

    def __init__(
        self,
        node_id: int,
        message_index: int = 0,
        next_node_id: Optional[int] = None,
        msbt_label: str = "",
        text_preview: str = "",
    ):
        super().__init__(node_id=node_id, node_type=NODE_TYPE_MESSAGE)
        self.message_index = message_index
        self.next_node_id = next_node_id
        self.msbt_label = msbt_label
        self.text_preview = text_preview


@dataclass
class ChoiceNode(FlowNode):
    """
    Interactive decision point presenting branching options to the player.
    """
    options: List[str] = None
    branch_targets: List[int] = None

    def __init__(
        self,
        node_id: int,
        options: Optional[List[str]] = None,
        branch_targets: Optional[List[int]] = None,
    ):
        super().__init__(node_id=node_id, node_type=NODE_TYPE_CHOICE)
        self.options = list(options or [])
        self.branch_targets = list(branch_targets or [])


@dataclass
class EventNode(FlowNode):
    """
    Script action or story event trigger (e.g. give item, set flag, play cutscene).
    """
    event_id: int = 0
    param: int = 0
    next_node_id: Optional[int] = None

    def __init__(
        self,
        node_id: int,
        event_id: int = 0,
        param: int = 0,
        next_node_id: Optional[int] = None,
    ):
        super().__init__(node_id=node_id, node_type=NODE_TYPE_EVENT)
        self.event_id = event_id
        self.param = param
        self.next_node_id = next_node_id


# ==============================================================================
# High-Level MSBF File & Flowchart Engine
# ==============================================================================

class MSBFFile:
    """
    Nintendo MSBF (Message Studio Binary Flow) Dialogue Flowchart Engine.
    Manages conversational branching graphs, interactive choices, MSBT synchronization,
    and visual Mermaid graph rendering.
    """

    MAGIC = MSBF_MAGIC

    def __init__(
        self,
        nodes: Optional[Dict[int, FlowNode]] = None,
        entries: Optional[Dict[str, int]] = None,
        encoding: str = "utf-16",
        endian: str = ">",
    ):
        self.nodes: Dict[int, FlowNode] = dict(nodes or {})
        self.entries: Dict[str, int] = dict(entries or {})
        self.encoding = encoding.lower()
        self.endian = endian

    @classmethod
    def from_bytes(cls, data: bytes) -> MSBFFile:
        """
        Parses an MSBF binary file into an analytical flowchart node graph.
        """
        if len(data) < MSBFHeaderStruct.sizeof():
            raise ParseError(f"Data too short for MSBF header ({len(data)} < {MSBFHeaderStruct.sizeof()} bytes)")

        # Read endian from BOM
        bom_raw = data[8:10]
        endian = ">" if bom_raw == b"\xFE\xFF" else "<"

        header = MSBFHeaderStruct.from_bytes(data, offset=0, endian=endian)
        if header.magic != MSBF_MAGIC:
            raise ParseError(f"Invalid MSBF magic: {header.magic!r} (expected {MSBF_MAGIC!r})")

        encoding = "utf-8" if header.encoding == 0 else "utf-16"

        pos = MSBFHeaderStruct.sizeof()
        raw_nodes: List[FLW3NodeStruct] = []
        raw_branches: List[int] = []
        entry_points: Dict[str, int] = {}
        option_strings: List[str] = []

        # Parse sections
        while pos + MSBFSectionHeaderStruct.sizeof() <= len(data):
            sec_hdr = MSBFSectionHeaderStruct.from_bytes(data, offset=pos, endian=endian)
            sec_start = pos + MSBFSectionHeaderStruct.sizeof()
            sec_end = sec_start + sec_hdr.size
            sec_data = data[sec_start:sec_end]

            if sec_hdr.magic == SECTION_FLW3:
                if len(sec_data) >= FLW3HeaderStruct.sizeof():
                    flw_hdr = FLW3HeaderStruct.from_bytes(sec_data, offset=0, endian=endian)
                    cur_node_off = FLW3HeaderStruct.sizeof()

                    # Read nodes
                    for _ in range(flw_hdr.node_count):
                        if cur_node_off + FLW3NodeStruct.sizeof() <= len(sec_data):
                            node_st = FLW3NodeStruct.from_bytes(sec_data, offset=cur_node_off, endian=endian)
                            raw_nodes.append(node_st)
                            cur_node_off += FLW3NodeStruct.sizeof()

                    # Read branch table
                    branch_bytes = sec_data[cur_node_off:]
                    count = len(branch_bytes) // 2
                    for b_idx in range(count):
                        target = int.from_bytes(branch_bytes[b_idx * 2 : b_idx * 2 + 2], "big" if endian == ">" else "little")
                        raw_branches.append(target)

            elif sec_hdr.magic == SECTION_FEN1:
                # Flow Entry points table (hash table bucket format similar to LBL1)
                if len(sec_data) >= 4:
                    num_slots = int.from_bytes(sec_data[0:4], "big" if endian == ">" else "little")
                    slot_array_off = 4
                    # Read bucket descriptors: count(4), offset(4)
                    for s in range(num_slots):
                        desc_off = slot_array_off + s * 8
                        if desc_off + 8 <= len(sec_data):
                            e_cnt = int.from_bytes(sec_data[desc_off : desc_off + 4], "big" if endian == ">" else "little")
                            e_off = int.from_bytes(sec_data[desc_off + 4 : desc_off + 8], "big" if endian == ">" else "little")
                            cur_e = e_off
                            for _ in range(e_cnt):
                                if cur_e + 1 <= len(sec_data):
                                    str_len = sec_data[cur_e]
                                    cur_e += 1
                                    if cur_e + str_len + 2 <= len(sec_data):
                                        label = sec_data[cur_e : cur_e + str_len].decode("ascii", errors="replace")
                                        cur_e += str_len
                                        root_node_idx = int.from_bytes(sec_data[cur_e : cur_e + 2], "big" if endian == ">" else "little")
                                        cur_e += 2
                                        entry_points[label] = root_node_idx

            elif sec_hdr.magic == SECTION_FOP1:
                # Option strings table
                if len(sec_data) >= 4:
                    opt_count = int.from_bytes(sec_data[0:4], "big" if endian == ">" else "little")
                    cur_p = 4
                    codec = ("utf-16-be" if endian == ">" else "utf-16-le") if encoding == "utf-16" else "utf-8"
                    for _ in range(opt_count):
                        if cur_p >= len(sec_data):
                            break
                        if encoding == "utf-16":
                            end_str = cur_p
                            while end_str + 1 < len(sec_data) and sec_data[end_str : end_str + 2] != b"\x00\x00":
                                end_str += 2
                            if end_str + 1 < len(sec_data):
                                opt_text = sec_data[cur_p:end_str].decode(codec, errors="replace")
                                option_strings.append(opt_text)
                                cur_p = end_str + 2
                            else:
                                opt_text = sec_data[cur_p:].decode(codec, errors="replace")
                                option_strings.append(opt_text)
                                break
                        else:
                            end_str = sec_data.find(b"\x00", cur_p)
                            if end_str != -1:
                                opt_text = sec_data[cur_p:end_str].decode("utf-8", errors="replace")
                                option_strings.append(opt_text)
                                cur_p = end_str + 1
                            else:
                                opt_text = sec_data[cur_p:].decode("utf-8", errors="replace")
                                option_strings.append(opt_text)
                                break

            # 16-byte alignment
            pad = (16 - (sec_hdr.size % 16)) % 16
            pos += MSBFSectionHeaderStruct.sizeof() + sec_hdr.size + pad

        # Reconstruct High-Level FlowNode Graph
        nodes_dict: Dict[int, FlowNode] = {}
        opt_cursor = 0
        for i, raw_n in enumerate(raw_nodes):
            if raw_n.node_type == NODE_TYPE_MESSAGE:
                next_id = raw_n.next_node_index if raw_n.next_node_index != 0xFFFF else None
                nodes_dict[i] = MessageNode(
                    node_id=i,
                    message_index=raw_n.item_id,
                    next_node_id=next_id,
                )
            elif raw_n.node_type == NODE_TYPE_CHOICE:
                branch_start = raw_n.next_node_index
                branch_count = raw_n.param2
                targets = raw_branches[branch_start : branch_start + branch_count] if branch_start < len(raw_branches) else []
                opt_start = raw_n.param1 if raw_n.param1 + branch_count <= len(option_strings) else opt_cursor
                if opt_start + branch_count <= len(option_strings):
                    opts = option_strings[opt_start : opt_start + branch_count]
                    opt_cursor = max(opt_cursor, opt_start + branch_count)
                elif opt_cursor + branch_count <= len(option_strings):
                    opts = option_strings[opt_cursor : opt_cursor + branch_count]
                    opt_cursor += branch_count
                else:
                    opts = [f"Option {o}" for o in range(branch_count)]
                nodes_dict[i] = ChoiceNode(
                    node_id=i,
                    options=opts,
                    branch_targets=targets,
                )
            elif raw_n.node_type == NODE_TYPE_EVENT:
                next_id = raw_n.next_node_index if raw_n.next_node_index != 0xFFFF else None
                nodes_dict[i] = EventNode(
                    node_id=i,
                    event_id=raw_n.item_id,
                    param=raw_n.param1,
                    next_node_id=next_id,
                )
            else:
                next_id = raw_n.next_node_index if raw_n.next_node_index != 0xFFFF else None
                nodes_dict[i] = FlowNode(node_id=i, node_type=raw_n.node_type)

        return cls(
            nodes=nodes_dict,
            entries=entry_points,
            encoding=encoding,
            endian=endian,
        )

    @classmethod
    def from_file(cls, filepath: Union[str, os.PathLike]) -> MSBFFile:
        """
        Loads and parses an MSBF file from the filesystem.
        """
        with open(filepath, "rb") as f:
            return cls.from_bytes(f.read())

    def link_msbt(self, msbt: MSBTFile) -> None:
        """
        Links this flowchart with an MSBTFile, automatically populating
        msbt_label and text_preview on all MessageNode instances.
        """
        for node in self.nodes.values():
            if isinstance(node, MessageNode):
                if node.message_index < len(msbt.entries):
                    entry = msbt.entries[node.message_index]
                    node.msbt_label = entry.label
                    node.text_preview = entry.text

    def to_mermaid(self, entry_point: Optional[str] = None) -> str:
        """
        Generates a Mermaid Markdown flowchart diagram (flowchart TD)
        visualizing conversation paths and interactive player decision branches.
        """
        lines = ["flowchart TD"]

        # If specific entry point requested, filter from root
        active_entry_nodes = self.entries.items()
        if entry_point and entry_point in self.entries:
            active_entry_nodes = [(entry_point, self.entries[entry_point])]

        for name, root_id in active_entry_nodes:
            lines.append(f'  Entry_{name}["Entry: {name}"] --> Node_{root_id}')

        for node_id, node in sorted(self.nodes.items()):
            if isinstance(node, MessageNode):
                lbl_text = f"Msg {node.message_index}"
                if node.msbt_label:
                    lbl_text += f" ({node.msbt_label})"
                preview = node.text_preview.replace('"', "'").replace("\n", " ")[:30]
                if preview:
                    lbl_text += f": {preview}..."
                lines.append(f'  Node_{node_id}["{lbl_text}"]')
                if node.next_node_id is not None:
                    lines.append(f"  Node_{node_id} --> Node_{node.next_node_id}")

            elif isinstance(node, ChoiceNode):
                lines.append(f'  Node_{node_id}{{"Choice Point"}}')
                for opt_idx, target in enumerate(node.branch_targets):
                    opt_title = node.options[opt_idx] if opt_idx < len(node.options) else f"Option {opt_idx}"
                    lines.append(f'  Node_{node_id} -- "{opt_title}" --> Node_{target}')

            elif isinstance(node, EventNode):
                lines.append(f'  Node_{node_id}(["Event {node.event_id} (param={node.param})"])')
                if node.next_node_id is not None:
                    lines.append(f"  Node_{node_id} --> Node_{node.next_node_id}")
            else:
                lines.append(f"  Node_{node_id}[Node {node_id}]")

        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        """
        Exports the flowchart to a JSON-serializable dictionary.
        """
        node_records = []
        for n_id, n in sorted(self.nodes.items()):
            rec: Dict[str, Any] = {"id": n_id, "type": n.node_type}
            if isinstance(n, MessageNode):
                rec.update({
                    "message_index": n.message_index,
                    "next_node_id": n.next_node_id,
                    "msbt_label": n.msbt_label,
                    "text_preview": n.text_preview,
                })
            elif isinstance(n, ChoiceNode):
                rec.update({
                    "options": n.options,
                    "branch_targets": n.branch_targets,
                })
            elif isinstance(n, EventNode):
                rec.update({
                    "event_id": n.event_id,
                    "param": n.param,
                    "next_node_id": n.next_node_id,
                })
            node_records.append(rec)

        return {
            "endian": self.endian,
            "encoding": self.encoding,
            "entries": self.entries,
            "nodes": node_records,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MSBFFile:
        """
        Reconstructs an MSBFFile from an exported dictionary.
        """
        nodes_dict: Dict[int, FlowNode] = {}
        for rec in data.get("nodes", []):
            n_id = rec["id"]
            n_type = rec["type"]
            if n_type == NODE_TYPE_MESSAGE:
                nodes_dict[n_id] = MessageNode(
                    node_id=n_id,
                    message_index=rec.get("message_index", 0),
                    next_node_id=rec.get("next_node_id"),
                    msbt_label=rec.get("msbt_label", ""),
                    text_preview=rec.get("text_preview", ""),
                )
            elif n_type == NODE_TYPE_CHOICE:
                nodes_dict[n_id] = ChoiceNode(
                    node_id=n_id,
                    options=rec.get("options", []),
                    branch_targets=rec.get("branch_targets", []),
                )
            elif n_type == NODE_TYPE_EVENT:
                nodes_dict[n_id] = EventNode(
                    node_id=n_id,
                    event_id=rec.get("event_id", 0),
                    param=rec.get("param", 0),
                    next_node_id=rec.get("next_node_id"),
                )
            else:
                nodes_dict[n_id] = FlowNode(node_id=n_id, node_type=n_type)

        return cls(
            nodes=nodes_dict,
            entries=data.get("entries", {}),
            encoding=data.get("encoding", "utf-16"),
            endian=data.get("endian", ">"),
        )

    def to_bytes(self, endian: Optional[str] = None) -> bytes:
        """
        Serializes and repacks the entire MSBF file with automatic branch table assembly
        and 16-byte section padding.
        """
        used_endian = endian or self.endian
        bom = b"\xFE\xFF" if used_endian == ">" else b"\xFF\xFE"
        byte_order = "big" if used_endian == ">" else "little"
        enc_code = 0 if self.encoding == "utf-8" else 1

        # 1. Build FLW3 Section (Nodes + Branch Table)
        sorted_node_ids = sorted(self.nodes.keys())
        id_to_idx = {nid: idx for idx, nid in enumerate(sorted_node_ids)}

        branch_table: List[int] = []
        raw_node_structs: List[FLW3NodeStruct] = []

        all_options: List[str] = []

        for nid in sorted_node_ids:
            node = self.nodes[nid]
            if isinstance(node, MessageNode):
                next_idx = id_to_idx.get(node.next_node_id, 0xFFFF) if node.next_node_id is not None else 0xFFFF
                raw_node_structs.append(
                    FLW3NodeStruct(
                        node_type=NODE_TYPE_MESSAGE,
                        param1=0,
                        next_node_index=next_idx,
                        param2=0,
                        item_id=node.message_index,
                    )
                )
            elif isinstance(node, ChoiceNode):
                branch_start = len(branch_table)
                for t in node.branch_targets:
                    branch_table.append(id_to_idx.get(t, 0xFFFF))
                raw_node_structs.append(
                    FLW3NodeStruct(
                        node_type=NODE_TYPE_CHOICE,
                        param1=len(all_options),
                        next_node_index=branch_start,
                        param2=len(node.branch_targets),
                        item_id=0,
                    )
                )
                all_options.extend(node.options)
            elif isinstance(node, EventNode):
                next_idx = id_to_idx.get(node.next_node_id, 0xFFFF) if node.next_node_id is not None else 0xFFFF
                raw_node_structs.append(
                    FLW3NodeStruct(
                        node_type=NODE_TYPE_EVENT,
                        param1=node.param,
                        next_node_index=next_idx,
                        param2=0,
                        item_id=node.event_id,
                    )
                )
            else:
                raw_node_structs.append(
                    FLW3NodeStruct(
                        node_type=node.node_type,
                        param1=0,
                        next_node_index=0xFFFF,
                        param2=0,
                        item_id=0,
                    )
                )

        flw_header = FLW3HeaderStruct(
            node_count=len(raw_node_structs),
            branch_count=len(branch_table),
        )

        flw_payload = bytearray(flw_header.to_bytes(endian=used_endian))
        for n_st in raw_node_structs:
            flw_payload.extend(n_st.to_bytes(endian=used_endian))
        for b_target in branch_table:
            flw_payload.extend(b_target.to_bytes(2, byte_order))

        flw_pad = (16 - (len(flw_payload) % 16)) % 16
        flw_sec_hdr = MSBFSectionHeaderStruct(
            magic=SECTION_FLW3,
            size=len(flw_payload),
        )
        flw_section = flw_sec_hdr.to_bytes(endian=used_endian) + bytes(flw_payload) + (b"\x00" * flw_pad)

        # 2. Build FEN1 Section (Entry Points Hash Table)
        fen_payload = bytearray()
        num_slots = 1  # Standard simple 1-bucket layout
        fen_payload.extend(num_slots.to_bytes(4, byte_order))

        # Bucket descriptor: count(4), offset(4)
        entry_list = list(self.entries.items())
        count_entries = len(entry_list)
        entries_data_offset = 4 + num_slots * 8  # Relative to FEN1 payload start
        fen_payload.extend(count_entries.to_bytes(4, byte_order))
        fen_payload.extend(entries_data_offset.to_bytes(4, byte_order))

        for label, target_nid in entry_list:
            target_idx = id_to_idx.get(target_nid, 0)
            encoded_label = label.encode("ascii", errors="replace")
            fen_payload.append(len(encoded_label))
            fen_payload.extend(encoded_label)
            fen_payload.extend(target_idx.to_bytes(2, byte_order))

        fen_pad = (16 - (len(fen_payload) % 16)) % 16
        fen_sec_hdr = MSBFSectionHeaderStruct(
            magic=SECTION_FEN1,
            size=len(fen_payload),
        )
        fen_section = fen_sec_hdr.to_bytes(endian=used_endian) + bytes(fen_payload) + (b"\x00" * fen_pad)

        # 3. Build FOP1 Section (Choice Options)
        fop_payload = bytearray()
        fop_payload.extend(len(all_options).to_bytes(4, byte_order))
        codec = ("utf-16-be" if used_endian == ">" else "utf-16-le") if enc_code == 1 else "utf-8"
        null_terminator = b"\x00\x00" if enc_code == 1 else b"\x00"

        for opt_str in all_options:
            fop_payload.extend(opt_str.encode(codec, errors="replace") + null_terminator)

        fop_pad = (16 - (len(fop_payload) % 16)) % 16
        fop_sec_hdr = MSBFSectionHeaderStruct(
            magic=SECTION_FOP1,
            size=len(fop_payload),
        )
        fop_section = fop_sec_hdr.to_bytes(endian=used_endian) + bytes(fop_payload) + (b"\x00" * fop_pad)

        # 4. Assemble Entire MSBF
        total_file_size = MSBFHeaderStruct.sizeof() + len(flw_section) + len(fen_section) + len(fop_section)
        root_hdr = MSBFHeaderStruct(
            magic=MSBF_MAGIC,
            bom=bom,
            encoding=enc_code,
            version=3,
            section_count=3,
            file_size=total_file_size,
        )

        return root_hdr.to_bytes(endian=used_endian) + flw_section + fen_section + fop_section

    def save(self, filepath: Union[str, os.PathLike]) -> None:
        """
        Saves the repacked MSBF container to disk.
        """
        with open(filepath, "wb") as f:
            f.write(self.to_bytes())


# ==============================================================================
# Helper / Factory Functions
# ==============================================================================

def create_synthetic_msbf(
    nodes: Sequence[FlowNode],
    entries: Optional[Dict[str, int]] = None,
    encoding: str = "utf-16",
    endian: str = ">",
) -> bytes:
    """
    Scaffolding utility to create a valid synthetic .msbf container for tests.
    """
    nodes_map = {n.node_id: n for n in nodes}
    msbf = MSBFFile(
        nodes=nodes_map,
        entries=entries or {},
        encoding=encoding,
        endian=endian,
    )
    return msbf.to_bytes()
