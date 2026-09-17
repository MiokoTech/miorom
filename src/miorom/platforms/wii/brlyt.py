"""
Nintendo Wii BRLYT (Binary Revolution Layout) UI Layout Engine.
Provides low-level declarative structures (BinaryStruct), section manipulation,
and a high-level analytical object model (BRLYTFile, BasePane, TextBoxPane, PicturePane)
for reverse engineering, font remapping, and UI localization.
Powered by MioROM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

from miorom.core.binary import BinaryReader, BinaryWriter
from miorom.core.schema import (
    U8,
    U16,
    U32,
    BinaryStruct,
    FixedString,
    Float32,
    RawBytes,
)
from miorom.errors import ParseError

# ==============================================================================
# Low-Level Binary Structures (Layer 1)
# ==============================================================================


class BRLYTHeaderStruct(BinaryStruct):
    """
    Standard 16-byte BRLYT file header.
    Format:
      magic (4s): 'RLYT'
      bom (u16): 0xFEFF (Big Endian)
      version (u16): 0x0008 or 0x000A
      file_size (u32): Total size in bytes
      header_size (u16): Header size (0x0010)
      section_count (u16): Total number of sections
    """
    _endian = ">"
    magic = RawBytes(4, default=b"RLYT")
    bom = U16(default=0xFEFF)
    version = U16(default=0x000A)
    file_size = U32(default=0)
    header_size = U16(default=16)
    section_count = U16(default=0)


class BRLYTSectionHeaderStruct(BinaryStruct):
    """Standard 8-byte chunk section header."""
    _endian = ">"
    magic = RawBytes(4, default=b"pan1")
    size = U32(default=0)


class BRLYTLyt1Struct(BinaryStruct):
    """
    Layout screen dimension section (lyt1) payload (without 8-byte section header).
    Total size: 12 bytes.
    """
    _endian = ">"
    centered = U8(default=1)
    pad = RawBytes(3, default=b"\x00\x00\x00")
    width = Float32(default=640.0)
    height = Float32(default=480.0)


class BRLYTResourceListHeaderStruct(BinaryStruct):
    """
    Header for resource lists such as txl1 (textures) and fnl1 (fonts).
    Total size: 4 bytes payload (without 8-byte section header).
    Followed by count * 4 offset table, then null-terminated string table.
    """
    _endian = ">"
    count = U16(default=0)
    pad = U16(default=0)


class BRLYTPaneStruct(BinaryStruct):
    """
    Standard pane (pan1) payload (without 8-byte section header).
    Total payload size: 68 bytes (total section size: 76 bytes).
    """
    _endian = ">"
    flag = U8(default=1)
    origin = U8(default=0)
    alpha = U8(default=255)
    pad = U8(default=0)
    name = FixedString(16, default="")
    x = Float32(default=0.0)
    y = Float32(default=0.0)
    z = Float32(default=0.0)
    rot_x = Float32(default=0.0)
    rot_y = Float32(default=0.0)
    rot_z = Float32(default=0.0)
    pad2 = RawBytes(8, default=b"\x00" * 8)
    scale_x = Float32(default=1.0)
    scale_y = Float32(default=1.0)
    width = Float32(default=0.0)
    height = Float32(default=0.0)


class BRLYTPic1Struct(BinaryStruct):
    """
    Picture pane (pic1) payload (without 8-byte section header).
    Contains pane base fields plus vertex colors, material index, and UV coordinates.
    Total payload size: 120 bytes (total section size: 128 bytes).
    """
    _endian = ">"
    flag = U8(default=1)
    origin = U8(default=0)
    alpha = U8(default=255)
    pad = U8(default=0)
    name = FixedString(16, default="")
    x = Float32(default=0.0)
    y = Float32(default=0.0)
    z = Float32(default=0.0)
    rot_x = Float32(default=0.0)
    rot_y = Float32(default=0.0)
    rot_z = Float32(default=0.0)
    pad2 = RawBytes(8, default=b"\x00" * 8)
    scale_x = Float32(default=1.0)
    scale_y = Float32(default=1.0)
    width = Float32(default=0.0)
    height = Float32(default=0.0)
    # Picture-specific fields (52 bytes)
    vertex_colors = RawBytes(16, default=b"\xff" * 16)
    material_idx = U16(default=0)
    uv_count = U8(default=1)
    pad3 = U8(default=0)
    uv_coords = RawBytes(32, default=b"\x00" * 32)


class BRLYTTxt1Struct(BinaryStruct):
    """
    TextBox pane (txt1) payload header (without 8-byte section header).
    Total header payload size: 108 bytes (total section header + payload: 116 bytes).
    Followed by UTF-16-BE string bytes.
    """
    _endian = ">"
    # Base pane fields (68 bytes)
    flag = U8(default=1)
    origin = U8(default=0)
    alpha = U8(default=255)
    pad = U8(default=0)
    name = FixedString(16, default="")
    x = Float32(default=0.0)
    y = Float32(default=0.0)
    z = Float32(default=0.0)
    rot_x = Float32(default=0.0)
    rot_y = Float32(default=0.0)
    rot_z = Float32(default=0.0)
    pad2 = RawBytes(8, default=b"\x00" * 8)
    scale_x = Float32(default=1.0)
    scale_y = Float32(default=1.0)
    width = Float32(default=0.0)
    height = Float32(default=0.0)

    # TextBox-specific fields (40 bytes)
    str_buf_len = U16(default=0)
    str_len = U16(default=0)
    material_idx = U16(default=0xFFFF)
    font_idx = U16(default=0)
    text_position = U8(default=0)
    text_alignment = U8(default=0)
    pad3 = RawBytes(2, default=b"\x00\x00")
    text_offset = U32(default=116)
    top_color = RawBytes(4, default=b"\xff\xff\xff\xff")
    bottom_color = RawBytes(4, default=b"\xff\xff\xff\xff")
    font_size_x = Float32(default=24.0)
    font_size_y = Float32(default=24.0)
    char_space = Float32(default=0.0)
    line_space = Float32(default=0.0)


# ==============================================================================
# Resource List Serialization Helpers
# ==============================================================================


def parse_resource_list(sec_bytes: bytes) -> List[str]:
    """
    Parses a txl1 (textures) or fnl1 (fonts) section into a list of resource names.
    sec_bytes includes the 8-byte section header.
    """
    if len(sec_bytes) < 12:
        return []

    count = BinaryReader.unpack_u16(sec_bytes, 8, endian=">")
    if count == 0:
        return []

    offsets: List[int] = []
    pos = 12
    for _ in range(count):
        if pos + 4 > len(sec_bytes):
            break
        off = BinaryReader.unpack_u32(sec_bytes, pos, endian=">")
        offsets.append(off)
        pos += 4

    results: List[str] = []
    sec_len = len(sec_bytes)
    for off in offsets:
        str_offset = off
        if str_offset >= sec_len or str_offset < 8:
            str_offset = 8 + off
        if str_offset < sec_len:
            end = sec_bytes.find(b"\x00", str_offset)
            if end == -1:
                end = sec_len
            name = sec_bytes[str_offset:end].decode("latin1", errors="replace")
            results.append(name)
        else:
            results.append("")
    return results


def build_resource_list(magic: bytes, names: List[str]) -> bytes:
    """
    Builds a complete txl1 or fnl1 section chunk from a list of resource names.
    Section is strictly 4-byte aligned.
    """
    count = len(names)
    table_offset = 8 + 4 + (count * 4)
    string_data = bytearray()
    offsets: List[int] = []

    for name in names:
        offsets.append(table_offset + len(string_data))
        string_data.extend(name.encode("latin1") + b"\x00")

    writer = BinaryWriter(endian=">")
    writer.write_u16(count)
    writer.write_u16(0)  # pad
    for off in offsets:
        writer.write_u32(off)
    writer.write_bytes(bytes(string_data))

    payload = writer.to_bytes()
    pad_len = (4 - (len(payload) % 4)) % 4
    payload += b"\x00" * pad_len

    sec_size = 8 + len(payload)
    sec_hdr = BRLYTSectionHeaderStruct(magic=magic, size=sec_size).to_bytes()
    return sec_hdr + payload


# ==============================================================================
# Low-Level Section Parser & Rebuilder (Backward Compatibility)
# ==============================================================================


def parse_brlyt_sections(data: bytes) -> Tuple[BRLYTHeaderStruct, List[Tuple[str, bytes]]]:
    """
    Parses a BRLYT file into its file header and a list of raw (magic, section_bytes) tuples.
    Each section_bytes contains the full section data including its 8-byte chunk header.
    """
    if len(data) < BRLYTHeaderStruct.sizeof():
        raise ParseError(f"Data too short for BRLYT header ({len(data)} bytes).")

    header = BRLYTHeaderStruct.from_bytes(data, offset=0)
    if header.magic != b"RLYT":
        raise ParseError(f"Invalid BRLYT magic: expected b'RLYT', got {header.magic!r}")

    sections: List[Tuple[str, bytes]] = []
    pos = header.header_size
    data_len = len(data)

    while pos < data_len:
        if pos + 8 > data_len:
            break
        sec_magic = data[pos : pos + 4].decode("latin1", errors="replace")
        sec_size = BinaryReader.unpack_u32(data, pos + 4, endian=">")
        if sec_size == 0 or pos + sec_size > data_len:
            break
        sec_bytes = data[pos : pos + sec_size]
        sections.append((sec_magic, sec_bytes))
        pos += sec_size

    return header, sections


def rebuild_brlyt(
    header: BRLYTHeaderStruct,
    sections: List[Tuple[str, bytes]],
) -> bytes:
    """
    Rebuilds BRLYT binary bytes from a header and modified list of sections.
    Updates file_size and section_count automatically.
    """
    writer = BinaryWriter(endian=">")
    total_sections = len(sections)
    body_bytes = b"".join(s_bytes for _, s_bytes in sections)
    total_size = header.header_size + len(body_bytes)

    updated_header = BRLYTHeaderStruct(
        magic=header.magic,
        bom=header.bom,
        version=header.version,
        file_size=total_size,
        header_size=header.header_size,
        section_count=total_sections,
    )

    writer.write_struct(updated_header)
    writer.write_bytes(body_bytes)
    return writer.to_bytes()


def find_pane(
    sections: List[Tuple[str, bytes]],
    pane_name: str,
) -> Optional[Tuple[int, str, Union[BRLYTPaneStruct, BRLYTPic1Struct, BRLYTTxt1Struct]]]:
    """
    Searches sections for a pane with the matching name.
    Returns (section_index, magic, struct_instance) or None if not found.
    """
    target_name = pane_name.rstrip("\x00")
    for idx, (magic, sec_bytes) in enumerate(sections):
        if magic in ("pan1", "pic1", "txt1"):
            if len(sec_bytes) >= 28:
                payload = sec_bytes[8:]
                struct_inst: Union[BRLYTPaneStruct, BRLYTPic1Struct, BRLYTTxt1Struct]
                if magic == "pan1":
                    struct_inst = BRLYTPaneStruct.from_bytes(payload)
                elif magic == "pic1":
                    struct_inst = BRLYTPic1Struct.from_bytes(payload)
                else:
                    struct_inst = BRLYTTxt1Struct.from_bytes(payload[: BRLYTTxt1Struct.sizeof()])
                if struct_inst.name.rstrip("\x00") == target_name:
                    return (idx, magic, struct_inst)
    return None


def update_pane(
    sections: List[Tuple[str, bytes]],
    pane_index: int,
    pane_struct: Union[BRLYTPaneStruct, BRLYTPic1Struct, BRLYTTxt1Struct],
) -> List[Tuple[str, bytes]]:
    """
    Replaces the pane payload at pane_index with the serialized pane_struct.
    Returns the updated sections list.
    """
    magic, orig_bytes = sections[pane_index]
    if isinstance(pane_struct, BRLYTTxt1Struct):
        # Preserve original trailing string buffer if present
        header_len = 8 + BRLYTTxt1Struct.sizeof()
        orig_str_buf = orig_bytes[header_len:] if len(orig_bytes) > header_len else b""
        new_payload = pane_struct.to_bytes() + orig_str_buf
    else:
        new_payload = pane_struct.to_bytes()
    new_size = 8 + len(new_payload)
    sec_header = BRLYTSectionHeaderStruct(magic=magic.encode("latin1"), size=new_size)
    new_sec_bytes = sec_header.to_bytes() + new_payload
    sections[pane_index] = (magic, new_sec_bytes)
    return sections


# ==============================================================================
# High-Level Object Model & Tree Hierarchy (Layer 2)
# ==============================================================================


class BasePane:
    """
    Base class for all BRLYT pane elements with hierarchical parent-child relationships.
    """

    def __init__(
        self,
        name: str = "",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        rot_x: float = 0.0,
        rot_y: float = 0.0,
        rot_z: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        width: float = 0.0,
        height: float = 0.0,
        alpha: int = 255,
        flag: int = 1,
        origin: int = 0,
        parent: Optional[BasePane] = None,
    ) -> None:
        self.name: str = name
        self.x: float = float(x)
        self.y: float = float(y)
        self.z: float = float(z)
        self.rot_x: float = float(rot_x)
        self.rot_y: float = float(rot_y)
        self.rot_z: float = float(rot_z)
        self.scale_x: float = float(scale_x)
        self.scale_y: float = float(scale_y)
        self.width: float = float(width)
        self.height: float = float(height)
        self.alpha: int = int(alpha)
        self.flag: int = int(flag)
        self.origin: int = int(origin)
        self.parent: Optional[BasePane] = parent
        self.children: List[BasePane] = []

    def add_child(self, child: BasePane) -> BasePane:
        """Adds a child pane to this pane."""
        child.parent = self
        self.children.append(child)
        return child

    def remove_child(self, child: BasePane) -> None:
        """Removes a child pane from this pane."""
        if child in self.children:
            self.children.remove(child)
            child.parent = None

    def iter_tree(self) -> Iterator[BasePane]:
        """Pre-order traversal generator yielding self and all descendants."""
        yield self
        for child in self.children:
            yield from child.iter_tree()

    def find_pane(self, name: str) -> Optional[BasePane]:
        """Finds a descendant pane by name."""
        target = name.rstrip("\x00")
        for p in self.iter_tree():
            if p.name.rstrip("\x00") == target:
                return p
        return None

    def find_text_boxes(self) -> List[TextBoxPane]:
        """Returns all TextBoxPane descendants in this tree."""
        return [p for p in self.iter_tree() if isinstance(p, TextBoxPane)]

    def to_section(self) -> Tuple[str, bytes]:
        """Serializes this pane into a raw (magic, section_bytes) tuple."""
        raise NotImplementedError("Subclasses must implement to_section()")


class Pane(BasePane):
    """Standard container pane (pan1)."""

    def to_section(self) -> Tuple[str, bytes]:
        struct_inst = BRLYTPaneStruct(
            flag=self.flag,
            origin=self.origin,
            alpha=self.alpha,
            name=self.name,
            x=self.x,
            y=self.y,
            z=self.z,
            rot_x=self.rot_x,
            rot_y=self.rot_y,
            rot_z=self.rot_z,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            width=self.width,
            height=self.height,
        )
        payload = struct_inst.to_bytes()
        sec_size = 8 + len(payload)
        sec_hdr = BRLYTSectionHeaderStruct(magic=b"pan1", size=sec_size).to_bytes()
        return ("pan1", sec_hdr + payload)


class PicturePane(BasePane):
    """Image or texture rendering pane (pic1)."""

    def __init__(
        self,
        name: str = "",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        rot_x: float = 0.0,
        rot_y: float = 0.0,
        rot_z: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        width: float = 0.0,
        height: float = 0.0,
        alpha: int = 255,
        flag: int = 1,
        origin: int = 0,
        parent: Optional[BasePane] = None,
        material_idx: int = 0,
        vertex_colors: bytes = b"\xff" * 16,
        uv_coords: bytes = b"\x00" * 32,
        uv_count: int = 1,
    ) -> None:
        super().__init__(
            name=name,
            x=x,
            y=y,
            z=z,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            scale_x=scale_x,
            scale_y=scale_y,
            width=width,
            height=height,
            alpha=alpha,
            flag=flag,
            origin=origin,
            parent=parent,
        )
        self.material_idx: int = material_idx
        self.vertex_colors: bytes = vertex_colors
        self.uv_coords: bytes = uv_coords
        self.uv_count: int = uv_count

    def to_section(self) -> Tuple[str, bytes]:
        struct_inst = BRLYTPic1Struct(
            flag=self.flag,
            origin=self.origin,
            alpha=self.alpha,
            name=self.name,
            x=self.x,
            y=self.y,
            z=self.z,
            rot_x=self.rot_x,
            rot_y=self.rot_y,
            rot_z=self.rot_z,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            width=self.width,
            height=self.height,
            vertex_colors=self.vertex_colors,
            material_idx=self.material_idx,
            uv_count=self.uv_count,
            uv_coords=self.uv_coords,
        )
        payload = struct_inst.to_bytes()
        sec_size = 8 + len(payload)
        sec_hdr = BRLYTSectionHeaderStruct(magic=b"pic1", size=sec_size).to_bytes()
        return ("pic1", sec_hdr + payload)


class TextBoxPane(BasePane):
    """
    Rich text rendering pane (txt1) with UTF-16-BE string buffers,
    font bindings, and alignment options.
    """

    def __init__(
        self,
        name: str = "",
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
        rot_x: float = 0.0,
        rot_y: float = 0.0,
        rot_z: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        width: float = 0.0,
        height: float = 0.0,
        alpha: int = 255,
        flag: int = 1,
        origin: int = 0,
        parent: Optional[BasePane] = None,
        text: str = "",
        str_buf_len: int = 0,
        str_len: int = 0,
        material_idx: int = 0xFFFF,
        font_idx: int = 0,
        font_name: str = "",
        text_position: int = 0,
        text_alignment: int = 0,
        top_color: bytes = b"\xff\xff\xff\xff",
        bottom_color: bytes = b"\xff\xff\xff\xff",
        font_size_x: float = 24.0,
        font_size_y: float = 24.0,
        char_space: float = 0.0,
        line_space: float = 0.0,
    ) -> None:
        super().__init__(
            name=name,
            x=x,
            y=y,
            z=z,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            scale_x=scale_x,
            scale_y=scale_y,
            width=width,
            height=height,
            alpha=alpha,
            flag=flag,
            origin=origin,
            parent=parent,
        )
        self.text: str = text
        self.str_len: int = str_len if str_len > 0 else len(text.encode("utf-16-be"))
        self.str_buf_len: int = max(str_buf_len, self.str_len + 2)
        self.material_idx: int = material_idx
        self.font_idx: int = font_idx
        self.font_name: str = font_name
        self.text_position: int = text_position
        self.text_alignment: int = text_alignment
        self.top_color: bytes = top_color
        self.bottom_color: bytes = bottom_color
        self.font_size_x: float = float(font_size_x)
        self.font_size_y: float = float(font_size_y)
        self.char_space: float = float(char_space)
        self.line_space: float = float(line_space)

    def to_section(self) -> Tuple[str, bytes]:
        encoded_text = self.text.encode("utf-16-be")
        actual_len = len(encoded_text)
        buf_len = max(self.str_buf_len, actual_len + 2)
        buf_len = (buf_len + 3) & ~3  # align to 4 bytes

        str_payload = encoded_text + b"\x00\x00"
        if len(str_payload) < buf_len:
            str_payload += b"\x00" * (buf_len - len(str_payload))

        struct_inst = BRLYTTxt1Struct(
            flag=self.flag,
            origin=self.origin,
            alpha=self.alpha,
            name=self.name,
            x=self.x,
            y=self.y,
            z=self.z,
            rot_x=self.rot_x,
            rot_y=self.rot_y,
            rot_z=self.rot_z,
            scale_x=self.scale_x,
            scale_y=self.scale_y,
            width=self.width,
            height=self.height,
            str_buf_len=buf_len,
            str_len=actual_len,
            material_idx=self.material_idx,
            font_idx=self.font_idx,
            text_position=self.text_position,
            text_alignment=self.text_alignment,
            text_offset=116,
            top_color=self.top_color,
            bottom_color=self.bottom_color,
            font_size_x=self.font_size_x,
            font_size_y=self.font_size_y,
            char_space=self.char_space,
            line_space=self.line_space,
        )
        payload = struct_inst.to_bytes() + str_payload
        pad_len = (4 - (len(payload) % 4)) % 4
        payload += b"\x00" * pad_len
        sec_size = 8 + len(payload)
        sec_hdr = BRLYTSectionHeaderStruct(magic=b"txt1", size=sec_size).to_bytes()
        return ("txt1", sec_hdr + payload)


class GenericPane(BasePane):
    """Fallback representation preserving arbitrary or vendor-specific pane chunks."""

    def __init__(self, magic: str, raw_payload: bytes, **kwargs) -> None:
        super().__init__(**kwargs)
        self.magic: str = magic
        self.raw_payload: bytes = raw_payload

    def to_section(self) -> Tuple[str, bytes]:
        sec_size = 8 + len(self.raw_payload)
        sec_hdr = BRLYTSectionHeaderStruct(magic=self.magic.encode("latin1"), size=sec_size).to_bytes()
        return (self.magic, sec_hdr + self.raw_payload)


# ==============================================================================
# BRLYT File High-Level Layout Manager
# ==============================================================================


class BRLYTFile:
    """
    High-level manager for Nintendo Wii BRLYT UI layouts.
    Reconstructs the hierarchical pane tree, resolves textures/fonts,
    and provides surgical inspection and modification APIs.
    """

    def __init__(
        self,
        header: Optional[BRLYTHeaderStruct] = None,
        layout_info: Optional[BRLYTLyt1Struct] = None,
        textures: Optional[List[str]] = None,
        fonts: Optional[List[str]] = None,
        root_pane: Optional[BasePane] = None,
    ) -> None:
        self.header: BRLYTHeaderStruct = header or BRLYTHeaderStruct()
        self.layout_info: BRLYTLyt1Struct = layout_info or BRLYTLyt1Struct()
        self.textures: List[str] = list(textures or [])
        self.fonts: List[str] = list(fonts or [])
        self.root_pane: Optional[BasePane] = root_pane
        self.other_sections_pre: List[Tuple[str, bytes]] = []
        self.other_sections_post: List[Tuple[str, bytes]] = []

    @classmethod
    def from_bytes(cls, data: bytes) -> BRLYTFile:
        """Parses complete BRLYT binary data into a BRLYTFile object model."""
        header, sections = parse_brlyt_sections(data)
        instance = cls(header=header)

        parent_stack: List[BasePane] = []
        last_pane: Optional[BasePane] = None
        panes_started = False

        for magic, sec_bytes in sections:
            if magic == "lyt1":
                if len(sec_bytes) >= 20:
                    instance.layout_info = BRLYTLyt1Struct.from_bytes(sec_bytes[8:20])
            elif magic == "txl1":
                instance.textures = parse_resource_list(sec_bytes)
            elif magic == "fnl1":
                instance.fonts = parse_resource_list(sec_bytes)
            elif magic == "pan1":
                panes_started = True
                pan_struct = BRLYTPaneStruct.from_bytes(sec_bytes[8:76])
                pane = Pane(
                    name=pan_struct.name.rstrip("\x00"),
                    x=pan_struct.x,
                    y=pan_struct.y,
                    z=pan_struct.z,
                    rot_x=pan_struct.rot_x,
                    rot_y=pan_struct.rot_y,
                    rot_z=pan_struct.rot_z,
                    scale_x=pan_struct.scale_x,
                    scale_y=pan_struct.scale_y,
                    width=pan_struct.width,
                    height=pan_struct.height,
                    alpha=pan_struct.alpha,
                    flag=pan_struct.flag,
                    origin=pan_struct.origin,
                )
                instance._attach_pane(pane, parent_stack)
                last_pane = pane
            elif magic == "pic1":
                panes_started = True
                pic_struct = BRLYTPic1Struct.from_bytes(sec_bytes[8:128])
                pane = PicturePane(
                    name=pic_struct.name.rstrip("\x00"),
                    x=pic_struct.x,
                    y=pic_struct.y,
                    z=pic_struct.z,
                    rot_x=pic_struct.rot_x,
                    rot_y=pic_struct.rot_y,
                    rot_z=pic_struct.rot_z,
                    scale_x=pic_struct.scale_x,
                    scale_y=pic_struct.scale_y,
                    width=pic_struct.width,
                    height=pic_struct.height,
                    alpha=pic_struct.alpha,
                    flag=pic_struct.flag,
                    origin=pic_struct.origin,
                    material_idx=pic_struct.material_idx,
                    vertex_colors=pic_struct.vertex_colors,
                    uv_coords=pic_struct.uv_coords,
                    uv_count=pic_struct.uv_count,
                )
                instance._attach_pane(pane, parent_stack)
                last_pane = pane
            elif magic == "txt1":
                panes_started = True
                min_sec_size = 8 + BRLYTTxt1Struct.sizeof()
                if len(sec_bytes) < min_sec_size:
                    raise ParseError(f"txt1 section too short ({len(sec_bytes)} bytes)")
                txt_struct = BRLYTTxt1Struct.from_bytes(sec_bytes[8:min_sec_size])
                str_offset = txt_struct.text_offset
                if str_offset >= len(sec_bytes) or str_offset < min_sec_size:
                    str_offset = 8 + txt_struct.text_offset
                    if str_offset >= len(sec_bytes) or str_offset < min_sec_size:
                        str_offset = min_sec_size

                str_len = txt_struct.str_len
                str_bytes = sec_bytes[str_offset : str_offset + str_len]
                text = str_bytes.decode("utf-16-be", errors="replace")

                font_name = (
                    instance.fonts[txt_struct.font_idx]
                    if txt_struct.font_idx < len(instance.fonts)
                    else ""
                )

                pane = TextBoxPane(
                    name=txt_struct.name.rstrip("\x00"),
                    x=txt_struct.x,
                    y=txt_struct.y,
                    z=txt_struct.z,
                    rot_x=txt_struct.rot_x,
                    rot_y=txt_struct.rot_y,
                    rot_z=txt_struct.rot_z,
                    scale_x=txt_struct.scale_x,
                    scale_y=txt_struct.scale_y,
                    width=txt_struct.width,
                    height=txt_struct.height,
                    alpha=txt_struct.alpha,
                    flag=txt_struct.flag,
                    origin=txt_struct.origin,
                    text=text,
                    str_buf_len=txt_struct.str_buf_len,
                    str_len=str_len,
                    material_idx=txt_struct.material_idx,
                    font_idx=txt_struct.font_idx,
                    font_name=font_name,
                    text_position=txt_struct.text_position,
                    text_alignment=txt_struct.text_alignment,
                    top_color=txt_struct.top_color,
                    bottom_color=txt_struct.bottom_color,
                    font_size_x=txt_struct.font_size_x,
                    font_size_y=txt_struct.font_size_y,
                    char_space=txt_struct.char_space,
                    line_space=txt_struct.line_space,
                )
                instance._attach_pane(pane, parent_stack)
                last_pane = pane
            elif magic == "pas1":
                if last_pane is None:
                    raise ParseError("Hierarchy error: pas1 encountered without preceding pane.")
                parent_stack.append(last_pane)
            elif magic == "pae1":
                if not parent_stack:
                    raise ParseError("Hierarchy error: unmatched pae1 encountered.")
                parent_stack.pop()
            else:
                if not panes_started:
                    instance.other_sections_pre.append((magic, sec_bytes))
                else:
                    instance.other_sections_post.append((magic, sec_bytes))

        return instance

    def _attach_pane(self, pane: BasePane, parent_stack: List[BasePane]) -> None:
        """Attaches a pane to its parent on the stack, or sets as root."""
        if parent_stack:
            parent_stack[-1].add_child(pane)
        else:
            if self.root_pane is None:
                self.root_pane = pane
            else:
                if not (isinstance(self.root_pane, Pane) and self.root_pane.name == "__root__"):
                    virtual_root = Pane(name="__root__")
                    virtual_root.add_child(self.root_pane)
                    self.root_pane = virtual_root
                self.root_pane.add_child(pane)

    def to_bytes(self) -> bytes:
        """Serializes the layout and pane hierarchy into valid BRLYT binary bytes."""
        sections: List[Tuple[str, bytes]] = []

        # 1. lyt1
        sections.append(
            ("lyt1", BRLYTSectionHeaderStruct(magic=b"lyt1", size=20).to_bytes() + self.layout_info.to_bytes())
        )

        # 2. txl1
        if self.textures:
            sections.append(("txl1", build_resource_list(b"txl1", self.textures)))

        # 3. fnl1
        if self.fonts:
            sections.append(("fnl1", build_resource_list(b"fnl1", self.fonts)))

        # 4. Other pre-pane sections (e.g. mat1)
        sections.extend(self.other_sections_pre)

        # 5. Pane hierarchy
        if self.root_pane is not None:
            if self.root_pane.name == "__root__":
                for child in self.root_pane.children:
                    sections.extend(self._serialize_pane_tree(child))
            else:
                sections.extend(self._serialize_pane_tree(self.root_pane))

        # 6. Other post-pane sections (e.g. grp1)
        sections.extend(self.other_sections_post)

        return rebuild_brlyt(self.header, sections)

    def _serialize_pane_tree(self, pane: BasePane) -> List[Tuple[str, bytes]]:
        """Recursively flattens pane hierarchy with pas1 / pae1 bracket chunks."""
        result: List[Tuple[str, bytes]] = [pane.to_section()]
        if pane.children:
            result.append(("pas1", BRLYTSectionHeaderStruct(magic=b"pas1", size=8).to_bytes()))
            for child in pane.children:
                result.extend(self._serialize_pane_tree(child))
            result.append(("pae1", BRLYTSectionHeaderStruct(magic=b"pae1", size=8).to_bytes()))
        return result

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> BRLYTFile:
        """Loads and parses a BRLYT file from disk."""
        return cls.from_bytes(Path(path).read_bytes())

    def save(self, path: Union[str, Path]) -> None:
        """Serializes and writes the BRLYT file to disk."""
        Path(path).write_bytes(self.to_bytes())

    # ==========================================================================
    # Analytical Queries & Surgical Mutations
    # ==========================================================================

    def find_pane(self, name: str) -> Optional[BasePane]:
        """Finds a pane across the entire layout hierarchy by name."""
        if self.root_pane is None:
            return None
        return self.root_pane.find_pane(name)

    def find_text_boxes(self) -> List[TextBoxPane]:
        """Returns all TextBoxPanes in the layout."""
        if self.root_pane is None:
            return []
        return self.root_pane.find_text_boxes()

    def get_text(self, pane_name: str) -> str:
        """Retrieves the text of a specific TextBoxPane."""
        pane = self.find_pane(pane_name)
        if pane is None:
            raise KeyError(f"Pane {pane_name!r} not found in layout.")
        if not isinstance(pane, TextBoxPane):
            raise ValueError(f"Pane {pane_name!r} is not a TextBoxPane ({type(pane).__name__}).")
        return pane.text

    def set_text(
        self,
        pane_name_or_pane: Union[str, TextBoxPane],
        text: str,
        expand_buffer: bool = True,
    ) -> None:
        """
        Sets the string content of a TextBoxPane.

        Args:
            pane_name_or_pane: Name string of target pane or TextBoxPane instance.
            text: New text string to assign.
            expand_buffer: If True, automatically increases str_buf_len if needed.
                           If False, raises ValueError when text exceeds allocated RAM buffer.
        """
        if isinstance(pane_name_or_pane, str):
            pane = self.find_pane(pane_name_or_pane)
            if pane is None:
                raise KeyError(f"Pane {pane_name_or_pane!r} not found in layout.")
        else:
            pane = pane_name_or_pane

        if not isinstance(pane, TextBoxPane):
            raise ValueError(f"Target pane is not a TextBoxPane ({type(pane).__name__}).")

        encoded = text.encode("utf-16-be")
        needed_bytes = len(encoded) + 2  # including null terminator

        if needed_bytes > pane.str_buf_len:
            if not expand_buffer:
                raise ValueError(
                    f"Text byte length ({needed_bytes} bytes) exceeds allocated buffer "
                    f"capacity ({pane.str_buf_len} bytes) for TextBoxPane {pane.name!r}."
                )
            pane.str_buf_len = (needed_bytes + 3) & ~3

        pane.text = text
        pane.str_len = len(encoded)

    def export_strings(self) -> Dict[str, str]:
        """Exports all textbox strings as a localization dictionary {pane_name: text}."""
        return {tb.name: tb.text for tb in self.find_text_boxes()}

    def import_strings(self, data: Dict[str, str], expand_buffer: bool = True) -> int:
        """
        Imports strings from a dictionary into matching TextBoxPanes.
        Returns the number of panes updated.
        """
        count = 0
        for name, text in data.items():
            pane = self.find_pane(name)
            if isinstance(pane, TextBoxPane):
                self.set_text(pane, text, expand_buffer=expand_buffer)
                count += 1
        return count

    def remap_font(self, target_font: str, replacement_font: str) -> int:
        """
        Remaps all text boxes using target_font to replacement_font.
        Synchronizes the fnl1 font list automatically.
        Returns the number of text boxes modified.
        """
        if replacement_font not in self.fonts:
            self.fonts.append(replacement_font)
        new_idx = self.fonts.index(replacement_font)

        count = 0
        for tb in self.find_text_boxes():
            is_match = False
            if tb.font_name and tb.font_name == target_font:
                is_match = True
            elif tb.font_idx < len(self.fonts) and self.fonts[tb.font_idx] == target_font:
                is_match = True

            if is_match:
                tb.font_idx = new_idx
                tb.font_name = replacement_font
                count += 1

        return count
